"""
全链路终止开关 — 优雅终止的协作标记。

终止不是硬杀进程：链路在各安全边界（条件轮之间、阶段之间、岗位之间、
爬虫事件转发等待中）检查 is_aborted()，命中则收尾：
已结束的部分照常统计，任务报告标注「手动终止」。
"""
import threading

_lock = threading.Lock()
_state = {"aborted": False, "pipeline_task_id": "", "aborted_at": 0.0}
# 平台级终止登记：flag 只负责当轮急刹，这里负责拦截后续轮次
# （各 controller 入口会 set_stop_flag(False) 重置 flag，登记不会被重置）
_platform_aborted: set = set()

KNOWN_PLATFORMS = ("boss", "51job", "zhilian", "liepin", "xiaohongshu")


class PipelineAbortedError(RuntimeError):
    """终止检查点异常（2026-11-05 僵尸链路事故）。

    preflight/编排片段间的终止检查点命中后抛出，与「窗口耗尽按跳过处理」的温和
    语义不同：整轮已被用户终止，片段结果无意义，必须快速向上传播让编排器按
    「手动终止」语义收口（_execute_pipeline 单列 except，不发失败告警）。
    放在 abort 模块：异常与旗子同源（架构归属），编排器/预检统一从此导入。
    """
    pass


def begin_pipeline(pipeline_task_id: str) -> None:
    """链路启动时调用：清掉上一轮的全局与平台级终止标记并登记当前任务。"""
    with _lock:
        _state["aborted"] = False
        _state["pipeline_task_id"] = pipeline_task_id
        _state["aborted_at"] = 0.0
        _platform_aborted.clear()


def request_abort(pipeline_task_id: str = "") -> bool:
    """请求终止。传入 task_id 时仅当与当前运行任务一致才生效。返回是否生效。"""
    import time

    with _lock:
        if pipeline_task_id and _state["pipeline_task_id"] and \
                pipeline_task_id != _state["pipeline_task_id"]:
            return False
        if not _state["aborted"]:
            _state["aborted"] = True
            _state["aborted_at"] = time.monotonic()
        return True


def aborted_at() -> float:
    """终止旗子置位时刻（monotonic 秒；未终止返回 0.0）。

    供编排器终止看门狗计时：优雅终止预期秒级~分钟级收口，超时未收口即视为
    协程挂死，触发强制收尾（2026-11-05 僵尸链路事故：preflight CDP 探测无超时
    挂死 → 终止旗子无人检查 → automation_logs 永久 running、占坑不释放）。
    """
    with _lock:
        return _state["aborted_at"]


def is_aborted() -> bool:
    with _lock:
        return _state["aborted"]


def current_pipeline_task_id() -> str:
    """当前登记运行中的链路 task_id（无登记为空串）。供终止接口做降级判定与日志取证。"""
    with _lock:
        return _state["pipeline_task_id"]


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
    """链路收尾时调用：释放登记并清掉终止标记。

    2026-10-24 工单：旧版只清 task_id、保留 aborted，导致「上一轮被终止」的标记残留到
    之后的单岗评估/审批放行投递与定时发射波次——这些流程不走 begin_pipeline，会被误判
    为仍在终止中而全部拦截。终止战报在 end_pipeline 之前生成，此处清理不影响报告标注。
    """
    with _lock:
        _state["pipeline_task_id"] = ""
        _state["aborted"] = False
        _state["aborted_at"] = 0.0
        # code-review R2-P2：平台终止登记与单岗取消标记同为「一次性」语义，链路收尾一并清——
        # 「先单岗取消、后全局终止」时投递节点的全局分支会提前 return 跳过 clear，若不在此
        # 兜底，陈旧单岗标记会残留到下一轮，造成同岗位首次投递被误拦一次。
        _platform_aborted.clear()
        # 单岗取消标记维持链路收尾全局清空（2026-11-02 审计 P2-25 评估后保守保留）：
        # 更精细的按任务归属清理涉及投递主链语义，列第四批。已知取舍：若用户恰在
        # 链路收尾瞬间对批量投递 worker 中的岗位下终止，该标记会被本次清空抹掉
        # （窗口极小）；残留风险由消费侧每岗 clear 兜底。
        _cancelled_job_deliveries.clear()


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
