"""
全链路 SSE 广播器
==================

全自动链路（抓取 → 清洗 → 飞书推送 → AI评估 → 改写 → 欢迎语 → 投递）的实时事件推送工具。

设计原则：
- 不新造队列机制，完全复用 app/tasks/state.task_queues（Dict[task_id, asyncio.Queue]）。
- 推送格式与现有爬虫/清洗模块保持一致：`data: {json}\n\n`，前端用同一套 EventSource 解析。
- 本模块只负责"往队列里塞事件"，不关心谁在消费（前端 /api/automation/stream 订阅）。
- 同时维护一份进程内「实时岗位/阶段登记表」：SSE 是直播，jobs-snapshot 是 12 秒轮询，
  两者粒度不同。快照服务必须用这里的实时态覆盖 Feishu 字段派生出来的近似态，否则
  改写中的岗位会被 12 秒轮询打回「AI初评完成 / 待审批」，卡片动画与导轨计数就会失真。

事件协议（type 字段）：
- stage    : 阶段切换      {"type":"stage","stage":"scraping","status":"running","label":"平台抓取"}
- progress : 阶段内进度    {"type":"progress","stage":"scraping","platform":"boss","current":3,"total":10}
- job      : 单岗位流转    {"type":"job","job_id":"...","job_name":"...","node":"evaluate","status":"running"}
- log      : 文本日志      {"type":"log","message":"..."}
- end      : 全链路结束    {"type":"end"}
"""
import asyncio
import json
import logging
import threading
import time

logger = logging.getLogger(__name__)

# 全链路阶段定义（顺序即渲染顺序）
PIPELINE_STAGES = [
    ("scraping", "平台抓取"),
    ("cleaning", "规则清洗"),
    ("feishu_sync", "飞书推送"),
    ("evaluating", "AI初评"),
    ("deep_eval", "深度评估"),
    ("rewriting", "简历改写"),
    ("greeting", "欢迎语"),
    ("review", "待审批"),
    ("delivering", "自动投递"),
    ("done", "完成"),
]

# LangGraph 节点 → 全链路阶段（与 graph_runner.emit_job 的 node 取值保持一致）。
# 深度评估虽然内联在 evaluate_node 里，但 evaluate_node 会通过 progress_callback
# 广播 node=deep_eval_node 的子阶段事件，因此这里必须保留该映射。
NODE_STAGE_MAP = {
    # 清洗/飞书推送段：step1/step2 逐岗位广播的节点（流式卡片）
    "clean_rule_node": "cleaning",
    "clean_ai_node": "cleaning",
    "feishu_sync": "feishu_sync",
    "evaluate_node": "evaluating",
    "deep_eval_node": "deep_eval",
    "rewrite_node": "rewriting",
    "greeting_node": "greeting",
    "quick_greeting_node": "greeting",
    "manual_review_node": "review",
    "delivery_node": "delivering",
}

# 运行态文案的唯一事实源：job 事件与 jobs-snapshot 都从这里取，
# 前端 job-card 只在字段缺失时兜底，避免前后端各维护一份中文映射。
# ⚠️ 前端镜像：frontend/store/pipeline-store.ts 的 NODE_ACTION_DESC（仅快照缺字段时兜底）。
# 增删节点或改措辞时必须同步两侧；前端表驱动测试锁定运行态节点取值
# （pipeline-store.test.ts 用例 12）。manual_review_node 后端只以 waiting 终态下发，
# 不走运行态兜底，因此不在该测试表内。
NODE_ACTION_DESC = {
    "clean_rule_node": "硬规则清洗中",
    "clean_ai_node": "AI排雷评估中",
    "feishu_sync": "正在推送飞书多维表格",
    "evaluate_node": "AI初评进行中",
    "deep_eval_node": "深度画像评估中",
    "rewrite_node": "定制简历改写中",
    "greeting_node": "生成打招呼语中",
    "quick_greeting_node": "生成打招呼语中",
    "manual_review_node": "待老板审批",
    "delivery_node": "正在自动投递中",
}

# 子状态文案：优先级高于节点文案（同一节点下的排队/通过/保留等细分态）
SUB_STATUS_ACTION_DESC = {
    "ai_eval_queued": "AI初评排队中",
    "clean_rule_passed": "硬规则通过，排队AI排雷",
    "clean_ai_passed": "AI排雷通过，等待推送飞书",
    "clean_ai_preserved": "AI排雷未完成，保留待重试",
    "feishu_synced": "已推送飞书，等待评估",
    "feishu_synced_existing": "已存在于飞书，跳过重复推送",
    "feishu_sync_failed": "飞书推送失败，等待下轮重试",
}


