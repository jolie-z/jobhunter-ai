"""
全链路 SSE 广播器
==================

全自动链路（抓取 → 清洗 → 飞书推送 → AI评估 → 改写 → 欢迎语 → 投递）的实时事件推送工具。

设计原则：
- 不新造队列机制，完全复用 app/tasks/state.task_queues（Dict[task_id, asyncio.Queue]）。
- 推送格式与现有爬虫/清洗模块保持一致：`data: {json}\n\n`，前端用同一套 EventSource 解析。
- 本模块只负责"往队列里塞事件"，不关心谁在消费（前端 /api/automation/stream 订阅）。

事件协议（type 字段）：
- stage    : 阶段切换      {"type":"stage","stage":"scraping","status":"running","label":"平台抓取"}
- progress : 阶段内进度    {"type":"progress","stage":"scraping","platform":"boss","current":3,"total":10}
- job      : 单岗位流转    {"type":"job","job_id":"...","job_name":"...","node":"evaluate","status":"running"}
- log      : 文本日志      {"type":"log","message":"..."}
- end      : 全链路结束    {"type":"end"}
"""
import asyncio
import json

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


def create_pipeline_queue(pipeline_task_id: str) -> asyncio.Queue:
    """为一条全链路创建主队列并注册到全局 task_queues。"""
    from app.tasks.state import TaskChannel, task_queues
    channel = TaskChannel()
    task_queues[pipeline_task_id] = channel
    return channel


# ── 当前链路追踪：供前端自动发现正在运行的全链路（定时/手动触发都经过这里）──
_current_pipeline = {"task_id": None, "running": False}

def set_current_pipeline(task_id: str | None, running: bool):
    _current_pipeline["task_id"] = task_id
    _current_pipeline["running"] = bool(running)

def get_current_pipeline() -> dict:
    return dict(_current_pipeline)


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


async def emit_stage(pipeline_task_id: str | None, stage: str, status: str = "running"):
    """广播阶段切换。label 自动从 PIPELINE_STAGES 查表。"""
    label = dict(PIPELINE_STAGES).get(stage, stage)
    await _put(pipeline_task_id, {"type": "stage", "stage": stage, "status": status, "label": label})


async def emit_progress(pipeline_task_id: str | None, stage: str, current: int, total: int,
                        platform: str | None = None, extra: dict | None = None):
    """广播阶段内进度（如某平台抓到第几个、清洗到第几条）。"""
    data = {"type": "progress", "stage": stage, "current": current, "total": total}
    if platform:
        data["platform"] = platform
    if extra:
        data.update(extra)
    await _put(pipeline_task_id, data)


async def emit_job(pipeline_task_id: str | None, job_id: str, job_name: str, node: str,
                   status: str = "running", grade: str | None = None, platform: str | None = None,
                   company_name: str | None = None, salary: str | None = None,
                   city: str | None = None, job_url: str | None = None, **kwargs):
    """广播单个岗位在链路中的流转状态。"""
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
