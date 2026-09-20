"""ChatAgent：飞书聊天框的模型驱动 agent harness。

技术栈：langchain.agents.create_agent（LangGraph 官方 ReAct 预置，1.x 推荐入口）
+ AsyncSqliteSaver（thread_id=chat_id_YYYYMM 按月切片，会话跨重启续接；老月份 thread 沉寂后由 checkpoint_gc 自动回收，根治单 thread O(N²) 膨胀；真实 chat_id 经 configurable[chat_id] 注入工具层）
+ MiMo（OpenAI 兼容端点；function calling 已真机验证 6/6 + 稳定性 3/3，深度思考随 reasoning_content 外显）。

红线（system prompt 与工具描述双重约束）：绝不自动/批量投递；写操作仅限用户明确表达的单条变更。
"""
import asyncio
import logging
import uuid
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_agent_app = None
_checkpointer = None
# 绝对路径（backend/data/）：相对路径会随启动目录漂移，静默换库丢记忆
_CHECKPOINT_DB = str(Path(__file__).resolve().parents[3] / "data" / "agent_chat_checkpoints.db")

# 会话上下文自动修剪：消息数超过 _HISTORY_TRIGGER 时，把旧消息压缩成一段摘要、
# 保留最近 _HISTORY_KEEP 条原文。checkpoint 只添不剪会无限膨胀（实测 76MB/338 快照），
# 且每轮 ainvoke 重放全量历史，撑爆模型上下文后每条消息都会「处理失败」。
_HISTORY_TRIGGER = 40
_HISTORY_KEEP = 20
_SUMMARY_PREFIX = "【历史对话摘要】"

# 同会话串行锁：卡片回调重放/用户催促重发/重启后事件重投等并发投递，
# 必须排队执行，否则两个 agent 运行各产出一条回复（重复回复的并发源）。
_chat_locks: dict = {}

# 单轮 agent 运行的 super-step 上限（覆盖 create_agent 默认的 9999，
# 正常对话 ~10 步内完成；配合工具层循环熔断双保险防死循环刷消息）。
_MAX_RECURSION_PER_TURN = 60

def _thread_id_for(chat_id: str) -> str:
    """会话 checkpoint 按月切片（TODO.md 数据库治理第 4 项首选方案）。

    thread_id = f"{chat_id}_{YYYYMM}"：同一飞书群每月一个新 thread，
    单 thread 的 checkpoint 链不再无限累积；老月份 thread 沉寂超 90 天后
    由 checkpoint_gc 按现有保护规则自动物理回收。真实 chat_id 经
    configurable["chat_id"] 并行注入，工具层发消息仍用原 chat_id。
    """
    return f"{chat_id}_{datetime.now():%Y%m}"


SYSTEM_PROMPT = """你是老板的求职助理 Agent。

【工作方式】
1. 涉及岗位、简历、评估进度的事实问题，必须调用工具查询后再回答，绝不凭记忆猜测。
2. 回答只基于工具返回的数据；工具失败就如实说明并给出建议，不要编造结果。
3. 当消息中提供了【当前焦点岗位上下文】(包含 record_id、公司名、岗位名) 时，如果用户的提问使用了“这个岗位/它/当前岗位/刚才的岗位/发我链接/详情”等代词或上下文指代，请直接基于该 record_id 调用 read_job_resume 等工具，严禁再次向用户询问公司名或调用 locate_job 重新搜索。
4. 需要定位全新未绑定的岗位时先用 locate_job 拿 record_id，再调其他工具。
5. 查询公司背景、业务情报、近期重大动态或AI布局时，优先调用 query_company_intel 工具（支持多维表格缓存与全网实时检索）。
6. 【重要】当 locate_job 返回 found > 1（多个候选）且 card_sent=true 时，系统已自动向用户发送了可点选的候选卡片。你必须立即停止调用 locate_job，严禁在当前回合再次调用 locate_job 尝试穷举或猜测！只需用一两句话简短提示用户点击上方卡片进行选择，严禁再用 Markdown 表格或大段列表重复输出岗位清单。
7. 简历修改与微调闭环：
   - ① 修改简历用 edit_resume_json，它产出修改稿（暂存草案）；
   - ② 如果用户对修改稿提出部分采纳（如“只要前3项，第4项不要/工作经历保持原样”）或继续微调，再次调用 edit_resume_json 迭代草案；
   - ③ 当用户对草案表示认可、确认或发出生成指令（如“帮我生成吧/确认生成/就按这个出物料/确认修改/写回/出新简历”）时，调用 confirm_and_render_materials 完成正式写回多维表格与重新渲染交付物料闭环；
   - ④ 当用户明确表示放弃/取消修改（如“取消修改/不改了”）时，调用 cancel_resume_edit。
8. 当用户表达「已投递/投递完成」等意图时，调用 update_follow_status(record_id, status="已投递", set_delivery_date=True)。
9. 对话历史里已有当前岗位上下文时不要重复定位；用户问「刚才改的哪个岗位」这类状态问题，基于历史直接回答。

【红线】
- 绝不自动投递、绝不批量投递；更新跟进状态仅在用户明确表达时执行单条变更。
- 不确定用户指哪个岗位且无上下文焦点时，先问清楚，不要猜。

【风格】中文，简洁直接，重点信息前置，不罗列工具清单。"""