def node_action_desc(node: str | None, sub_status: str | None = None) -> str:
    if sub_status in SUB_STATUS_ACTION_DESC:
        return SUB_STATUS_ACTION_DESC[sub_status]
    return NODE_ACTION_DESC.get(str(node or ""), "流水线运行中")

# ── 进程内实时登记表 ────────────────────────────────────────────────────────
# task_id -> job_id -> 最近一次 job 事件状态（含 updated_at / deep_eval_done）
_live_jobs: dict[str, dict[str, dict]] = {}
# task_id -> stage -> 最近一次 stage 事件状态
_live_stages: dict[str, dict[str, str]] = {}
# task_id -> phase -> {current,total}（硬清洗 / AI 初筛 / 飞书同步进度）
_live_phases: dict[str, dict[str, dict]] = {}

# step2 的 phase_progress 由 worker thread 写入，dashboard-sync 在事件循环线程读取；
# 所有登记表读写统一加可重入锁，避免迭代期间 dict 变长触发 RuntimeError。
_live_lock = threading.RLock()


def create_pipeline_queue(pipeline_task_id: str) -> asyncio.Queue:
    """为一条全链路创建主队列并注册到全局 task_queues。

    新链路开始即清空上一轮实时登记表：全链路有进程级互斥锁，同一时刻只有一条主线，
    旧任务的实时态没有继续保留的必要（历史展示由 jobs-snapshot 从 Feishu/SQLite 重建）。
    """
    from app.tasks.state import TaskChannel, task_queues
    with _live_lock:
        _live_jobs.clear()
        _live_stages.clear()
        _live_phases.clear()
    from app.automation import pipeline_blocked
    pipeline_blocked.reset_all()
    channel = TaskChannel()
    task_queues[pipeline_task_id] = channel
    return channel


def discard_pipeline_queue(pipeline_task_id: str) -> None:
    """移除尚未使用的任务队列（占坑回滚专用，2026-11-02 审计 CR-R1-P1）。

    正常运行收尾的队列清理属批次三（schedule_task_cleanup 接线）；本函数只服务
    「占坑后预检失败」的回滚路径——链路从未发射，队列无订阅者、无历史，直接丢弃。
    存储位置：app.tasks.state.task_queues（与 create_pipeline_queue 对称）。
    """
    from app.tasks.state import task_queues
    task_queues.pop(pipeline_task_id, None)


# ── 当前链路追踪：供前端自动发现正在运行的全链路（定时/手动触发都经过这里）──
_current_pipeline = {"task_id": None, "running": False}

def set_current_pipeline(task_id: str | None, running: bool):
    _current_pipeline["task_id"] = task_id
    _current_pipeline["running"] = bool(running)

def get_current_pipeline() -> dict:
    return dict(_current_pipeline)


def _record_stage(task_id: str | None, stage: str, status: str) -> None:
    if not task_id or not stage:
        return
    with _live_lock:
        _live_stages.setdefault(task_id, {})[stage] = status


def _record_job(task_id: str | None, data: dict) -> None:
    """把一条 job 事件并入实时登记表（同岗位后到的事件覆盖先到的）。"""
    if not task_id:
        return
    jid = str(data.get("job_id") or "").strip()
    if not jid:
        return

    with _live_lock:
        prev = _live_jobs.get(task_id, {}).get(jid, {})
        entry = dict(prev)
        # 描述性字段：空串/None 不覆盖已知值（与前端 handleEvent 的 falsey 合并口径一致）
        for key in (
            "job_name", "platform", "company_name", "company_scale", "salary", "city",
            "education", "experience", "job_url", "jd_text", "grade", "review_type",
            "raw_job_id", "greeting_msg",
        ):
            val = data.get(key)
            if val not in (None, ""):
                entry[key] = val
        # 状态类字段：允许显式清空/改写（放行后 node 残留等历史事故）
        for key in ("node", "status", "sub_status"):
            if key in data:
                entry[key] = data.get(key)
        if data.get("score") is not None:
            entry["score"] = data["score"]
        # running 事件意味着新一轮尝试开始：清掉旧失败信息，避免卡片残留失败态
        if data.get("status") == "running":
            entry["failure_info"] = None
        elif "failure_info" in data:
            entry["failure_info"] = data.get("failure_info")

        # 深评完成标记必须跨事件保留：深评结束后紧接着会广播 rewrite running，
        # 前端仅凭最后一条事件无法回看「深评已结束」。
        # 但同一岗位重新进入初评（重试）时必须清零，避免上一轮的完成标记污染本轮。
        if (
            data.get("node") == "evaluate_node"
            and data.get("status") == "running"
            and data.get("sub_status") in ("ai_eval", "ai_eval_queued")
        ):
            entry["deep_eval_done"] = False
        else:
            entry["deep_eval_done"] = bool(
                prev.get("deep_eval_done")
                or data.get("deep_eval_done")
                or (data.get("node") == "deep_eval_node" and data.get("status") == "done")
            )
        entry["job_id"] = jid
        entry["updated_at"] = time.time()
        _live_jobs.setdefault(task_id, {})[jid] = entry


