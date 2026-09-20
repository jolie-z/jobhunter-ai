"""
全链路终止开关 — 优雅终止的协作标记。

终止不是硬杀进程：链路在各安全边界（条件轮之间、阶段之间、岗位之间、
爬虫事件转发等待中）检查 is_aborted()，命中则收尾：
已结束的部分照常统计，任务报告标注「手动终止」。
"""
import threading

_lock = threading.Lock()
_state = {"aborted": False, "pipeline_task_id": ""}
# 平台级终止登记：flag 只负责当轮急刹，这里负责拦截后续轮次
# （各 controller 入口会 set_stop_flag(False) 重置 flag，登记不会被重置）
_platform_aborted: set = set()

KNOWN_PLATFORMS = ("boss", "51job", "zhilian", "liepin", "xiaohongshu")


def begin_pipeline(pipeline_task_id: str) -> None:
    """链路启动时调用：清掉上一轮的全局与平台级终止标记并登记当前任务。"""
    with _lock:
        _state["aborted"] = False
        _state["pipeline_task_id"] = pipeline_task_id
        _platform_aborted.clear()


def request_abort(pipeline_task_id: str = "") -> bool:
    """请求终止。传入 task_id 时仅当与当前运行任务一致才生效。返回是否生效。"""
    with _lock:
        if pipeline_task_id and _state["pipeline_task_id"] and \
                pipeline_task_id != _state["pipeline_task_id"]:
            return False
        _state["aborted"] = True
        return True


def is_aborted() -> bool:
    with _lock:
        return _state["aborted"]


def request_platform_abort(platform: str) -> bool:
    """登记平台级终止（拦截编排层后续轮次）。未知平台忽略并返回 False。"""
    with _lock:
        if platform not in KNOWN_PLATFORMS:
            return False
        _platform_aborted.add(platform)
        return True


def is_platform_aborted(platform: str) -> bool:
    with _lock:
        return platform in _platform_aborted


def get_aborted_platforms() -> list:
    with _lock:
        return sorted(_platform_aborted)


def end_pipeline() -> None:
    """链路收尾时调用：释放登记（终止标记保留给报告读取，由下次 begin 清理）。"""
    with _lock:
        _state["pipeline_task_id"] = ""


# ==========================================
# 单岗级自动投递终止标记管理
# ==========================================
_cancelled_job_deliveries: set[str] = set()


def cancel_job_delivery(record_id: str) -> None:
    """登记单岗位投递取消请求。"""
    if not record_id:
        return
    with _lock:
        _cancelled_job_deliveries.add(str(record_id))


def is_job_delivery_cancelled(record_id: str) -> bool:
    """查询指定岗位是否已被请求取消投递。"""
    if not record_id:
        return False
    with _lock:
        return str(record_id) in _cancelled_job_deliveries


def clear_job_delivery_cancelled(record_id: str) -> None:
    """清理单岗位的取消标记（收尾退出或重试时调用）。"""
    if not record_id:
        return
    with _lock:
        _cancelled_job_deliveries.discard(str(record_id))
