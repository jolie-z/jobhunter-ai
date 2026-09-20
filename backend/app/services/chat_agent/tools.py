"""ChatAgent 工具层（第一批六件套）。

模式覆盖：实体定位（locate_job）、只读查询（read_job_resume / check_evaluation_progress）、
受控写入（update_follow_status）、长任务异步（start_evaluation）、会话迭代（edit_resume_json）。
后续加工具 = 选模式 → 填实现 → 写描述（描述即意图路由依据）→ 跑评测。

chat_id 不进工具签名，经 RunnableConfig 注入（thread_id == chat_id，见 agent.py）。
红线双重约束：本层工具描述 + agent.py 的 system prompt 都写明「绝不自动/批量投递」。
"""
import asyncio
import functools
import json
import logging
import time
from datetime import datetime
from typing import Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

logger = logging.getLogger(__name__)


def _chat_id(config: RunnableConfig = None) -> str:
    """真实 chat_id：优先读 configurable["chat_id"]（thread_id 按月切片后
    含 _YYYYMM 后缀，不能直接当 chat_id 发消息）；兼容旧的纯 thread_id 传参。"""
    conf = (config or {}).get("configurable") or {}
    return str(conf.get("chat_id") or conf.get("thread_id") or "")


def _txt(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, (int, float, bool)):
        return str(v)
    if isinstance(v, dict):
        if "link" in v:
            return str(v.get("link") or v.get("text") or "").strip()
        if "text" in v:
            return str(v.get("text") or "").strip()
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, list):
        items = []
        for x in v:
            if isinstance(x, dict):
                items.append(x.get("link") or x.get("text") or x.get("name") or "")
            elif isinstance(x, str):
                items.append(x)
        return "".join(items).strip()
    return str(v or "").strip()


def _j(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False)


_locate_card_sent_ts: dict[str, float] = {}

# 后台评估流水线任务的强引用集合（防 GC 中途回收，见 start_evaluation）
_BACKGROUND_EVAL_TASKS: set = set()


# ==========================================
# 循环熔断守卫：同会话内「同工具+同参数」连续调用达阈值时拒绝执行，
# 强制模型基于已有结果作答。根治 MiMo 同回合重复调用导致的重复发卡/重发物料
# （实测：confirm_and_render_materials 连环 9 次全 success、query_company_intel 连环 43 次）。
# 历史按轮次重置（handle_agent_message 每轮调用 reset_loop_guard），跨轮不误伤。
# ==========================================
_LOOP_GUARD_LIMIT_DEFAULT = 2   # 只读工具：允许连续相同调用 2 次，第 3 次熔断
_LOOP_GUARD_LIMIT_WRITE = 1     # 写副作用工具：第 2 次相同调用即熔断（重复执行=重复交付）
_LOOP_TOOLS_WRITE = {
    "confirm_and_render_materials", "update_follow_status", "edit_resume_json",
    "start_evaluation", "archive_duplicate_jobs", "approve_duplicate_suspects",
    "start_liveness_check", "send_report",
}
_loop_history: dict[str, list[str]] = {}   # chat_id -> 本轮最近调用签名序列
_loop_guard_hits: dict[str, int] = {}      # 熔断命中计数（观测用）


def _call_signature(tool_name: str, args: dict[str, Any]) -> str:
    try:
        return json.dumps({"t": tool_name, "a": args}, sort_keys=True, ensure_ascii=False, default=str)
    except Exception:
        return f"{tool_name}:{args!r}"


def reset_loop_guard(chat_id: str) -> None:
    """新一轮用户消息开始时清空调用历史（守卫只在单轮 agent 运行内生效）。"""
    _loop_history.pop(chat_id, None)
    _loop_guard_hits.pop(chat_id, None)


def _loop_guard_should_block(chat_id: str, tool_name: str, signature: str) -> bool:
    """返回 True 表示本次调用应被熔断（禁止重复执行）。"""
    if not chat_id:
        return False
    hist = _loop_history.setdefault(chat_id, [])
    consecutive = 0
    for sig in reversed(hist):
        if sig != signature:
            break
        consecutive += 1
    limit = _LOOP_GUARD_LIMIT_WRITE if tool_name in _LOOP_TOOLS_WRITE else _LOOP_GUARD_LIMIT_DEFAULT
    if consecutive >= limit:
        _loop_guard_hits[chat_id] = _loop_guard_hits.get(chat_id, 0) + 1
        return True
    hist.append(signature)
    del hist[:-12]  # 只保留最近 12 条，防内存膨胀
    return False