def record_phase_progress(task_id: str | None, phase: str, current: int, total: int) -> None:
    """登记清洗/飞书同步的 phase 进度（供刷新页面后恢复进度条）。"""
    if not task_id or not phase:
        return
    with _live_lock:
        _live_phases.setdefault(task_id, {})[phase] = {
            "current": int(current or 0),
            "total": int(total or 0),
            "updated_at": time.time(),
        }
        # step1/step2 也可作为独立任务运行；只保留最近 8 个 task 的 phase 进度，
        # 防止长期运行后登记表无上界增长（全链路主线每次启动仍会整表清空）。
        while len(_live_phases) > 8:
            _live_phases.pop(next(iter(_live_phases)))


def record_phase_progress_event(task_id: str | None, event_data: dict) -> None:
    """从 phase_progress SSE 事件登记进度。

    step1/step2 各自持有一份 push_sse_event（一个 async、一个跨线程），
    把「判断事件类型 + 解析字段」收口到这里，避免两份复制体日后漂移。
    """
    if not task_id or not isinstance(event_data, dict):
        return
    if event_data.get("type") != "phase_progress":
        return
    try:
        record_phase_progress(
            task_id,
            str(event_data.get("phase") or ""),
            int(event_data.get("current") or 0),
            int(event_data.get("total") or 0),
        )
    except Exception as e:
        logger.warning(f"[pipeline_broadcast] phase_progress 登记失败: {e}")


def get_live_jobs(task_id: str | None) -> dict[str, dict]:
    """当前任务每个岗位的最近实时态（浅拷贝，调用方可安全写字段）。"""
    if not task_id:
        return {}
    with _live_lock:
        return {jid: dict(st) for jid, st in (_live_jobs.get(task_id) or {}).items()}


def get_stage_snapshot(task_id: str | None = None) -> dict:
    """供 dashboard-sync 下发：阶段状态 + 清洗进度 + 各阶段实时运行岗位数。

    刷新页面后前端没有 SSE 历史可回放，必须靠这份快照恢复导轨。
    running_counts/active_stages 目前仅作诊断与其他客户端使用；前端并发高亮
    由 jobs-snapshot 的实时岗位态自行聚合，不依赖这两个字段。
    """
    with _live_lock:
        tid = task_id or _current_pipeline.get("task_id")
        stages = dict(_live_stages.get(tid) or {}) if tid else {}
        phases = {
            name: {"current": int(v.get("current") or 0), "total": int(v.get("total") or 0)}
            for name, v in ((_live_phases.get(tid) or {}) if tid else {}).items()
        }

        running_counts: dict[str, int] = {}
        for st in ((_live_jobs.get(tid) or {}) if tid else {}).values():
            if st.get("status") != "running":
                continue
            stage = NODE_STAGE_MAP.get(str(st.get("node") or ""))
            if stage:
                running_counts[stage] = running_counts.get(stage, 0) + 1

    current_stage = None
    for key, _label in PIPELINE_STAGES:
        if stages.get(key) == "running":
            current_stage = key
            break

    active_stages = [
        key for key, _label in PIPELINE_STAGES if running_counts.get(key, 0) > 0
    ]

    # 任务级 LLM 阻塞态：LLM 网关挂掉时 end 的 outcome=blocked 只存在于 SSE 瞬时事件里，
    # 刷新页面就没了。这里随阶段快照每 12 秒下发给 dashboard-sync，阻塞态刷新可见。
    from app.automation import pipeline_blocked
    blocked = pipeline_blocked.get_blocked_state(tid)

    return {
        "task_id": tid,
        "stage_status": stages,
        "phases": phases,
        "running_counts": running_counts,
        "active_stages": active_stages,
        "current_stage": current_stage,
        "blocked": blocked,
    }


async def _put(pipeline_task_id: str | None, event_data: dict):
    """把事件塞进主队列；队列不存在时静默丢弃（不阻塞链路）。"""
    if not pipeline_task_id:
        return
    try:
        from app.tasks.state import task_queues
        queue = task_queues.get(pipeline_task_id)
        if queue is not None:
            msg = f'data: {json.dumps(event_data, ensure_ascii=False)}\n\n'
            await queue.put(msg)
    except Exception:
        pass


