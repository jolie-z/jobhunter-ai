"""
任务级 LLM 阻塞状态登记表
==========================
背景（2026-10-31 上游聚合网关 账号池全灭事故）：LLM 网关 503 时 AI 侦察兵 fail-preserve
把岗位留在「待AI初筛」，链路照常收尾，前端徽标却显示「任务完成」，用户全程不知道
哪里坏了、怎么修、修好后如何继续。

本模块维护 per-task 的阻塞登记：
- AI 侦察兵 PRESERVE 路径把异常按 classify_llm_error 分类后 report 上来；
- 连续失败置位，任一次真实 LLM 成功即清除（恢复运行无需人工介入）；
- 状态进程内持久：不随 SSE 断连/页面刷新丢失，dashboard-sync 经
  pipeline_broadcast.get_stage_snapshot 每 12 秒带给前端；
- 编排器收尾据此给 emit_end 打 outcome="blocked"，不伪装成完全成功。

本模块是纯内存叶子（仅 stdlib），可被 pipeline_broadcast / 编排器 / job_processor
安全引用，不反向依赖任何业务模块。
"""
import logging
import threading
from datetime import datetime

logger = logging.getLogger(__name__)

_lock = threading.Lock()
# task_id -> blocked dict；新链路启动时整体清空（见 reset_all）
_blocked: dict[str, dict] = {}
# 登记表上界：与 pipeline_broadcast._live_phases 同策略，防长期运行无界增长
_MAX_TRACKED = 8


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def report_llm_failure(
    task_id: str | None,
    kind: str,
    model: str | None = None,
    message: str = "",
    gateway_hint: str = "",
    retry_after: float | None = None,
) -> dict | None:
    """登记一次 LLM 调用失败并置位阻塞。返回置位后的状态（task_id 为空返回 None）。

    failed_count 为该任务累计失败次数；重复失败时刷新 kind/model/message 为最近一次
    （前端横幅展示「最近一次」的根因比首次更贴近当下）。
    """
    if not task_id:
        return None
    with _lock:
        prev = _blocked.get(task_id)
        entry = {
            "blocked": True,
            "task_id": task_id,
            "kind": str(kind or "unknown"),
            "model": model or (prev or {}).get("model"),
            "message": message or (prev or {}).get("message") or "LLM 调用失败",
            "gateway_hint": gateway_hint or (prev or {}).get("gateway_hint") or "",
            "retry_after": retry_after,
            "failed_count": int((prev or {}).get("failed_count") or 0) + 1,
            "first_seen": (prev or {}).get("first_seen") or _now(),
            "min_rowid": (prev or {}).get("min_rowid"),
        }
        _blocked[task_id] = entry
        while len(_blocked) > _MAX_TRACKED:
            _blocked.pop(next(iter(_blocked)))
        return dict(entry)


def report_llm_success(task_id: str | None) -> None:
    """任一次真实 LLM 成功即清除阻塞：恢复是运行态事实，无需等人工确认。"""
    if not task_id:
        return
    with _lock:
        _blocked.pop(task_id, None)


def clear_task(task_id: str | None) -> None:
    """显式清除某任务的阻塞登记（前端「终止任务」的放弃出口）。

    与 report_llm_success 的区别是语义：这不是「LLM 恢复了」的运行态事实，
    而是用户显式放弃这条链路——不清的话刷新页面后横幅会凭空复现。"""
    if not task_id:
        return
    with _lock:
        _blocked.pop(task_id, None)


def get_blocked_state(task_id: str | None) -> dict | None:
    if not task_id:
        return None
    with _lock:
        state = _blocked.get(task_id)
        return dict(state) if state else None


def attach_scope(task_id: str | None, min_rowid: int | None = None) -> None:
    """把本轮清洗范围（start_rowid）附着到阻塞态：供「继续任务」只重洗本轮遗留行。"""
    if not task_id or min_rowid is None:
        return
    with _lock:
        state = _blocked.get(task_id)
        if state is not None:
            state["min_rowid"] = int(min_rowid)


def reset_all() -> None:
    """新链路启动时清空上一轮登记（与 pipeline_broadcast.create_pipeline_queue 同时机）。"""
    with _lock:
        _blocked.clear()


def apply_outcome(summary: dict, task_id: str | None, preserved_count: int) -> dict:
    """收尾判定：本轮存在 LLM 阻塞且仍有「待AI初筛」遗留时，end 摘要打 outcome=blocked。

    preserved_count <= 0 说明阻塞期间的 PRESERVE 行最终都被消化了（或本轮本就无遗留），
    不打阻塞标记，避免把已自愈的轮次误报成暂停。
    """
    state = get_blocked_state(task_id)
    if not state or int(preserved_count or 0) <= 0:
        return summary
    merged = dict(summary or {})
    merged["outcome"] = "blocked"
    merged["blocked"] = state
    return merged
