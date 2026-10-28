"""
多平台在线简历编辑器 - 共享常量与辅助函数
"""

import json
import os
import threading

# 路径常量：数据目录只认 resume_editor.paths 真源（读/写锚点拆分 2026-10-26，
# 用户数据打包态落用户数据目录，字典随包只读）；本模块不再自算 data 路径
from resume_editor.paths import DATA_DIR, DICT_DIR, UNIFIED_PATH  # noqa: F401

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
PLATFORMS_DIR = os.path.join(_BACKEND_DIR, "resume_editor", "platforms")
SCRIPTS_DIR = PLATFORMS_DIR

PLATFORMS = ["boss", "liepin", "51job", "zhilian"]


def atomic_write_json(path: str, data) -> None:
    """原子写 JSON：进程唯一临时文件 + os.replace，写一半被杀不会留下损坏文件（与采集落盘同一规范）。
    tmp 名带 pid：多进程并发写同一文件时不会互踩临时文件。
    目标目录按需创建：打包态全新安装时用户数据目录尚不存在。"""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp_path = f"{path}.tmp.{os.getpid()}"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def merge_platform_fields(existing: dict | None, incoming: dict) -> dict:
    """平台字段文件的模块级增量合并（2026-10-23 保存接口改造）。

    - incoming 的顶层键整体替换同名模块（不做列表深合并——工作经历等有序数组
      按下标/ID 合并必然错位，模块级替换与前端 Tab 的数据形状一致）；
    - 值为 None 表示删除该模块（合并语义无法靠「省略」表达删除；整表清空走 /clear-data）；
    - 未提及的模块原样保留——根治「局部数据当全量发」把未带模块整份销毁的事故
      （test_03 曾把 17 模块的 boss_fields.json 覆盖成 1 模块）；
    - existing=None 表示「文件不存在」的首存场景；existing/incoming 非 dict 抛 ValueError
      （调用方对 existing 映射为 fail-closed 500、对 incoming 映射为 400）。
    返回新 dict，不修改入参。
    """
    if incoming is None or not isinstance(incoming, dict):
        raise ValueError("增量载荷必须是模块字典")
    if existing is None:
        base: dict = {}
    elif isinstance(existing, dict):
        base = dict(existing)
    else:
        raise ValueError("现有数据不是模块字典（疑似损坏）")

    merged = base
    for key, value in incoming.items():
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = value
    return merged


# ============================================================
# 回写并发防护（用户质检 2026-08-30）：同平台回写互斥，
# 防止批量回写与 Tab 内回写同时操作同一 Edge 的 CDP 会话
# ============================================================

_writeback_locks: dict = {}
_writeback_locks_guard = threading.Lock()


def claim_writeback_slot(platform: str) -> bool:
    """尝试占用平台回写槽位；已被占用返回 False（调用方应拒绝执行）。"""
    with _writeback_locks_guard:
        lock = _writeback_locks.setdefault(platform, threading.Lock())
    return lock.acquire(blocking=False)


def release_writeback_slot(platform: str) -> None:
    lock = _writeback_locks.get(platform)
    if lock is not None and lock.locked():
        lock.release()


# ============================================================
# 回写日志落盘（用户案例 2026-08-31）：个别字段「接口回执成功、官网实际没生效」，
# 只有拿到官网逐操作的原话返回才能定位。每次回写把脚本完整 stdout/stderr、
# 复核明细与写入结果明细存成日志文件，路径随响应的 log_file 字段返回。
# 日志目录在用户数据目录 resume_editor/writeback_logs/ 下（打包态随 JOBHUNTER_DATA_DIR，不进仓库不进包）。
# ============================================================

def persist_writeback_log(platform: str, stdout: str = "", stderr: str = "",
                          returncode=None, data=None, dry_run: bool = False,
                          log_dir: str = None) -> str:
    """把一次平台回写的完整输出存成日志文件，返回文件路径。调用方自行吞异常。"""
    import datetime as _dt

    # 运行时从 DATA_DIR 派生（而非绑定导入期常量）：测试按模块 patch common.DATA_DIR 即可整体隔离
    target_dir = log_dir or os.path.join(DATA_DIR, "writeback_logs")
    os.makedirs(target_dir, exist_ok=True)
    now = _dt.datetime.now()
    path = os.path.join(target_dir, f"writeback_{now.strftime('%Y%m%d_%H%M%S')}_{platform}.log")
    data = data if isinstance(data, dict) else {}

    lines = [
        f"回写日志：{platform} | {now.strftime('%Y-%m-%d %H:%M:%S')} | dry_run={dry_run} | 退出码={returncode}",
        f"success={data.get('success')} | message={data.get('message') or ''}",
    ]
    if data.get("data_source"):
        lines.append(f"数据源: {json.dumps(data['data_source'], ensure_ascii=False)}")
    lines.append("=" * 24 + " 脚本完整输出 " + "=" * 24)
    lines.append((stdout or "").rstrip() or "(无输出)")
    if (stderr or "").strip():
        lines.append("=" * 24 + " stderr " + "=" * 24)
        lines.append(stderr.strip())
    verify = data.get("verify") or []
    if verify:
        lines.append("=" * 24 + " 复核明细 " + "=" * 24)
        for v in verify:
            tag = "✓" if v.get("match") else "✗"
            lines.append(f"  [{tag}] {v.get('module')}: {v.get('note')}")
    details = data.get("results") or data.get("modules") or []
    if details:
        lines.append("=" * 24 + " 写入结果明细 " + "=" * 24)
        for d in details:
            if isinstance(d, dict):
                tag = "OK" if d.get("ok") else "FAIL"
                extra = d.get("resp_message") or d.get("resp_status") or ""
                lines.append(f"  [{tag}] {d.get('module')}: {d.get('detail') or ''} {extra}".rstrip())
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return path


def precheck_writeback_login(platform: str):
    """回写前 DOM 级登录预检（用户质检 C4 2026-08-30）。

    回写是覆盖官网的破坏性动作，值得比采集更强的前置校验：
    - EXPIRED（确证失效）→ 拦截，返回 (False, 提示)
    - HEALTHY / UNKNOWN（检查失败，存疑）→ 放行，脚本层还有登录二次校验兜底
    返回 (ok, message)。
    """
    from app.session.health_checker import check_login_via_dom
    from app.session.registry import PLATFORM_CONFIGS
    config = PLATFORM_CONFIGS.get(platform)
    if config is None:
        return True, "无平台配置，跳过预检"
    status = check_login_via_dom(config)
    if status.state.value == "expired":
        return False, f"{config.display_name}登录态已失效（DOM 校验未命中登录标识），请先在浏览器重新登录再回写"
    return True, status.message or "登录态正常"

# 工作经历平台专属字段的选项列表映射
WORK_FIELD_OPTIONS_MAP = {
    "zhilian": {
        "job_titles": "zhilian_work_jobtitles.json",
        "skills": "zhilian_work_skills_progress.json",
        "industries": "zhilian_industries.json",
    },
    "boss": {
        "job_titles": "boss_job_categories_full.json",
        "industries": "boss_industry_options.json",
    },
    "liepin": {
        "job_titles": "liepin_job_categories.json",
        "industries": "liepin_industry_categories.json",
    },
    "51job": {
        "job_titles": "51job_dd_funtype.json",
        "industries": "51job_industry.json",
    },
}