async def emit_stage(pipeline_task_id: str | None, stage: str, status: str = "running",
                     extra: dict | None = None):
    """广播阶段切换。label 自动从 PIPELINE_STAGES 查表；extra 附加负载
    （如 status=blocked 时携带 blocked 明细）原样并入事件体。"""
    _record_stage(pipeline_task_id, stage, status)
    label = dict(PIPELINE_STAGES).get(stage, stage)
    data = {"type": "stage", "stage": stage, "status": status, "label": label}
    if extra:
        data.update(extra)
    await _put(pipeline_task_id, data)


async def emit_progress(pipeline_task_id: str | None, stage: str, current: int, total: int,
                        platform: str | None = None, extra: dict | None = None):
    """广播阶段内进度（如某平台抓到第几个、清洗到第几条）。"""
    data = {"type": "progress", "stage": stage, "current": current, "total": total}
    if platform:
        data["platform"] = platform
    if extra:
        data.update(extra)
    await _put(pipeline_task_id, data)


async def emit_phase_progress(pipeline_task_id: str | None, phase: str,
                              current: int, total: int, **extra):
    """广播清洗/飞书同步的 phase_progress，并写入实时登记表（刷新后可恢复进度）。

    与 step1/step2 的 push_sse_event 同构；供编排器/清洗泵下发累计进度使用。
    """
    data = {
        "type": "phase_progress",
        "phase": phase,
        "current": int(current or 0),
        "total": int(total or 0),
    }
    data.update(extra)
    record_phase_progress(pipeline_task_id, phase, int(current or 0), int(total or 0))
    await _put(pipeline_task_id, data)


def build_job_event(job_id: str, job_name: str, node: str,
                    status: str = "running", grade: str | None = None, platform: str | None = None,
                    company_name: str | None = None, salary: str | None = None,
                    city: str | None = None, job_url: str | None = None, **kwargs) -> dict:
    """构造与 emit_job 完全同构的 job 事件体（不做 IO）。

    供工作线程（step2 飞书同步）自行序列化推送使用：事件字段与 SSE/实时登记表
    口径必须完全一致，禁止调用方手拼 dict 造成两套协议。
    """
    data = {"type": "job", "job_id": job_id, "job_name": job_name, "node": node, "status": status}
    if grade:
        data["grade"] = grade
    if platform:
        data["platform"] = platform
    if company_name:
        data["company_name"] = company_name
    if salary:
        data["salary"] = salary
    if city:
        data["city"] = city
    if job_url:
        data["job_url"] = job_url
    if kwargs:
        data.update(kwargs)
    return data


def record_live_job(pipeline_task_id: str | None, data: dict) -> dict:
    """把 job 事件并入实时登记表，并补齐运行态文案 / deep_eval_done。

    返回同一 dict（原地补字段），调用方随后可直接序列化下发。
    """
    _record_job(pipeline_task_id, data)
    if data.get("status") == "running":
        # 运行态文案由服务端统一计算；终态沿用快照/Feishu 的既有文案
        data["last_action_desc"] = node_action_desc(data.get("node"), data.get("sub_status"))
    # 把登记表算出的权威 deep_eval_done 回填到事件：前端无需再复制
    # 「ai_eval 清零 / 跨事件保留」规则，服务端登记表是唯一事实源。
    if pipeline_task_id:
        with _live_lock:
            live_job = _live_jobs.get(pipeline_task_id, {}).get(str(data.get("job_id") or "").strip())
            if live_job is not None:
                data["deep_eval_done"] = bool(live_job.get("deep_eval_done"))
    return data


async def emit_job(pipeline_task_id: str | None, job_id: str, job_name: str, node: str,
                   status: str = "running", grade: str | None = None, platform: str | None = None,
                   company_name: str | None = None, salary: str | None = None,
                   city: str | None = None, job_url: str | None = None, **kwargs):
    """广播单个岗位在链路中的流转状态，并同步写入实时登记表。"""
    data = build_job_event(
        job_id, job_name, node, status=status, grade=grade, platform=platform,
        company_name=company_name, salary=salary, city=city, job_url=job_url, **kwargs,
    )
    record_live_job(pipeline_task_id, data)
    await _put(pipeline_task_id, data)


async def emit_log(pipeline_task_id: str | None, message: str, level: str = "info"):
    """广播一条文本日志。level=error 时 type 置为 warning（与清洗模块约定一致）。"""
    event_type = "warning" if level == "error" else "log"
    await _put(pipeline_task_id, {"type": event_type, "message": message})


async def emit_end(pipeline_task_id: str | None, summary: dict | None = None):
    """广播全链路结束。"""
    data = {"type": "end"}
    if summary:
        data["summary"] = summary
    await _put(pipeline_task_id, data)