def guard_tool_loop(tool_obj):
    """给 langchain 工具挂载循环熔断：连续相同调用超限时返回终止指令而非执行。"""
    original = getattr(tool_obj, "coroutine", None)
    if original is None:
        return tool_obj
    tool_name = getattr(tool_obj, "name", "") or "tool"

    @functools.wraps(original)
    async def guarded(*args: Any, **kwargs: Any):
        chat_id = _chat_id(kwargs.get("config"))
        sig_args = {k: v for k, v in kwargs.items() if k != "config"}
        if args:  # 位置参数调用无法可靠签名，放行走原路径
            return await original(*args, **kwargs)
        if _loop_guard_should_block(chat_id, tool_name, _call_signature(tool_name, sig_args)):
            logger.warning(f"[ChatAgent][循环熔断] {tool_name} 连续相同调用被拦截 | chat_id={chat_id}")
            return _j({
                "loop_guarded": True,
                "error": f"工具 {tool_name} 已用完全相同的参数连续调用过多次。",
                "hint": "严禁再次调用该工具！你此前已经拿到过它的返回结果，请立即基于已有结果向用户输出最终中文回答。",
            })
        return await original(*args, **kwargs)

    try:
        tool_obj.coroutine = guarded
    except Exception:
        logger.warning(f"[ChatAgent] 工具 {tool_name} 无法挂载循环熔断守卫")
    return tool_obj


@tool
async def locate_job(company: str, job_title: str = "", config: RunnableConfig = None) -> str:
    """按「公司名+岗位名」在岗位表中模糊定位岗位，返回候选列表（含 record_id 与跟进状态）。

    何时用：用户想查看/修改某个岗位但没有 record_id 时，先调用本工具拿到 record_id。
    何时不用：对话里已经明确了当前岗位（如刚交付过物料、刚评估过），直接用 read_job_resume。
    注意：当返回多个候选岗位时，系统会自动在飞书聊天框推送可交互的候选卡片。
    """
    from app.services import resume_edit_chat

    query = f"{company} {job_title}".strip()
    cands = await resume_edit_chat.find_job_candidates(query)
    if not cands:
        return _j({"found": 0, "hint": "岗位表没有匹配，请向用户确认公司名与岗位名后重试"})

    # 1. 唯一命中或首个候选具有压倒性高置信度（直接返回 record_id 供后续工具串联）
    if len(cands) == 1 or (cands and cands[0].get("score", 0) >= 0.85 and (len(cands) == 1 or (cands[0]["score"] - cands[1]["score"]) >= 0.25)):
        cand = cands[0]
        return _j({
            "found": 1,
            "record_id": cand["record_id"],
            "company": cand["company"],
            "title": cand["title"],
            "status": cand.get("status", ""),
            "candidates": cands,
        })

    # 2. 多候选：推交互卡片（严格节流防重，10秒内单 chat_id 仅允许推送 1 张）
    chat_id = _chat_id(config)
    card_sent = False
    now = time.time()
    if chat_id and (now - _locate_card_sent_ts.get(chat_id, 0) >= 10.0):
        from app.core.feishu_messaging import send_feishu_card
        try:
            card = resume_edit_chat.build_candidates_card(cands)
            await send_feishu_card(chat_id, card)
            _locate_card_sent_ts[chat_id] = now
            if len(_locate_card_sent_ts) > 1000:  # 只进不出的节流账本定期瘦身
                for k in list(_locate_card_sent_ts)[:500]:
                    _locate_card_sent_ts.pop(k, None)
            resume_edit_chat._pending_locate[chat_id] = json.dumps(
                {"candidates": cands, "instruction": None}, ensure_ascii=False
            )
            card_sent = True
        except Exception:
            pass
    elif chat_id and chat_id in _locate_card_sent_ts:
        card_sent = True  # 本轮已推送过

    return _j({
        "found": len(cands),
        "card_sent": card_sent,
        "candidates": cands[:5],
        "hint": (
            "已在飞书聊天框为用户推送了包含匹配岗位的交互选择卡片。"
            "【重要指令】请直接简短回复用户提示其点击上方卡片选择具体岗位即可，严禁在当前回合再次调用 locate_job 重新搜索，严禁重复输出大段岗位列表！"
            if card_sent else
            "找到了多个匹配岗位，请向用户询问具体是指哪一个。"
        ),
    })


