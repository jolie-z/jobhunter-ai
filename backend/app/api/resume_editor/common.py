"""
多平台在线简历编辑器 - 共享常量与辅助函数
"""

import json
import os
import threading

# 路径常量
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
DATA_DIR = os.path.join(_BACKEND_DIR, "resume_editor", "data")
PLATFORMS_DIR = os.path.join(_BACKEND_DIR, "resume_editor", "platforms")
SCRIPTS_DIR = PLATFORMS_DIR
UNIFIED_PATH = os.path.join(DATA_DIR, "unified_resume.json")

PLATFORMS = ["boss", "liepin", "51job", "zhilian"]


def atomic_write_json(path: str, data) -> None:
    """原子写 JSON：进程唯一临时文件 + os.replace，写一半被杀不会留下损坏文件（与采集落盘同一规范）。
    tmp 名带 pid：多进程并发写同一文件时不会互踩临时文件。"""
    tmp_path = f"{path}.tmp.{os.getpid()}"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


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
# 日志目录在 resume_editor/data/ 下（整个 data/ 已被 gitignore，不会进仓库）。
# ============================================================

def persist_writeback_log(platform: str, stdout: str = "", stderr: str = "",
                          returncode=None, data=None, dry_run: bool = False,
                          log_dir: str = None) -> str:
    """把一次平台回写的完整输出存成日志文件，返回文件路径。调用方自行吞异常。"""
    import datetime as _dt

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


def load_llm_config() -> dict:
    """从 backend/.env 读取 LLM 配置"""
    candidates = [
        os.path.join(_BACKEND_DIR, ".env"),
        os.path.join(_BACKEND_DIR, "..", "backend", ".env"),
    ]
    config = {}
    for env_path in candidates:
        env_path = os.path.normpath(env_path)
        if os.path.exists(env_path):
            with open(env_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        v = v.strip().strip('"').strip("'")
                        config[k.strip()] = v
            break
    # OpenAI SDK 会自动拼 /chat/completions：配置写成完整请求路径时归一化回基址
    bu = config.get("OPENAI_BASE_URL", "")
    if bu.endswith("/chat/completions"):
        config["OPENAI_BASE_URL"] = bu[:-len("/chat/completions")]
    return config