def is_ready() -> bool:
    return _agent_app is not None


async def init_chat_agent() -> None:
    """lifespan 调用：编译 agent（checkpointer 长连接与 scheduler 同款模式，进程内存活）。"""
    global _agent_app, _checkpointer
    if _agent_app is not None:
        return
    import aiosqlite
    from langchain.agents import create_agent
    from langchain_openai import ChatOpenAI
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    from app.services.chat_agent.tools import CHAT_TOOLS
    from common.config import _cfg

    # 模型名与 key/url 统一走 _cfg（settings.json 优先、页面保存即生效）；
    # 此前模型名读 pydantic settings，UI 配置用户的「推理模型」会被静默忽略
    model_name = _cfg("OPENAI_MODEL", json_key="OPENAI_MODEL") or "mimo-v2.5-pro"
    key = _cfg("OPENAI_API_KEY", "LLM_API_KEY", "api_key", json_key="OPENAI_API_KEY")
    url = _cfg("OPENAI_BASE_URL", "LLM_BASE_URL", "base_url", json_key="OPENAI_BASE_URL")

    from app.core.llm_tracker import make_langchain_token_callback
    cb = make_langchain_token_callback(model_name, caller="chat_agent")

    model = ChatOpenAI(
        model=model_name, api_key=key, base_url=url,
        temperature=0, timeout=180, max_retries=2,
        callbacks=[cb] if cb else None,
    )

    conn = await aiosqlite.connect(_CHECKPOINT_DB)
    _checkpointer = AsyncSqliteSaver(conn)
    await _checkpointer.setup()
    _agent_app = create_agent(
        model=model, tools=CHAT_TOOLS, system_prompt=SYSTEM_PROMPT, checkpointer=_checkpointer,
    )
    logger.info(f"🤖 [ChatAgent] 就绪 | model={model_name} | tools={[t.name for t in CHAT_TOOLS]}")


_reinit_lock: asyncio.Lock = asyncio.Lock()


async def reinit_chat_agent() -> bool:
    """配置页保存 LLM 配置后重建 agent（换 Key / 换模型热生效）。

    返回 True 表示 agent 已就绪。未配置 Key 时不构建（保持 None，消息继续走老链路回退）。
    旧的 sqlite checkpointer 连接不主动关闭：重建是用户保存配置时的低频动作，
    在跑的会话可安全用完旧连接；主动关闭反而可能打断 in-flight 的 ainvoke。
    """
    async with _reinit_lock:
        from common.config import _cfg

        if not _cfg("OPENAI_API_KEY", "LLM_API_KEY", "api_key", json_key="OPENAI_API_KEY"):
            logger.info("[ChatAgent] 未配置 LLM Key，跳过重建（消息将走老链路回退）")
            return False
        _agent_app = None
        await init_chat_agent()
        return _agent_app is not None


def _to_text(content) -> str:
    """AIMessage.content 兼容：str 或内容块列表。"""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        return "\n".join(
            str(b.get("text", "")) for b in content if isinstance(b, dict) and b.get("text")
        ).strip()
    return str(content or "").strip()


async def send_agent_reply(chat_id: str, reply_text: str, title: str = "🤖 求职助理") -> None:
    """优先以 interactive card (lark_md) 发送富文本回复，失败时自动平滑降级为普通文本。

    卡片发送失败后先用同一幂等键重试一次：超时类失败无法判定飞书是否已收下
    （请求可能已送达、只是响应丢失），同 uuid 重试由飞书幂等去重保证不双发；
    重试仍失败（多半是卡片被明确拒绝）才降级纯文本，宁可单份文本也不「卡+文」双份。
    """
    from app.core.feishu_messaging import send_feishu_card, send_feishu_message
    from app.services.chat_agent.card_builder import build_agent_reply_card

    card = build_agent_reply_card(reply_text, title=title)
    dedup_key = str(uuid.uuid4())
    try:
        await send_feishu_card(chat_id, card, idempotency_key=dedup_key)
    except Exception as e:
        try:
            await send_feishu_card(chat_id, card, idempotency_key=dedup_key)
            logger.info(f"[ChatAgent] 卡片首次发送异常({type(e).__name__})，同幂等键重试成功 | chat_id={chat_id}")
            return
        except Exception as e2:
            logger.warning(f"[ChatAgent] 卡片发送失败，降级为普通文本 | chat_id={chat_id}: {e2}")
            try:
                await send_feishu_message(chat_id, reply_text, "chat_id",
                                          idempotency_key=str(uuid.uuid4()))
            except Exception:
                logger.exception(f"[ChatAgent] 降级普通文本亦失败 | chat_id={chat_id}")