@tool
async def read_job_resume(record_id: str, config: RunnableConfig = None) -> str:  # noqa: ARG001  # LangChain 注入
    """读取岗位在飞书多维表格中的全量完整画像数据。

    包含字段：
    1. 基础盘：公司名称、岗位名称、岗位链接(job_link)、招聘平台、薪资、城市、工作地址、经验要求、学历要求、公司规模、所属行业、发布日期、HR活跃度、岗位详情
    2. 状态与物料：跟进状态、投递日期、淘汰原因、打招呼语、AI改写简历(resume_json)
    3. AI 评估与深度诊断：综合评级 (A-F)、AI评估详情、8个细项维度评分、高杠杆匹配点、致命硬伤与毒点、破局行动计划、理想画像与能力信号、核心能力词典

    何时用：回答关于该岗位的任何事实问题（如“发我链接”、“在哪个区上班”、“为什么评B级”、“改写简历里写了什么”、“面试有什么建议”）。
    """
    from app.core.config import settings
    from app.core.feishu_client import feishu_client

    rec = await feishu_client.fetch_bitable_record_by_id(settings.FEISHU_TABLE_ID_JOBS, record_id)
    if not rec:
        return _j({"error": f"记录 {record_id} 不存在"})
    fields = (rec or {}).get("fields", {}) or {}

    return _j({
        "record_id": record_id,
        "company": _txt(fields.get("公司名称")),
        "job_title": _txt(fields.get("岗位名称")),
        "job_link": _txt(fields.get("岗位链接")),
        "platform": _txt(fields.get("招聘平台")),
        "salary": _txt(fields.get("薪资")),
        "city": _txt(fields.get("城市")),
        "work_address": _txt(fields.get("工作地址")),
        "experience": _txt(fields.get("经验要求")),
        "education": _txt(fields.get("学历要求")),
        "company_scale": _txt(fields.get("公司规模")),
        "industry": _txt(fields.get("所属行业")),
        "publish_date": _txt(fields.get("发布日期")),
        "hr_activity": _txt(fields.get("HR活跃度")),
        "scrape_time": _txt(fields.get("抓取时间")),
        "job_detail": _txt(fields.get("岗位详情"))[:2500],

        # 状态与物料
        "follow_status": _txt(fields.get("跟进状态")),
        "delivery_date": _txt(fields.get("投递日期")),
        "reject_reason": _txt(fields.get("淘汰原因")),
        "greeting": _txt(fields.get("打招呼语"))[:500],
        "resume_json": _txt(fields.get("AI改写JSON"))[:8000],

        # AI 评估与 8 维打分
        "grade": _txt(fields.get("综合评级 (A-F)")),
        "eval_detail": _txt(fields.get("AI评估详情"))[:2500],
        "scores_8_dimensions": {
            "核心-角色匹配": _txt(fields.get("核心-角色匹配")),
            "核心-技能重合": _txt(fields.get("核心-技能重合")),
            "高权-薪资契合": _txt(fields.get("高权-薪资契合")),
            "高权-职级资历": _txt(fields.get("高权-职级资历")),
            "高权-面试概率": _txt(fields.get("高权-面试概率")),
            "中权-赛道前景": _txt(fields.get("中权-赛道前景")),
            "中权-成长空间": _txt(fields.get("中权-成长空间")),
            "中权-公司阶段": _txt(fields.get("中权-公司阶段")),
        },

        # 深度策略与诊断
        "company_intel": _txt(fields.get("公司业务情报")),
        "high_leverage_matches": _txt(fields.get("高杠杆匹配点")),
        "deal_breakers": _txt(fields.get("致命硬伤与毒点")),
        "action_plan": _txt(fields.get("破局行动计划")),
        "ideal_persona": _txt(fields.get("理想画像与能力信号")),
        "core_skills_dict": _txt(fields.get("核心能力词典")),
    })


