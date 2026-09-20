import asyncio
import os
import sqlite3
import sys
from typing import Annotated, TypedDict

import requests

# ==========================================
# 🌟 修复路径问题
# ==========================================
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

DB_PATH = os.path.join(PROJECT_ROOT, "data", "job_hunter.db")

# ==========================================
# 引入 LangGraph 核心
# ==========================================
from langchain_core.messages import BaseMessage, SystemMessage  # noqa: E402
from langchain_openai import ChatOpenAI  # noqa: E402
from langgraph.checkpoint.memory import MemorySaver  # fallback only  # noqa: E402
from langgraph.graph import START, StateGraph  # noqa: E402
from langgraph.graph.message import add_messages  # noqa: E402
from langgraph.prebuilt import ToolNode, tools_condition  # noqa: E402

# 核心服务
from app.core.config import settings  # noqa: E402
from app.core.feishu_utils import get_tenant_access_token  # noqa: E402

# DB Schema（用于 SYSTEM_PROMPT）
from app.db_nl_controller import DB_SCHEMA  # noqa: E402
from app.services.feishu_service import send_feishu_message  # noqa: E402


# ==========================================
# 📍 状态定义
# ==========================================
class JobHunterState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]


# ==========================================
# 📍 辅助函数：飞书数据同步
# ==========================================
def _feishu_val_to_str(val, default=""):
    if val is None:
        return default
    if isinstance(val, str):
        return val or default
    if isinstance(val, (int, float)):
        ts = int(val)
        if ts > 10000000000:
            try:
                from datetime import datetime, timedelta, timezone
                tz_beijing = timezone(timedelta(hours=8))
                return datetime.fromtimestamp(ts / 1000.0, tz_beijing).strftime("%Y-%m-%dT%H:%M")
            except Exception:
                pass
        return str(val)
    if isinstance(val, list):
        chunks = []
        for item in val:
            if isinstance(item, str):
                chunks.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("name") or item.get("value")
                if text is not None:
                    chunks.append(str(text))
            elif item is not None:
                chunks.append(str(item))
        return "".join([c for c in chunks if c]) or default
    if isinstance(val, dict):
        text = val.get("text") or val.get("name") or val.get("value")
        if text is not None:
            return str(text)
        return str(val) or default
    return str(val) or default

def sync_feishu_to_memory_sqlite(sql_where_clause: str = "", limit: int = 10) -> dict:
    token = get_tenant_access_token()
    # 🌟 使用 settings 获取环境配置
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{settings.FEISHU_APP_TOKEN}/tables/{settings.FEISHU_TABLE_ID_JOBS}/records"
    headers = {"Authorization": f"Bearer {token}"}

    all_records = []
    page_token = None
    while True:
        params = {"page_size": 500}
        if page_token:
            params["page_token"] = page_token
        resp = requests.get(url, headers=headers, params=params, timeout=15, proxies={"http": None, "https": None}).json()  # type: ignore[dict-item]  # requests stub 过严：None 值运行时合法
        if resp.get("code") == 0:
            all_records.extend(resp["data"].get("items", []))
            if not resp["data"].get("has_more"):
                break
            page_token = resp["data"].get("page_token")
        else:
            raise RuntimeError(f"飞书 API 返回错误: code={resp.get('code')}, msg={resp.get('msg')}")

    if not all_records:
        return {"total": 0, "items": [], "columns": [], "raw_count": 0}

    all_field_keys: set = set()
    for r in all_records:
        all_field_keys.update(r.get("fields", {}).keys())
    all_columns = sorted(all_field_keys) or ["公司名称", "岗位名称", "城市", "薪资", "跟进状态", "招聘平台"]
    if "record_id" not in all_columns:
        all_columns.append("record_id")

    mem_db = sqlite3.connect(":memory:")
    mem_cursor = mem_db.cursor()
    col_def = ", ".join(f'"{c}" TEXT' for c in all_columns)
    mem_cursor.execute(f"CREATE TABLE feishu_jobs ({col_def})")
    placeholders = ", ".join("?" * len(all_columns))
    insert_data = [
        tuple(r.get("record_id", "") if c == "record_id" else _feishu_val_to_str(r.get("fields", {}).get(c, "")) for c in all_columns)
        for r in all_records
    ]
    mem_cursor.executemany(f"INSERT INTO feishu_jobs VALUES ({placeholders})", insert_data)
    mem_db.commit()

    count_sql = "SELECT COUNT(*) FROM feishu_jobs"
    if sql_where_clause:
        count_sql += f" WHERE {sql_where_clause}"
    total = mem_cursor.execute(count_sql).fetchone()[0]

    select_sql = "SELECT * FROM feishu_jobs"
    if sql_where_clause:
        select_sql += f" WHERE {sql_where_clause}"
    select_sql += f" LIMIT {limit}"
    mem_cursor.execute(select_sql)
    rows = mem_cursor.fetchall()
    col_names = [d[0] for d in mem_cursor.description]
    items = [dict(zip(col_names, row, strict=False)) for row in rows]
    mem_db.close()

    return {"total": total, "items": items, "columns": col_names, "raw_count": len(all_records)}


