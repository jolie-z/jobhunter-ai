# app/services/holiday_calendar.py
"""中国法定节假日数据（chinese-calendar 包）覆盖状态检查与一键在线升级。

国务院每年 11-12 月发布下一年度放假安排，chinese-calendar 社区随后发版收录。
本模块负责：
1. 查询当前安装的数据覆盖到哪一年（供前端判断是否透出「更新节假日数据」按钮）；
2. 一键升级：pip 拉新版 + 进程内热加载（清 sys.modules 重新导入），后端无需重启。

fail-open 约定与 scheduler._check_non_workday 一致：数据缺失/未覆盖只降级不阻断。
"""
import logging
import shutil
import subprocess
import sys
import threading
from datetime import date
from importlib import import_module, metadata, util

logger = logging.getLogger(__name__)

PACKAGE_NAME = "chinese-calendar"
UPDATE_TIMEOUT_SEC = 180

# 防止重复点击/并发触发两路 pip 升级
_update_lock = threading.Lock()


def _coverage_year() -> int | None:
    """数据覆盖的最大年份；包未安装或结构异常返回 None。"""
    try:
        import chinese_calendar as cc
        return max(cc.holidays).year
    except Exception:
        return None


def _package_version() -> str:
    try:
        return metadata.version(PACKAGE_NAME)
    except Exception:
        return "unknown"


def get_holiday_data_status() -> dict:
    """当前节假日数据状态。stale_soon=下一年安排未收录（12月透出按钮）；
    stale_critical=连当年都覆盖不了（fail-open 已退化为只跳周末，任何时候都提醒）。"""
    today = date.today()
    covered = _coverage_year()
    return {
        "installed": covered is not None,
        "covered_year": covered,
        "current_year": today.year,
        "next_year": today.year + 1,
        "stale_soon": covered is None or covered < today.year + 1,
        "stale_critical": covered is None or covered < today.year,
        "version": _package_version(),
    }


def _reload_module() -> int | None:
    """pip 升级后进程内热加载：旧模块对象已缓存 import 结果，须整体丢弃再重导入。"""
    stale_names = [m for m in list(sys.modules) if m == "chinese_calendar" or m.startswith("chinese_calendar.")]
    for name in stale_names:
        del sys.modules[name]
    try:
        cc = import_module("chinese_calendar")
        return max(cc.holidays).year
    except Exception as e:
        logger.error(f"[holiday_calendar] 热加载 chinese-calendar 失败: {e}")
        return None


def _install_command() -> list[str] | None:
    """拼出适用于当前解释器的安装命令；uv 创建的 venv 没有 pip 模块，回退 uv CLI。"""
    if util.find_spec("pip") is not None:
        return [sys.executable, "-m", "pip", "install", "--upgrade",
                PACKAGE_NAME, "--disable-pip-version-check", "--quiet"]
    uv = shutil.which("uv")
    if uv:
        return [uv, "pip", "install", "--python", sys.executable, PACKAGE_NAME, "--quiet"]
    return None


def update_holiday_data() -> dict:
    """升级 chinese-calendar 并热加载，返回更新后状态与结果消息。同步阻塞，调用方应放线程池。"""
    if not _update_lock.acquire(blocking=False):
        return {**get_holiday_data_status(), "updated": False, "message": "已有更新任务正在进行，请稍候"}

    before = get_holiday_data_status()
    try:
        cmd = _install_command()
        if cmd is None:
            return {**before, "updated": False,
                    "message": "当前环境缺少 pip 与 uv，无法在线升级，请手动安装: pip install -U " + PACKAGE_NAME}
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=UPDATE_TIMEOUT_SEC)
        except subprocess.TimeoutExpired:
            return {**before, "updated": False,
                    "message": f"升级超时（{UPDATE_TIMEOUT_SEC}s），请手动执行: pip install -U {PACKAGE_NAME}"}
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()[-300:]
            logger.warning(f"[holiday_calendar] 升级失败: {err}")
            return {**before, "updated": False, "message": f"升级失败：{err}"}

        covered = _reload_module()
        status = get_holiday_data_status()
        if covered is not None and covered > (before.get("covered_year") or 0):
            status.update(updated=True, message=f"✅ 已更新至 v{status['version']}，节假日数据覆盖至 {covered} 年")
            logger.info(f"[holiday_calendar] {status['message']}")
        else:
            status.update(updated=False,
                          message=f"已是最新版 v{status['version']}（覆盖至 {before.get('covered_year')} 年），"
                                  f"下一年度放假安排尚未发布或未收录")
        return status
    finally:
        _update_lock.release()