@tool
async def query_company_intel(company: str = "", record_id: str = "", config: RunnableConfig = None) -> str:  # noqa: ARG001  # LangChain 注入
    """查询公司的业务情报、近期重大动态、AI落地战略与商业前景（支持本地缓存与全网实时搜索）。

    何时用：用户问「查这家公司的业务情报」「公司背景如何」「公司最近有什么AI新闻/业务动态」，或点击了「🏢 查公司业务情报」卡片按钮。
    优先：若传入 record_id，会优先读取飞书岗位表中已有的「公司业务情报」缓存；若无缓存或仅提供公司名，则自动触发网络深度搜索并智能汇总。
    """
    from ai_agents.company_intel import fetch_company_intel
    from app.core.config import settings
    from app.core.feishu_client import feishu_client

    company_name = company.strip()
    cached_intel = ""

    if record_id:
        rec = await feishu_client.fetch_bitable_record_by_id(settings.FEISHU_TABLE_ID_JOBS, record_id)
        if rec and "fields" in rec:
            fields = rec["fields"]
            if not company_name:
                company_name = _txt(fields.get("公司名称"))
            intel_val = _txt(fields.get("公司业务情报"))
            if intel_val and not intel_val.startswith("⚠️"):
                cached_intel = intel_val

    if cached_intel:
        return _j({
            "company": company_name,
            "source": "bitable_cached",
            "intelligence": cached_intel,
            "note": "已获取该公司的业务情报与背景分析（来自岗位评估沉淀数据）。",
        })

    if not company_name:
        return _j({"error": "缺少公司名称或有效的岗位记录，无法发起情报检索。"})

    # 触发实时搜索与研报汇总
    intel = await asyncio.to_thread(fetch_company_intel, company_name)
    if intel and not intel.startswith("⚠️") and record_id:
        try:
            from app.services.feishu_service import update_feishu_record
            await asyncio.to_thread(update_feishu_record, record_id, {"公司业务情报": intel})
        except Exception:
            pass

    return _j({
        "company": company_name,
        "source": "live_web_search",
        "intelligence": intel,
        "note": "已通过实时网络深度搜索并由大模型提炼完成公司业务情报。",
    })


@tool
async def edit_resume_json(record_id: str, instruction: str, config: RunnableConfig = None) -> str:
    """按自然语言指令定向修改岗位的定制简历（AI改写JSON）。只改指令涉及的内容，绝不编造经历。

    何时用：用户明确要求修改简历内容时。支持多轮迭代：每轮调用自动以上一轮修改稿为基准。
    重要：本工具只产出修改稿并登记待确认会话，不直接写回飞书——用户回复「确认生成」后才会重新渲染物料。
    请把返回的改动摘要转述给用户，并提醒回复「确认生成」。
    """
    chat_id = _chat_id(config)
    if not chat_id:
        return _j({"error": "缺少会话标识"})
    from app.services import resume_edit_chat

    base = await resume_edit_chat._load_resume_base(record_id)
    if base is None:
        return _j({"error": "该岗位的简历内容无法解析（可能尚未评估或旧格式解析失败），建议先对岗位发起评估"})
    try:
        edited = await resume_edit_chat._llm_edit_resume(base, instruction)
    except Exception as e:
        return _j({"error": f"修改失败: {e}"})
    diff = resume_edit_chat._diff_summary(base, edited)
    resume_edit_chat._set_edit_session(chat_id, {
        "record_id": record_id,
        "stage": "confirm",
        "updated": json.dumps(edited, ensure_ascii=False),
        "orig": json.dumps(base, ensure_ascii=False),
    })
    return _j({"diff": diff, "next": "改动已登记待确认；请转述改动摘要并提醒用户回复「确认生成」或表达生成意愿出物料"})


@tool
async def confirm_and_render_materials(record_id: str, config: RunnableConfig = None) -> str:
    """确认当前的简历修改草案，正式写回飞书多维表格「AI改写JSON」并重新渲染/交付定制 PDF 和长图物料。

    何时用：用户对修改草案表达认可、确认或要求出物料（如「帮我生成吧」「确认生成」「就按这个出物料」「确认修改」「写回」）。
    重要：如果当前存在编辑暂存草案，直接确认并渲染；若未暂存草案，则基于多维表格现有内容重新出物料。
    """
    chat_id = _chat_id(config)
    if not chat_id:
        return _j({"error": "缺少会话标识"})
    from app.services import resume_edit_chat

    session = resume_edit_chat._get_edit_session(chat_id)
    if not session or session.get("record_id") != record_id:
        base = await resume_edit_chat._load_resume_base(record_id)
        if base is None:
            return _j({"error": "该岗位的简历内容为空或无法解析，无法渲染物料"})
        session = {
            "record_id": record_id,
            "stage": "confirm",
            "updated": json.dumps(base, ensure_ascii=False),
            "orig": json.dumps(base, ensure_ascii=False),
        }

    try:
        await resume_edit_chat._confirm_and_render(chat_id, session)
        return _j({
            "success": True,
            "record_id": record_id,
            "note": "已正式写回多维表格并重新生成交付了定制 PDF 简历与长图物料，已发送至聊天框。"
        })
    except Exception as e:
        logger.exception(f"[ChatAgent] 确认出物料失败: {e}")
        return _j({"error": f"物料渲染或发送失败: {e}"})