# ==========================================
# 📍 工具集（从 chatops_tools 统一导入）
# ==========================================
import app.core.chatops_tools as _tools_mod  # noqa: E402
from app.core.chatops_tools import ALL_TOOLS, set_runtime_context  # noqa: E402

tools = ALL_TOOLS

# ==========================================
# 📍 Agent 工作流定义
# ==========================================
SYSTEM_PROMPT = f"""你是一个顶级的高情商 AI 求职助理 Agent。你的核心职责是通过全链路自动化流水线帮老板高效求职。

【📚 全局数据库字典 (DB_SCHEMA)】
{DB_SCHEMA}

【🔧 可用工具 — 按意图分类】

▶ 执行类（老板要你干活 → 直接调，不要先查进度）
- run_full_pipeline: 全链路（抓取→清洗→飞书同步→AI评估→简历改写→投递），参数可选
- run_scraping: 仅抓取岗位，支持多平台并发（boss,liepin,51job,zhilian,xhs）
- run_cleaning: 仅执行数据清洗
- batch_task: 批量AI任务（evaluate/rewrite/deep_evaluate/deliver）
- approve_delivery: 审批放行/拒绝待投递岗位
- import_job: 通过文本快速录入岗位（岗位截图老板直接发图即可自动识别，无需此工具）

▶ 查询类（老板问情况）
- check_progress: 查询任务进度
- search_job_database: 查询本地数据库
- get_dashboard: 数据看板（overview/funnel/platform/trend）
- check_login_status: 各平台浏览器登录状态
- manage_goals(action="get"): 查看求职目标和进度

▶ 配置类（老板改设置）
- manage_goals(action="start/update/finish"): 设定/更新/结束求职目标
- manage_strategy: 自动化策略配置（查看/改定时任务/查偏好）
- update_feishu_records: 批量更新飞书记录字段

▶ 输出类（老板要东西）
- send_report: 发送战报（daily/weekly/monthly/final）
- interview_prep: 面试准备（handbook锦囊/init训练营）
- resume_ops: 简历操作（diagnosis/rewrite/greeting/ats_check）

🚨 行为铁律：
1. 老板要求执行动作时，直接调对应工具！不要先 check_progress 再决定。
2. 只有老板明确问"进度"/"跑到哪了"时才用 check_progress。
3. 老板说"跑一轮"/"全链路"→ run_full_pipeline
4. 老板说"爬一下"/"抓取"→ run_scraping（问清关键词和城市）
5. 老板说"清洗"/"推送飞书"/"同步"→ run_cleaning
6. 老板说"放行"/"通过"→ approve_delivery
7. 老板说"评估"/"改写"/"投递"→ batch_task
8. 老板说"日报"/"周报"/"月报"→ send_report
9. 老板说"面试准备"/"锦囊"→ interview_prep
10. 老板说"诊断简历"/"改写简历"/"打招呼语"→ resume_ops
11. 参数不齐必须反问，不要猜。
12. 回复简洁有力，用 emoji 分段，不要啰嗦。
"""