async def _trim_thread_history(chat_id: str, config: dict) -> None:
    """会话历史超阈值时压缩旧消息为摘要（LLM 调用失败则直接截断，绝不阻塞对话）。

    裁剪点只落在 HumanMessage 边界，保证不拆散 tool_call/tool_result 配对
    （拆散会让 LangGraph 校验直接报错）。
    """
    from langchain_core.messages import HumanMessage
    from langgraph.graph.message import REMOVE_ALL_MESSAGES, RemoveMessage

    from app.core.context_summarizer import summarize_messages

    try:
        state = await _agent_app.aget_state(config)
        msgs = list((state.values or {}).get("messages") or [])
        if len(msgs) <= _HISTORY_TRIGGER:
            return

        cut = len(msgs) - _HISTORY_KEEP
        while cut < len(msgs) and not isinstance(msgs[cut], HumanMessage):
            cut += 1
        if cut >= len(msgs):
            return
        overflow, recent = msgs[:cut], msgs[cut:]

        # 累积摘要：上一段摘要若作为首条注入消息存在，取出继续压缩
        prev_summary = ""
        first = overflow[0]
        if isinstance(first, HumanMessage) and str(first.content or "").startswith(_SUMMARY_PREFIX):
            prev_summary = str(first.content).removeprefix(_SUMMARY_PREFIX).strip()

        summary, _ = await asyncio.to_thread(summarize_messages, overflow, prev_summary)
        if not summary:
            summary = "（早期对话较长，已省略）"

        trimmed = [
            RemoveMessage(id=REMOVE_ALL_MESSAGES),
            HumanMessage(content=f"{_SUMMARY_PREFIX}{summary}\n\n以下为最近对话："),
            *recent,
        ]
        await _agent_app.aupdate_state(config, {"messages": trimmed})
        logger.info(f"[ChatAgent] 会话历史已压缩 | chat_id={chat_id} | {len(msgs)}条 → 摘要+{len(recent)}条")
    except Exception as e:
        logger.warning(f"[ChatAgent] 会话历史修剪失败（本轮跳过，不影响对话）| chat_id={chat_id}: {e}")


async def handle_agent_message(chat_id: str, text: str) -> bool:
    """ChatAgent 统一入口。返回 True=已消费（失败也致歉消费，防双回复）；False=未就绪，调用方回退老链路。"""
    if _agent_app is None:
        return False
    from app.core.config import settings
    from app.core.feishu_client import feishu_client
    from app.core.feishu_messaging import send_feishu_message
    from app.services.resume_edit_chat import _resolve_context_target

    # 同会话串行化：先给即时反馈，再排队等前一轮跑完
    await send_feishu_message(chat_id, "🤖 正在思考…", "chat_id")
    lock = _chat_locks.setdefault(chat_id, asyncio.Lock())
    async with lock:
        run_config = {
            "configurable": {
                "thread_id": _thread_id_for(chat_id),
                "chat_id": chat_id,  # 工具层发飞书消息用真实 chat_id，与 thread_id 解耦
            },
            "recursion_limit": _MAX_RECURSION_PER_TURN,
        }
        try:
            # 每轮重置工具循环熔断历史（守卫只在单轮运行内生效，跨轮不误伤重复提问）
            from app.services.chat_agent.tools import reset_loop_guard
            reset_loop_guard(chat_id)

            # 历史超阈值先压缩（防 checkpoint 无限膨胀撑爆上下文）
            await _trim_thread_history(chat_id, run_config)

            # 动态检测当前会话锁定的焦点岗位（防指代代词断链）
            user_content = text
            active_rid = _resolve_context_target(chat_id)
            if active_rid:
                try:
                    rec = await feishu_client.fetch_bitable_record_by_id(settings.FEISHU_TABLE_ID_JOBS, active_rid)
                    fields = (rec or {}).get("fields", {}) or {}
                    def _fmt(v):
                        if isinstance(v, str):
                            return v.strip()
                        if isinstance(v, list):
                            return "".join(x.get("text", "") for x in v if isinstance(x, dict)).strip()
                        return str(v or "").strip()
                    company = _fmt(fields.get("公司名称")) or "未知公司"
                    job = _fmt(fields.get("岗位名称")) or "未知岗位"
                    status = _fmt(fields.get("跟进状态")) or "未知状态"
                    user_content = (
                        f"【当前焦点岗位上下文】当前会话正在跟进岗位【{company} · {job}】"
                        f"（record_id: {active_rid}，当前状态: {status}）。\n"
                        f"用户提问：{text}"
                    )
                except Exception as ctx_err:
                    logger.warning(f"[ChatAgent] 读取焦点岗位上下文异常: {ctx_err}")

            result = await _agent_app.ainvoke(
                {"messages": [{"role": "user", "content": user_content}]},
                config=run_config,
            )
            reply = _to_text(result["messages"][-1].content)
            await send_agent_reply(chat_id, reply or "（这次没有产出回复，换个说法试试？）")
            return True
        except Exception as e:
            logger.exception(f"[ChatAgent] 处理失败 | chat_id={chat_id}: {e}")
            try:
                await send_agent_reply(chat_id, f"❌ 处理失败：{str(e)[:150]}\n可换个说法重试。", title="⚠️ 助理提示")
            except Exception:
                pass
            return True