@tool
async def cancel_resume_edit(config: RunnableConfig = None) -> str:
    """放弃/取消当前的简历修改草案，丢弃暂存的修改并保持多维表格原样。

    何时用：用户明确表示「放弃修改」「取消修改」「算了不改了」。
    """
    chat_id = _chat_id(config)
    if not chat_id:
        return _j({"error": "缺少会话标识"})
    from app.services import resume_edit_chat

    had = resume_edit_chat.clear_edit_session(chat_id)
    return _j({"cancelled": True, "had_pending_session": had, "note": "已取消本次简历修改，多维表格保持原样不变。"})


@tool
async def update_follow_status(record_id: str, status: str, set_delivery_date: bool = False, config: RunnableConfig = None) -> str:  # noqa: ARG001  # LangChain 注入
    """更新单个岗位的跟进状态（写操作）。常用值：已投递 / 面试中 / 简历人工复核 / 已拒绝。

    何时用：用户明确表达了状态变更意图（如「投递完了」「标记为面试中」）。
    红线：只允许单条更新，绝不批量；用户未明确表达时绝不调用。
    set_delivery_date=True 仅在用户表示「已投递」时使用（同时记录投递时间）。
    """
    from app.core.config import settings
    from app.core.feishu_client import feishu_client

    fields: dict[str, Any] = {"跟进状态": status}
    if set_delivery_date:
        fields["投递日期"] = int(datetime.now().timestamp() * 1000)
    await feishu_client.update_record(settings.FEISHU_TABLE_ID_JOBS, record_id, fields)
    return _j({"updated": True, "record_id": record_id,
               "follow_status": status, "delivery_date_set": set_delivery_date})


@tool
async def start_evaluation(record_id: str, config: RunnableConfig = None) -> str:
    """对指定岗位发起 AI 评估流水线（初评+深评+简历改写+物料，约3~8分钟），进度卡实时发到聊天框。

    何时用：用户要求「评估这个岗位」。本工具立即返回，评估在后台执行；期间用 check_evaluation_progress 查进度。
    """
    chat_id = _chat_id(config)
    if not chat_id:
        return _j({"error": "缺少会话标识"})
    from app.automation import inflight_registry
    from app.services.job_entry_chat import _launch_single_job_pipeline

    if inflight_registry.has(record_id):
        return _j({"accepted": False, "reason": "该岗位已有评估在跑（进度卡在聊天框），可用 check_evaluation_progress 查询"})
    # 必须持有任务引用：事件循环对运行中 task 只持弱引用，裸 create_task 可能被 GC
    # 中途回收，用户看到「已启动」却永远没有进度（3~8 分钟长任务尤其危险）
    _eval_task = asyncio.create_task(_launch_single_job_pipeline(chat_id, record_id))
    _BACKGROUND_EVAL_TASKS.add(_eval_task)
    _eval_task.add_done_callback(_BACKGROUND_EVAL_TASKS.discard)
    return _j({"accepted": True, "note": "评估已后台启动（约3~8分钟），进度卡将实时更新；请告知用户留意聊天框"})


@tool
async def check_evaluation_progress(record_id: str, config: RunnableConfig = None) -> str:  # noqa: ARG001  # LangChain 注入
    """查询岗位评估流水线进度：未开始/评估中/已完成，附最新跟进状态与评级。

    何时用：用户问「评估好了吗」「进度怎么样」。
    """
    from app.automation import inflight_registry
    from app.core.config import settings
    from app.core.feishu_client import feishu_client

    inflight = inflight_registry.get(record_id)
    rec = await feishu_client.fetch_bitable_record_by_id(settings.FEISHU_TABLE_ID_JOBS, record_id)
    fields = ((rec or {}).get("fields", {}) or {}) if rec else {}
    stage = "评估中" if inflight else ("已完成" if _txt(fields.get("AI改写JSON")) else "未开始")
    return _j({
        "stage": stage,
        "elapsed_seconds": int(time.time() - float(inflight.get("started_epoch", 0))) if inflight else None,
        "materials_delivered": bool((inflight or {}).get("materials_delivered")),
        "follow_status": _txt(fields.get("跟进状态")),
        "grade": _txt(fields.get("综合评级 (A-F)")),
    })