llm = ChatOpenAI(
    api_key=settings.OPENAI_API_KEY,
    base_url=settings.OPENAI_BASE_URL,
    model=settings.OPENAI_MODEL,
    temperature=0.1,
    timeout=180,  # 供应商网关挂起时必须有超时兜底，否则用户「思考中」后永久沉默且线程被占死
).bind_tools(tools)

def agent_node(state: JobHunterState):
    messages = state["messages"]
    if not messages or not isinstance(messages[0], SystemMessage):
        messages = [SystemMessage(content=SYSTEM_PROMPT)] + messages
    response = llm.invoke(messages)
    return {"messages": [response]}

workflow = StateGraph(JobHunterState)
workflow.add_node("agent", agent_node)
workflow.add_node("tools", ToolNode(tools))
workflow.add_edge(START, "agent")
workflow.add_conditional_edges("agent", tools_condition)
workflow.add_edge("tools", "agent")

# 持久化 checkpointer（AsyncSqliteSaver），在 init_agent_memory() 中初始化
_agent_checkpointer = None
agent_app = None  # 延迟编译，等 checkpointer 就绪


async def init_agent_memory(db_path: str = ""):
    """
    初始化 Agent 对话记忆的持久化存储。
    应在 FastAPI lifespan 中调用（与 init_automation_pipeline 并列）。
    """
    global _agent_checkpointer, agent_app
    from pathlib import Path as _Path

    import aiosqlite
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    if not db_path:
        # 默认落到 backend/data/（绝对路径），与 ChatAgent 的 checkpoint 同目录；
        # 相对路径会随启动目录漂移，静默换库
        db_path = str(_Path(__file__).resolve().parents[1] / "data" / "agent_chat_memory.db")
    conn = await aiosqlite.connect(db_path)
    _agent_checkpointer = AsyncSqliteSaver(conn)
    await _agent_checkpointer.setup()

    # 编译 Agent 图（带持久化 checkpointer）
    agent_app = workflow.compile(checkpointer=_agent_checkpointer)
    print(f"✅ [AgentRouter] 对话记忆持久化已就绪: {db_path}")


def _ensure_agent_app():
    """确保 agent_app 已编译（兜底：若异步初始化未执行，用 MemorySaver 编译）。"""
    global agent_app
    if agent_app is None:
        print("⚠️ [AgentRouter] 持久化未初始化，回退到 MemorySaver（重启丢失）")
        agent_app = workflow.compile(checkpointer=MemorySaver())
    return agent_app


# ==========================================
# 📡 Pipeline 进度监控 & 审批通知
# ==========================================
_active_monitors: dict[str, asyncio.Task] = {}  # task_id → monitor task


