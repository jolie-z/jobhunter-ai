"""51job 附件简历日上传配额跟踪（投递引擎 / 手动批量 / 定时波次三方共用）。

背景：51job 对附件简历上传按日限次（业务错误码 720721「今日上传次数达上限」），
且不提供余量查询接口——撞墙是唯一信号。本模块把「今日是否已撞墙 / 今日已成功
上传几次 / 海投「我的简历」是否当日新鲜」持久化到 backend/data/51job_upload_quota.json，
跨进程重启存活：
- 引擎在「确需上传」决策点据此止损（附件可直接复用的岗位不受影响）；
- 编排层据此对 51job 精投岗预检，配额耗尽当日不再唤起引擎；
- uploads_used 顺带帮用户摸清 51job 的实际日限额。

日期以本机本地日期为准；任何读操作发现 date 不是今天即视为新的一天（状态归零），
所以调用方永远不需要自己处理跨天。
"""
import json
import logging
import os
import threading
from datetime import date

logger = logging.getLogger("upload_quota")

QUOTA_STATE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "51job_upload_quota.json",
)

# 引擎 / 编排层写入飞书「自动投递失败日志」与失败台账的统一文案。
# 「[风控]」前缀命中 failure_triage.PERSISTENT_PATTERNS（当日波次不再重试），
# 「今日上传次数已达上限」命中 failure_triage.DAILY_UPLOAD_QUOTA_MARKER（跨天自动恢复）。
QUOTA_EXHAUSTED_ERROR = "[风控] 51job附件简历今日上传次数已达上限(720721)，留待次日自动重试或手动投递"

_lock = threading.Lock()


def _today() -> str:
    return date.today().isoformat()


def _empty_state() -> dict:
    return {"date": _today(), "uploads_used": 0, "exhausted": False, "mass_resume_date": ""}


def _read_state() -> dict:
    """读状态；文件缺失/损坏/非今日一律视为今日全新状态。"""
    try:
        with open(QUOTA_STATE_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return _empty_state()
    if not isinstance(data, dict) or data.get("date") != _today():
        return _empty_state()
    return {**_empty_state(), **data}


def _write_state(state: dict) -> None:
    """临时文件 + os.replace 原子替换，避免并发写出半截 JSON；写失败只告警不阻塞投递。"""
    tmp_path = f"{QUOTA_STATE_FILE}.{os.getpid()}.tmp"
    try:
        os.makedirs(os.path.dirname(QUOTA_STATE_FILE), exist_ok=True)
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)
        os.replace(tmp_path, QUOTA_STATE_FILE)
    except OSError as e:
        logger.warning(f"⚠️ [51job配额] 状态文件写入失败（不影响投递流程）: {e}")
        try:
            os.remove(tmp_path)
        except OSError:
            pass


def get_state() -> dict:
    with _lock:
        return _read_state()


def is_exhausted_today() -> bool:
    """今日是否已收到 720721（撞墙后当日所有新上传必然失败）。"""
    return bool(get_state().get("exhausted"))


def is_mass_resume_fresh_today() -> bool:
    """海投「我的简历」是否由本引擎在今日上传过（是则当日海投零配额复用）。"""
    return get_state().get("mass_resume_date") == _today()


def mark_upload_success() -> None:
    with _lock:
        state = _read_state()
        state["uploads_used"] = int(state.get("uploads_used") or 0) + 1
        _write_state(state)


def mark_quota_exhausted() -> None:
    with _lock:
        state = _read_state()
        state["exhausted"] = True
        _write_state(state)


def mark_mass_resume_uploaded_today() -> None:
    with _lock:
        state = _read_state()
        state["mass_resume_date"] = _today()
        _write_state(state)