@tool
async def check_table_hygiene(config: RunnableConfig = None) -> str:  # noqa: ARG001  # LangChain 注入
    """岗位表体检（只读）：统计「同公司+同岗位」重复分组与可归档数量、过期未动岗位积压量。

    何时用：用户问岗位表干不干净/有多少重复/想清理岗位表时。本工具绝不改数据；
    用户同意清理后，先复述清单再调用 archive_duplicate_jobs 执行。
    """
    from app.services import job_table_hygiene

    report = await job_table_hygiene.hygiene_report()
    return _j({
        "dedup": report["dedup"],
        "liveness": report["liveness"],
        "summary": job_table_hygiene.summarize_report(report),
    })


@tool
async def archive_duplicate_jobs(config: RunnableConfig = None) -> str:  # noqa: ARG001  # LangChain 注入
    """执行重复岗位归档：把「同公司+同岗位」重复记录里较旧较少的一条改为「已归档-重复」（保留最全最新的一条）。

    绝不物理删除，随时可恢复；进行中评估/已投递/白名单/会话引用的记录自动保护跳过。
    红线：必须先用 check_table_hygiene 出清单并展示给用户、用户明确同意后才能调用本工具；一次执行一批即可。
    """
    from app.services import job_table_hygiene

    result = await job_table_hygiene.execute_dedup(confirmed=True)
    if not result.get("executed"):
        return _j(result)
    return _j({"archived": result["archived"], "failed": result["failed"],
               "note": "归档完成（跟进状态=已归档-重复，未删除）。受保护记录已自动跳过，详情见返回明细",
               "results": result["results"][:30]})


@tool
async def start_liveness_check(platform: str = "", config: RunnableConfig = None) -> str:  # noqa: ARG001  # LangChain 注入
    """启动一批过期岗位的链接存活检测（后台跑，默认20条，条间休息20~60秒防风控；51job 平台不支持）。

    何时用：用户想清理过期/失效岗位，或问「哪些岗位链接失效了」并同意执行时。
    platform 可选 boss/zhilian/liepin（不填自动选积压最多的支持平台）。
    红线：需用户明确同意后才调用；一次只跑一批，绝不连续大批量。死链岗位会被标「已下架」（不删除）。
    """
    from app.services import job_table_hygiene

    result = await job_table_hygiene.start_liveness_batch(platform=platform)
    if not result.get("started"):
        return _j(result)
    return _j({**result, "note": result["note"] + "；死链岗位将标「已下架」（不删除）"})


@tool
async def check_liveness_progress(config: RunnableConfig = None) -> str:  # noqa: ARG001  # LangChain 注入
    """查询存活检测批次的实时进度：已检/在招/已下架/无法判定/是否熔断中止。"""
    from app.services import job_table_hygiene

    return _j(job_table_hygiene.liveness_progress())


@tool
async def review_duplicate_suspects(config: RunnableConfig = None) -> str:  # noqa: ARG001  # LangChain 注入
    """复核「疑似重复」待办（只读）——决策优先的三层漏斗：铁证真重复自动处理（一句话带过，不打扰用户）、
    AI 建议放行的列出理由等同意、仅边界条目（相似度<90%）附「本条 vs 母本」对比请用户拍板。

    何时用：用户问「疑似重复要怎么处理」「帮我复核那些重复的岗位」。
    汇报纪律：只转述 summary 里的决策内容（放行建议+边界对比），不要倾倒全量数据；
    用户点名放行哪几条后，用 approve_duplicate_suspects 执行（record_id 用返回里的完整 id）。
    """
    from app.services import job_table_hygiene

    report = await job_table_hygiene.review_duplicate_suspects()
    report["relay_instruction"] = (
        "只向用户转述 summary（决策摘要）；summary 已按「铁证一句话/放行建议/边界对比」组织。"
        "不要输出完整 items、不要重复相似度表格。用户放行时用 need_decision/suggest_approve 里的完整 record_id。")
    return _j(report)


@tool
async def approve_duplicate_suspects(record_ids: list[str], config: RunnableConfig = None) -> str:  # noqa: ARG001  # LangChain 注入
    """放行指定的疑似重复岗位（仅限用户在对话里明确点名的那些）：改回「新线索」+ 记入去重白名单，此后查重永不拦截。

    红线：只放行用户明确同意的条目，用 record_id 精确指定；用户没点名的一条都不动。
    """
    from app.services import job_table_hygiene

    return _j(await job_table_hygiene.approve_suspects([str(r) for r in record_ids]))