async def _pipeline_progress_monitor(chat_id: str, task_id: str):
    """
    后台协程：订阅 pipeline 的 SSE 队列，将进度推送到飞书群。
    检测到审批断点时，在群里提示用户放行。
    """
    import json as _json

    from app.tasks.state import task_queues

    # 等待队列创建（pipeline 启动有短暂延迟）
    for _ in range(20):
        if task_id in task_queues:
            break
        await asyncio.sleep(0.5)

    queue = task_queues.get(task_id)
    if not queue:
        await asyncio.to_thread(send_feishu_message, chat_id, f"⚠️ 任务 {task_id} 未产生进度队列，可能已结束。", "chat_id")
        return

    print(f"📡 [Monitor] 开始监听 pipeline 进度: {task_id} → {chat_id}")
    pending_approval_threads = []

    try:
        while True:
            try:
                raw = await asyncio.wait_for(queue.get(), timeout=300)  # 5分钟无消息则退出
            except asyncio.TimeoutError:
                await asyncio.to_thread(send_feishu_message, chat_id, f"📡 任务 {task_id} 已超时（5分钟无进度），监控退出。", "chat_id")
                break

            # 结束信号
            if '"type": "end"' in raw or '"type":"end"' in raw:
                await asyncio.to_thread(send_feishu_message, chat_id, f"🎉 全链路任务 {task_id} 已完成！", "chat_id")
                break
            if '"type": "terminated"' in raw or '"type":"terminated"' in raw:
                await asyncio.to_thread(send_feishu_message, chat_id, f"🛑 任务 {task_id} 已终止。", "chat_id")
                break

            # 解析 SSE 帧
            try:
                data_str = raw.replace("data: ", "").strip()
                if data_str.endswith("\n"):
                    data_str = data_str[:-1]
                event = _json.loads(data_str)
            except Exception:
                continue

            event_type = event.get("type", "")
            stage = event.get("stage", "")
            message = event.get("message", "")

            # 阶段完成通知
            if event_type == "stage_complete" and stage:
                stage_names = {
                    "scraping": "🕷️ 抓取",
                    "cleaning": "🧹 清洗",
                    "feishu_sync": "📤 飞书同步",
                    "evaluation": "🤖 AI评估",
                    "rewrite": "✍️ 简历改写",
                    "delivery": "🚀 投递",
                }
                stage_label = stage_names.get(stage, stage)
                detail = event.get("detail", "")
                msg = f"✅ {stage_label} 完成"
                if detail:
                    msg += f"\n   {detail}"
                await asyncio.to_thread(send_feishu_message, chat_id, msg, "chat_id")

            # 审批断点通知
            elif event_type == "manual_review" or "manual_review" in str(event):
                thread_id = event.get("thread_id", "")
                job_name = event.get("job_name", event.get("company_name", "未知岗位"))
                if thread_id:
                    pending_approval_threads.append(thread_id)
                msg = (
                    f"🔔 **审批请求**\n"
                    f"岗位: {job_name}\n"
                    f"线程ID: {thread_id}\n\n"
                    f"回复「放行」批准投递，或「拒绝」跳过。"
                )
                await asyncio.to_thread(send_feishu_message, chat_id, msg, "chat_id")

            # 错误通知
            elif event_type == "error":
                err_msg = event.get("error", message)
                await asyncio.to_thread(send_feishu_message, chat_id, f"❌ 流水线异常: {err_msg}", "chat_id")

    except asyncio.CancelledError:
        print(f"📡 [Monitor] 监控被取消: {task_id}")
    except Exception as e:
        print(f"📡 [Monitor] 监控异常退出: {e}")
    finally:
        _active_monitors.pop(task_id, None)


def start_pipeline_monitor(chat_id: str, task_id: str):
    """启动 pipeline 进度监控（非阻塞）。"""
    if task_id in _active_monitors:
        return  # 已在监控
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            task = asyncio.ensure_future(_pipeline_progress_monitor(chat_id, task_id))
            _active_monitors[task_id] = task
            print(f"📡 [Monitor] 已启动进度监控: {task_id}")
    except Exception as e:
        print(f"⚠️ [Monitor] 启动失败: {e}")


async def _handle_quick_approval(chat_id: str, action: str = "approve"):
    """快捷审批：委托 quick_approval 子模块（Q-M9-2：扫描源=内存∪SQLite停车场，重启不漏审）。"""
    from app.services.quick_approval import handle_quick_approval

    await handle_quick_approval(chat_id, action=action)


# ==========================================
# 🚀 对外入口
# ==========================================
# 老链路全局串行锁：工具运行时上下文（loop/chat_id）、_pending_pipeline_task_id 与
# pipeline 审批断点恢复都是模块级全局态，并发消息会互相覆盖——A 群回复错投进 B 群、
# 断点被重复 resume 导致投递重复执行。本链路现在仅作 ChatAgent 未就绪时的回退通道，
# 串行化彻底消除竞态，单用户场景吞吐完全足够。
_chatops_lock = asyncio.Lock()


async def process_chatops_query(chat_id: str, user_input: str, root_id: str | None = None):
    """飞书消息处理主入口（全局串行化，防全局上下文并发污染/断点重复恢复）。"""
    async with _chatops_lock:
        await _process_chatops_query_locked(chat_id, user_input, root_id)