@tool
async def check_progress(task_id: str = "", config: RunnableConfig = None) -> str:  # noqa: ARG001  # LangChain 注入
    """查询后台任务进度（只读）：批量任务的状态/完成度，以及岗位评估的实时阶段。

    何时用：用户问「现在跑到哪了」「任务完成了吗」「进度怎么样」。task_id 留空时列出当前所有活跃任务概览。
    """
    from app.automation import inflight_registry
    from app.tasks.state import task_status

    result: dict[str, Any] = {}

    if task_id:
        st = task_status.get(task_id)
        if st:
            result["batch_task"] = {"task_id": task_id, **st}
        inflight = inflight_registry.get(task_id)
        if inflight:
            result["evaluation"] = {
                "record_id": task_id,
                "elapsed_seconds": int(time.time() - float(inflight.get("started_epoch", 0))),
                "materials_delivered": bool(inflight.get("materials_delivered")),
            }
        if not result:
            return _j({"error": f"任务 {task_id} 不存在或已结束", "hint": "可用 task_id 留空的方式列出当前活跃任务"})
        result["hint"] = "用一两句话转述进度，不要倾倒原始字段"
        return _j(result)

    batches = [
        {"task_id": tid, **st} for tid, st in task_status.items()
        if isinstance(st, dict) and st.get("status") not in ("done", "finished", "completed")
    ]
    if batches:
        result["batch_tasks"] = batches
    result["hint"] = (
        f"当前有 {len(batches)} 个批量任务在跑" if batches else "当前没有活跃的批量任务"
    )
    return _j(result)


@tool
async def query_dashboard(view: str = "overview", config: RunnableConfig = None) -> str:  # noqa: ARG001  # LangChain 注入
    """查询求职数据看板（只读）。view 可选: overview(核心指标总览) / funnel(漏斗转化) / platform(平台对比) / trend(趋势)。

    何时用：用户问「看看整体数据」「漏斗转化怎么样」「各平台对比」「最近趋势」。
    汇报纪律：把关键数字提炼成两三句话汇报，不要倾倒原始 JSON。
    """
    from app.api.routes.analytics_dashboard import (
        get_funnel,
        get_overview,
        get_platform_stats,
        get_trend,
    )

    view = (view or "overview").strip().lower()
    if view == "overview":
        data = await get_overview()
    elif view == "funnel":
        data = await get_funnel()
    elif view == "platform":
        data = await get_platform_stats()
    elif view == "trend":
        # 注意：get_trend 的默认值是 FastAPI Query 对象，进程内直接调用必须显式传参
        data = await get_trend(time_range="daily")
    else:
        return _j({"error": "view 必须是 overview/funnel/platform/trend 之一"})
    return _j({"view": view, "data": data,
               "hint": "提炼关键数字向用户汇报；数据为空时如实说明并建议先跑一轮抓取"})


@tool
async def send_report(period: str = "daily", config: RunnableConfig = None) -> str:  # noqa: ARG001  # LangChain 注入
    """生成并推送求职战报到飞书群。period 可选: daily(日报) / weekly(周报) / monthly(月报) / final(终报)。

    何时用：用户明确说「发日报/周报/月报/终报」「来一份战报」。战报会推送到「接收群 Chat ID」配置的群。
    红线：这是面向群的正式推送，用户没有明确要求时不要调用。
    """
    period = (period or "daily").strip().lower()
    if period == "daily":
        from app.services.report_feishu import send_daily_report
        await send_daily_report()
    elif period == "weekly":
        from app.services.report_feishu import send_weekly_report
        await send_weekly_report()
    elif period == "monthly":
        from app.services.report_feishu import send_monthly_report
        await send_monthly_report()
    elif period == "final":
        from app.services.report_feishu import send_final_report
        await send_final_report()
    else:
        return _j({"error": "period 必须是 daily/weekly/monthly/final 之一"})
    return _j({"sent": True, "period": period,
               "note": "战报卡片已推送到接收群，请简短告知用户战报已发出"})


# 全部工具统一挂载循环熔断守卫（重复调用根治层）
CHAT_TOOLS: list = [guard_tool_loop(t) for t in [
    locate_job, read_job_resume, query_company_intel, edit_resume_json,
    confirm_and_render_materials, cancel_resume_edit,
    update_follow_status, start_evaluation, check_evaluation_progress,
    check_table_hygiene, archive_duplicate_jobs,
    start_liveness_check, check_liveness_progress,
    review_duplicate_suspects, approve_duplicate_suspects,
    check_progress, query_dashboard, send_report,
]]