async def _process_chatops_query_locked(chat_id: str, user_input: str, root_id: str | None = None):
    """
    飞书消息处理主入口。

    Args:
        chat_id: 飞书群 ID
        user_input: 清洗后的用户文本
        root_id: 飞书话题根消息 ID（话题内消息才有，主对话流为 None）
    """
    from app.core.context_summarizer import should_summarize, summarize_messages
    from app.core.session_manager import get_session_manager

    # 设置运行时上下文（主事件循环 + chat_id），供工具模块调度异步任务
    set_runtime_context(asyncio.get_running_loop(), chat_id)

    print(f"\n💬 [ChatOps] 收到飞书消息 | chat_id: {chat_id} | root_id: {root_id} | 内容: {user_input}")

    # 1. Session 解析
    sm = get_session_manager()

    # 检查是否为显式新对话指令
    if user_input.strip().lower() in ("/new", "/reset", "新对话", "新会话"):
        session = sm.force_new_session(chat_id, root_id)
        await asyncio.to_thread(send_feishu_message, chat_id, "🆕 已开启新对话，之前的上下文已归档。", "chat_id")
        return

    # 快捷审批指令（不走 Agent，直接执行；词表单一事实源=chatops_authorizer，Q-M9-4 门禁同源）
    _lower_input = user_input.strip().lower()
    from app.core.chatops_authorizer import (
        APPROVAL_APPROVE_WORDS,
        APPROVAL_REJECT_WORDS,
    )
    if _lower_input in APPROVAL_APPROVE_WORDS:
        await _handle_quick_approval(chat_id, action="approve")
        return
    if _lower_input in APPROVAL_REJECT_WORDS:
        await _handle_quick_approval(chat_id, action="reject")
        return

    session = sm.resolve_session(chat_id, root_id)
    thread_id = session.session_id
    config = {"configurable": {"thread_id": thread_id}}

    app = _ensure_agent_app()

    try:
        await asyncio.to_thread(send_feishu_message, chat_id, "⚙️ 首席架构助理正在思考并调度工具，请稍候...", "chat_id")

        # 2. 获取当前历史，检查是否需要摘要压缩
        existing_summary = sm.get_session_summary(thread_id)
        try:
            state_snapshot = await app.aget_state(config)
            if state_snapshot and state_snapshot.values.get("messages"):
                history = state_snapshot.values["messages"]
                if should_summarize(history, existing_summary):
                    new_summary, _ = summarize_messages(history, existing_summary)
                    if new_summary:
                        sm.save_session_summary(thread_id, new_summary)
                        print(f"📝 [ChatOps] 上下文已压缩，摘要 {len(new_summary)} 字")
        except Exception as e:
            print(f"⚠️ [ChatOps] 摘要检查跳过: {e}")

        # 3. 执行 Agent
        def run_agent():
            return app.invoke({"messages": [("user", user_input)]}, config=config)

        final_state = await asyncio.to_thread(run_agent)
        final_message = final_state["messages"][-1].content
        await asyncio.to_thread(send_feishu_message, chat_id, final_message, "chat_id")
        print("✅ [ChatOps] 响应已成功推送至飞书！")

        # 4. 如果 Agent 触发了全链路 pipeline，启动进度监控
        if _tools_mod._pending_pipeline_task_id:
            start_pipeline_monitor(chat_id, _tools_mod._pending_pipeline_task_id)
            _tools_mod._pending_pipeline_task_id = None
    except Exception as e:
        import traceback
        traceback.print_exc()
        await asyncio.to_thread(send_feishu_message, chat_id, f"❌ Agent 核心引擎崩溃了: {str(e)}", "chat_id")

if __name__ == "__main__":
    print("\n" + "="*50 + "\n🤖 Agent 引擎已启动！(输入 'quit' 退出)\n" + "="*50 + "\n")
    _app = _ensure_agent_app()
    config = {"configurable": {"thread_id": "test_session_1"}}
    while True:
        user_input = input("\n👨‍💻 老板: ")
        if user_input.lower() in ['quit', 'exit', 'q']:
            break
        events = _app.stream({"messages": [("user", user_input)]}, config=config, stream_mode="values")
        for event in events:
            last_message = event["messages"][-1]
            if last_message.type == "ai" and getattr(last_message, "tool_calls", None):
                for tc in last_message.tool_calls:
                    print(f"👉 准备使用工具: {tc['name']}")
            elif last_message.type == "ai" and not getattr(last_message, "tool_calls", None):
                print(f"\n🤖 助理: {last_message.content}")