# ==========================================
# 工具元数据（前端「指令话术」速查的数据源，GET /api/chatops/tools 下发）
# 以后端为唯一真源：新增工具 = 实现 + 在这里补一行，前端无需改代码
# ==========================================
TOOL_META: dict[str, dict[str, Any]] = {
    # ---- 岗位与简历 ----
    "locate_job": {
        "category": "岗位与简历", "desc": "按公司名+岗位名定位岗位表中的记录",
        "phrases": ["帮我找一下 字节 的 后端 岗", "定位一下这家公司的岗位", "看看表里有没有这个岗位"],
    },
    "read_job_resume": {
        "category": "岗位与简历", "desc": "读取岗位全量画像（链接/薪资/评估/简历内容）",
        "phrases": ["把这个岗位的链接发我", "这个岗位评估里写了什么", "看看这个岗位的详情"],
    },
    "query_company_intel": {
        "category": "岗位与简历", "desc": "查询公司业务情报与近期动态（缓存优先，可联网搜索）",
        "phrases": ["查一下这家公司的背景", "这家公司最近有什么动态", "看看这家公司的AI布局"],
    },
    "edit_resume_json": {
        "category": "岗位与简历", "desc": "按自然语言指令修改定制简历（先出草案待确认）",
        "phrases": ["把这份简历往数据方向改一改", "突出一下我的大模型项目经验", "简历里少写点运维内容"],
    },
    "confirm_and_render_materials": {
        "category": "岗位与简历", "desc": "确认修改草案，正式写回并重新渲染 PDF/长图物料",
        "phrases": ["确认生成", "就按这个出物料", "可以了，写回吧"],
    },
    "cancel_resume_edit": {
        "category": "岗位与简历", "desc": "放弃当前简历修改草案，表格保持原样",
        "phrases": ["取消修改", "不改了", "放弃这次改动"],
    },
    "update_follow_status": {
        "category": "岗位与简历", "desc": "更新单个岗位的跟进状态（单条写操作）",
        "phrases": ["这条改成已投递", "标记为面试中", "这个岗位标记已拒绝"],
    },
    # ---- 评估与进度 ----
    "start_evaluation": {
        "category": "评估与进度", "desc": "对岗位发起 AI 评估流水线（后台跑，进度卡实时更新）",
        "phrases": ["评估一下这个岗位", "帮这个岗位跑一轮评估", "深度评估这家公司"],
    },
    "check_evaluation_progress": {
        "category": "评估与进度", "desc": "查询岗位评估进度（评估中/已完成/评级）",
        "phrases": ["评估好了吗", "评估进度怎么样", "跑到哪一步了"],
    },
    "check_progress": {
        "category": "评估与进度", "desc": "查询后台任务进度（批量任务/评估流水线）",
        "phrases": ["现在跑到哪了", "任务完成了吗", "看看当前进度"],
    },
    # ---- 表格维护 ----
    "check_table_hygiene": {
        "category": "表格维护", "desc": "岗位表体检：重复岗位、过期积压统计（只读）",
        "phrases": ["岗位表干不干净", "有多少重复岗位", "体检一下岗位表"],
    },
    "archive_duplicate_jobs": {
        "category": "表格维护", "desc": "归档重复岗位（先体检出清单、用户同意后执行）",
        "phrases": ["把重复的归档了吧", "清理一下重复岗位", "按刚才的清单归档"],
    },
    "start_liveness_check": {
        "category": "表格维护", "desc": "启动一批过期岗位的链接存活检测（后台跑）",
        "phrases": ["查查哪些岗位失效了", "检测一下链接存活", "把死链岗位找出来"],
    },
    "check_liveness_progress": {
        "category": "表格维护", "desc": "查询存活检测批次进度",
        "phrases": ["存活检测跑到哪了", "死链检查完了吗"],
    },
    "review_duplicate_suspects": {
        "category": "表格维护", "desc": "复核疑似重复岗位（只读，出放行建议与边界对比）",
        "phrases": ["复核一下疑似重复", "那些重复岗位怎么处理", "看看重复嫌疑清单"],
    },
    "approve_duplicate_suspects": {
        "category": "表格维护", "desc": "放行用户明确点名的疑似重复岗位（记入白名单）",
        "phrases": ["前两条放行", "这几条不是重复，放了吧", "把这条放出来"],
    },
    # ---- 数据与战报 ----
    "query_dashboard": {
        "category": "数据与战报", "desc": "数据看板：总览/漏斗/平台对比/趋势",
        "phrases": ["看看整体数据", "给我看漏斗转化", "各平台对比怎么样", "最近一周趋势如何"],
    },
    "send_report": {
        "category": "数据与战报", "desc": "生成并推送战报（日报/周报/月报/终报）到接收群",
        "phrases": ["发今天的日报", "生成本周周报", "出一份月报", "收工，发个终报"],
    },
}
