"""
自然语言定向修改简历 + 状态流转（已投递）。

流程：物料送达后用户可直接发修改指令（如"把XX段改成YY"）→
LLM 仅按指令定向修改 V2 JSON（禁止编造）→ 回显改动 → 确认后重渲染物料并回写附件 →
投递完成后回复「已投递」或点卡片按钮更新跟进状态。
"""

import asyncio
import difflib
import json
import logging
import re
import time
from datetime import datetime
from typing import Any

from app.core.config import BASE_DIR, settings
from app.core.feishu_messaging import (
    send_feishu_card,
    send_feishu_file,
    send_feishu_image,
    send_feishu_message,
)

logger = logging.getLogger(__name__)

# 跨消息会话状态（与聊天录入共用持久化机制）
from app.services.job_entry_chat import _LINK_TTL_SECONDS, _PendingStore  # noqa: E402

_EDIT_SESSION_PATH = BASE_DIR / "data" / "pending_resume_edit.json"
_LAST_DELIVERED_PATH = BASE_DIR / "data" / "last_delivered_job.json"
_PENDING_LOCATE_PATH = BASE_DIR / "data" / "pending_job_locate.json"
_EDIT_TARGET_PATH = BASE_DIR / "data" / "active_edit_target.json"
_PENDING_TARGET_CONFIRM_PATH = BASE_DIR / "data" / "pending_edit_target_confirm.json"

# 编辑会话：chat_id → {"record_id", "stage", "updated", "orig"}（JSON 字符串存入 store）
_edit_sessions = _PendingStore(_EDIT_SESSION_PATH, _LINK_TTL_SECONDS)
# 最近一次物料送达的岗位：chat_id → record_id（交付锚点，供"已投递"与上下文延续）
_last_delivered = _PendingStore(_LAST_DELIVERED_PATH, _LINK_TTL_SECONDS * 7)
_pending_locate = _PendingStore(_PENDING_LOCATE_PATH, _LINK_TTL_SECONDS)  # 岗位定位候选待点选
# 定位/点选绑定的编辑目标：独立于交付锚点——误定位不得反向污染「最近交付」上下文
_edit_target = _PendingStore(_EDIT_TARGET_PATH, _LINK_TTL_SECONDS)
# 原文一致性校验未通过时的反问：chat_id → {"record_id", "instruction"}，等用户确认
_pending_target_confirm = _PendingStore(_PENDING_TARGET_CONFIRM_PATH, _LINK_TTL_SECONDS)

_CONFIRM_WORDS = ("确认生成", "重新生成", "重新给我", "出新物料", "重新出", "生成新的")
_CANCEL_WORDS = ("取消修改", "放弃修改", "不改了")
_DELIVERED_WORDS = ("已投递", "投递完成", "投递完了")

_MODIFY_VERBS = ("改成", "改为", "调整为", "换成", "修改", "帮我改", "改一下", "调整一下")


def _set_edit_session(chat_id: str, session: dict[str, Any]) -> None:
    _edit_sessions[chat_id] = json.dumps(session, ensure_ascii=False)


def _get_edit_session(chat_id: str) -> dict[str, Any] | None:
    raw = _edit_sessions.get(chat_id)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def _pop_edit_session(chat_id: str) -> dict[str, Any] | None:
    raw = _edit_sessions.pop(chat_id, None)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def record_delivered_context(chat_id: str, record_id: str) -> None:
    """物料送达时登记交付锚点（供"已投递"与上下文延续）。值存 JSON 带时间戳，供双指针按新旧取舍。"""
    if record_id:
        _last_delivered[chat_id] = json.dumps({"record_id": record_id, "ts": time.time()})


def record_edit_target(chat_id: str, record_id: str) -> None:
    """定位/点选绑定编辑目标（独立指针：误定位不覆盖交付锚点）。"""
    if record_id:
        _edit_target[chat_id] = json.dumps({"record_id": record_id, "ts": time.time()})


def _read_ptr(store: "_PendingStore", chat_id: str) -> tuple[str, float]:
    """读指针值：新格式 JSON（record_id+ts）或旧格式裸 record_id。"""
    raw = store.get(chat_id)
    if not raw:
        return "", 0.0
    try:
        d = json.loads(raw)
        return str(d.get("record_id") or ""), float(d.get("ts") or 0)
    except (json.JSONDecodeError, TypeError, ValueError):
        return str(raw), 0.0


def _resolve_context_target(chat_id: str) -> str:
    """当前编辑目标 = 交付锚点与编辑目标两个指针中较新的一条（用户最近意图优先）。"""
    rid_delivered, ts_delivered = _read_ptr(_last_delivered, chat_id)
    rid_target, ts_target = _read_ptr(_edit_target, chat_id)
    if rid_target and (not rid_delivered or ts_target >= ts_delivered):
        return rid_target
    return rid_delivered


# ==========================================
# 意图判定（消息分发层拦截用）
# ==========================================
def should_intercept_delivered(chat_id: str, text: str) -> bool:
    """会话有最近交付岗位，且回复表达投递完成 → 更新跟进状态。"""
    if chat_id not in _last_delivered:
        return False
    t = (text or "").strip()
    return any(w in t for w in _DELIVERED_WORDS)


def should_intercept_edit(chat_id: str, text: str) -> bool:
    """编辑确认中的后续消息，或修改指令（有上下文直接改，无上下文进入岗位定位流程）。"""
    t = (text or "").strip()
    if chat_id in _pending_target_confirm:
        return True  # 反问确认阶段：任何回复都进编辑流消费（确认/取消/其余=新指令）
    if _get_edit_session(chat_id):
        return True  # 确认阶段：任何消息都进编辑流消费（确认/继续改/取消/其他=继续指令）
    if any(w in t for w in _DELIVERED_WORDS):
        return False  # 已投递优先级更高（上一拦截）
    return any(w in t for w in _MODIFY_VERBS)


# ==========================================
# LLM 定向修改（只改指令指定内容，禁止编造）
# ==========================================
_EDIT_SYSTEM_PROMPT = """你是一个简历定向编辑器。用户会给你一份结构化简历 JSON 和一条修改指令。
严格规则：
1. 只修改指令明确要求的内容，其余所有字段原样保留，一字不改。
2. 绝不允许编造新的经历、数据、公司、项目；改写只允许基于指令给出的新表述或对原文的措辞调整。
3. 保持 JSON 结构（所有 key、层级、数组长度）与输入一致，除非指令明确要求删除/新增条目。
4. description 数组内保持 markdown 加粗等既有格式风格。
5. 只输出修改后的完整 JSON，不得包含任何解释或 markdown 代码块标记。"""


async def _llm_edit_resume(resume_json: dict[str, Any], instruction: str) -> dict[str, Any]:
    from common.config import get_openai_client

    client = get_openai_client(caller="resume_edit")
    model = settings.OPENAI_MODEL or "gpt-4o"

    def _call() -> str:
        messages = [
            {"role": "system", "content": _EDIT_SYSTEM_PROMPT},
            {"role": "user", "content": f"【当前简历JSON】：\n{json.dumps(resume_json, ensure_ascii=False)}\n\n【修改指令】：\n{instruction}"},
        ]
        try:
            resp = client.chat.completions.create(model=model, messages=messages, temperature=0.1,
                                                  response_format={"type": "json_object"})
        except Exception:
            resp = client.chat.completions.create(model=model, messages=messages, temperature=0.1)
        return (resp.choices[0].message.content or "").strip()

    raw = await asyncio.to_thread(_call)
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r'^```(?:json)?\s*', '', raw).rstrip('`').strip()
    edited = json.loads(raw)
    if not isinstance(edited, dict) or not set(resume_json.keys()).issubset(set(edited.keys())):
        raise ValueError("LLM 返回的简历 JSON 结构异常")
    return edited


_KEY_LABELS = {
    "summary": "个人总结", "workExperience": "工作经历", "personalProjects": "项目经历",
    "education": "教育背景", "additional": "专业技能", "personalInfo": "个人信息",
}


def _diff_summary(orig: dict[str, Any], updated: dict[str, Any], max_len: int = 90) -> str:
    """模块级改动回显：中文模块名 + 文本字段 原文→新文 摘要，列表字段标注条目变化。"""
    titles = updated.get("moduleTitles") if isinstance(updated.get("moduleTitles"), dict) else {}

    def _label(key: str) -> str:
        return titles.get(key) or _KEY_LABELS.get(key) or key

    lines = []
    for key, old_val in orig.items():
        new_val = updated.get(key)
        if new_val == old_val:
            continue
        label = _label(key)
        if isinstance(old_val, str) and isinstance(new_val, str):
            lines.append(f"• {label}：{_brief(old_val, max_len)} → {_brief(new_val, max_len)}")
        elif isinstance(old_val, list) and isinstance(new_val, list):
            lines.append(f"• {label}：{len(old_val)} 条 → {len(new_val)} 条（内容已按指令更新）")
        else:
            lines.append(f"• {label}：已更新")
    for key in updated:
        if key not in orig:
            lines.append(f"• 新增模块 {_label(key)}")
    return "\n".join(lines) or "（无实质改动）"


def _brief(v: str, max_len: int) -> str:
    v = v.replace("\n", " ").strip()
    return v[:max_len] + "…" if len(v) > max_len else v


# ==========================================
# 岗位定位（公司名 + 岗位名自然语言 → 候选）
# ==========================================
def _norm(s: Any) -> str:
    return re.sub(r'[\s（）()\[\]【】·、，,。．\-—_/\\]+', '', str(s or '')).lower()


# LLM/技术品牌词：指令里「列举模型名」（如 支持 GPT/claude/deepseek/qwen/glm）不构成公司名定位信号——
# 真实事故：改简历指令里提到 deepseek 模型，被当成 DeepSeek 公司岗位误定位。
# 品牌词紧跟求职语境词时保留（如 "deepseek公司""deepseek的岗位"），那是在指名公司。
_BRAND_WORDS = (
    "chatglm", "deepseek", "moonshot", "qwen", "claude", "gemini", "openai",
    "gpt", "glm", "llama", "kimi", "doubao", "minimax", "ernie",
    "通义千问", "通义", "千问", "文心一言", "文心", "豆包", "智谱", "百川", "混元", "零一万物",
)
_EMPLOYMENT_CTX = ("岗位", "公司", "招聘", "职位", "offer", "面试", "jd")


def _strip_stray_brand_words(text: str) -> str:
    """移除「模型列举」语境下的品牌词；已规范化（去分隔符+小写）。"""
    t = _norm(text)
    for b in sorted((_norm(x) for x in _BRAND_WORDS if x), key=len, reverse=True):
        t = re.sub(rf"{re.escape(b)}(?!\s*的?\s*(?:{'|'.join(_EMPLOYMENT_CTX)}))", "、", t)
    return t


_GENERIC_COMPANY_SUFFIXES = ("有限公司", "责任公司", "股份有限公司", "集团", "科技", "网络", "信息", "发展", "技术", "分公司")


def _clean_company_core(name: str) -> str:
    n = _norm(name)
    for s in _GENERIC_COMPANY_SUFFIXES:
        n = n.replace(_norm(s), "")
    return n.strip() or _norm(name)


def _contain_score(short: str, long_: str) -> float:
    """short 在 long 中的匹配度：完整包含=1.0，否则按最长公共子串占比（下限保底 2 字符）。"""
    if not short:
        return 0.0
    if short in long_:
        return 1.0
    m = difflib.SequenceMatcher(None, short, long_).find_longest_match(0, len(short), 0, len(long_))
    # 至少匹配 3 个字符或占短串一半以上才计分，避免单个字/通用后缀虚高
    if m.size < 3 and (len(short) > 3 or m.size < 2):
        return 0.0
    return min(1.0, m.size / max(3.0, min(len(short), 6.0)))


def _score_job(msg_norm: str, company: str, title: str) -> float:
    c_core = _clean_company_core(company)
    c_score = max(_contain_score(_norm(company), msg_norm), _contain_score(c_core, msg_norm) * 1.1)
    c_score = min(1.0, c_score)
    t_score = _contain_score(_norm(title), msg_norm)
    return 0.6 * c_score + 0.4 * t_score


async def find_job_candidates(query_text: str, top_n: int = 5) -> list[dict[str, Any]]:
    """按整条消息对公司名+岗位名打分，返回候选（≥0.5 分，按分数降序，最多 top_n）。"""
    from app.jobs import service as jobs_service

    jobs = await jobs_service.fetch_and_clean_all_jobs()
    msg_norm = _strip_stray_brand_words(query_text)
    scored = []
    has_strong_company = False

    for j in jobs:
        c_name = j.get("company_name", "")
        t_name = j.get("job_name", "")
        c_core = _clean_company_core(c_name)

        c_score = max(_contain_score(_norm(c_name), msg_norm), _contain_score(c_core, msg_norm) * 1.1)
        c_score = min(1.0, c_score)
        t_score = _contain_score(_norm(t_name), msg_norm)

        # 至少一路强信号（公司或岗位独立匹配过半）
        if max(c_score, t_score) < 0.5:
            continue

        if c_score >= 0.8:
            has_strong_company = True

        score = 0.6 * c_score + 0.4 * t_score
        if score >= 0.25:
            status = str(j.get("follow_status") or "").strip()
            salary = str(j.get("salary") or "").strip()
            city = str(j.get("city") or "").strip()
            platform = str(j.get("platform") or "").strip()
            grade = str(j.get("grade") or "").strip()
            scored.append({
                "record_id": j.get("record_id"),
                "company": c_name,
                "title": t_name,
                "status": status or "新线索",
                "salary": salary,
                "city": city,
                "platform": platform,
                "grade": grade,
                "c_score": round(c_score, 2),
                "t_score": round(t_score, 2),
                "score": round(score, 2),
            })

    scored.sort(key=lambda x: x["score"], reverse=True)

    # 如果有明确的公司强匹配项，过滤掉完全不同公司的低相关项
    if has_strong_company:
        scored = [s for s in scored if s["c_score"] >= 0.4]

    # 相对截断：存在完全匹配时，明显更弱的候选剔除
    if scored:
        cutoff = scored[0]["score"] * 0.75
        scored = [s for s in scored if s["score"] >= cutoff]

    return scored[:top_n]


def build_candidates_card(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """候选岗位选择卡：每个候选一行结构化卡片（展示公司/岗位/薪资/地点/状态/平台），配独立交互按钮。"""
    _STATUS_SHORT = {"简历人工复核": "人工复核", "海投人工复核": "海投复核"}

    elements: list[dict[str, Any]] = []

    for i, c in enumerate(candidates):
        company = c.get("company", "未知公司")
        title = c.get("title", "未知岗位")
        salary = c.get("salary") or "面议"
        city = c.get("city") or "全国"
        raw_status = c.get("status", "")
        status = _STATUS_SHORT.get(raw_status, raw_status) or "新线索"
        platform = c.get("platform") or ""
        grade = c.get("grade") or ""

        # 拼接标签元信息
        meta_items = [f"💰 {salary}", f"📍 {city}"]
        if platform:
            meta_items.append(f"🏢 {platform}")
        if grade:
            meta_items.append(f"📊 评级 {grade}")
        meta_items.append(f"🏷️ {status}")
        meta_line = " ｜ ".join(meta_items)

        item_md = f"**{i+1}. {company}** · {title}\n<font color='grey'>{meta_line}</font>"
        btn_label = f"👉 选第 {i+1} 个" if len(candidates) > 1 else "👉 选择此岗位"

        div_element = {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": item_md,
            },
            "extra": {
                "tag": "button",
                "text": {
                    "tag": "plain_text",
                    "content": btn_label,
                },
                "type": "primary" if i == 0 else "default",
                "value": {
                    "action": "select_job",
                    "record_id": c.get("record_id"),
                },
            },
        }
        elements.append(div_element)
        if i < len(candidates) - 1:
            elements.append({"tag": "hr"})

    elements.append({
        "tag": "note",
        "elements": [{
            "tag": "plain_text",
            "content": "💡 点击对应「选择」按钮即可选定目标岗位并继续（如改简历、查详情、发起评估等）。",
        }],
    })

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": "blue",
            "title": {"tag": "plain_text", "content": f"🔍 找到 {len(candidates)} 个匹配岗位，请选择："},
        },
        "elements": elements,
    }


# 显式定位触发词（用户主动要求找岗位/切换岗位）
_LOCATE_PHRASES = ("找到这个岗位", "找这个岗位", "岗位是", "找岗位", "定位岗位", "帮我找到")


def should_intercept_locate(_chat_id: str, text: str) -> bool:
    t = (text or "").strip()
    return any(w in t for w in _LOCATE_PHRASES)


async def handle_locate(chat_id: str, text: str) -> None:
    """显式定位：找岗位 → 单命中直接绑定，多命中推候选卡。"""
    candidates = await find_job_candidates(text)
    if not candidates:
        await send_feishu_message(
            chat_id,
            "🔍 没有在岗位表找到匹配的岗位。请用「公司名 + 岗位名」再试（如：唯品会 AI产品运营）。",
            "chat_id",
        )
        return
    if len(candidates) == 1:
        cand = candidates[0]
        record_edit_target(chat_id, cand["record_id"])
        from app.services.chat_agent.card_builder import build_job_selected_card

        card = build_job_selected_card(
            {
                "company": cand.get("company", "该公司"),
                "title": cand.get("title", "该岗位"),
                "salary": cand.get("salary", "面议"),
                "city": cand.get("city", "全国"),
                "status": cand.get("status", "新线索"),
                "platform": cand.get("platform", ""),
                "grade": cand.get("grade", ""),
            },
            record_id=cand["record_id"],
        )
        fallback = f"🎯 已定位岗位：{cand['company']} · {cand['title']}\n状态：{cand.get('status', '新线索')}"
        from app.core.feishu_messaging import send_feishu_card_with_fallback
        await send_feishu_card_with_fallback(chat_id, card, fallback_text=fallback)
        return
    _pending_locate[chat_id] = json.dumps({"candidates": candidates, "instruction": None}, ensure_ascii=False)
    await send_feishu_card(chat_id, build_candidates_card(candidates))


async def handle_candidate_selected(chat_id: str, record_id: str) -> None:
    """用户点选候选岗位：绑定上下文；若定位前带修改指令则立即执行。"""
    raw = _pending_locate.pop(chat_id, None)
    instruction = None
    if raw:
        try:
            instruction = (json.loads(raw) or {}).get("instruction")
        except (json.JSONDecodeError, TypeError):
            instruction = None

    record_edit_target(chat_id, record_id)

    from app.core.feishu_client import feishu_client

    rec = await feishu_client.fetch_bitable_record_by_id(settings.FEISHU_TABLE_ID_JOBS, record_id)
    fields = (rec or {}).get("fields", {}) or {}

    def _txt(v: Any) -> str:
        if isinstance(v, str):
            return v.strip()
        if isinstance(v, list):
            return "".join(x.get("text", "") for x in v if isinstance(x, dict)).strip()
        return str(v or "").strip()

    company = _txt(fields.get("公司名称")) or "该公司"
    job = _txt(fields.get("岗位名称")) or "该岗位"
    salary = _txt(fields.get("薪资")) or "面议"
    city = _txt(fields.get("城市")) or "全国"
    status = _txt(fields.get("跟进状态")) or "新线索"

    if instruction:
        await send_feishu_message(chat_id, f"🎯 已锁定岗位：{company} · {job}，正在执行你的修改指令…", "chat_id")
        # 用户已点选确认：带 confirmed_target 直接执行，跳过定位与原文一致性反问
        await handle_edit_message(chat_id, instruction, confirmed_target=record_id)
        return

    from app.services.chat_agent.card_builder import build_job_selected_card

    card = build_job_selected_card(
        {
            "company": company,
            "title": job,
            "salary": salary,
            "city": city,
            "status": status,
            "platform": _txt(fields.get("招聘平台")),
            "grade": _txt(fields.get("综合评级 (A-F)")),
        },
        record_id=record_id,
    )
    fallback = (
        f"🎯 已选定目标岗位：**{company} · {job}**\n"
        f"💰 薪资：{salary} ｜ 📍 城市：{city} ｜ 🏷️ 状态：{status}\n"
    )
    from app.core.feishu_messaging import send_feishu_card_with_fallback
    await send_feishu_card_with_fallback(chat_id, card, fallback_text=fallback)


# ==========================================
# 消息处理入口
# ==========================================
async def handle_delivered_reply(chat_id: str, _text: str) -> None:
    record_id, _ = _read_ptr(_last_delivered, chat_id)
    if not record_id:
        return
    await mark_delivered_record(chat_id, record_id)


async def _merge_privacy(parsed: dict[str, Any]) -> None:
    """从简历库「结构化数据」回填个人隐私（改写内容不含个人信息，渲染前必须合并）。"""
    from app.core.feishu_client import feishu_client
    from app.services.feishu_service import get_active_resume_record_id

    rid = await asyncio.to_thread(get_active_resume_record_id)
    if not rid:
        return
    orig = await feishu_client.get_record(settings.FEISHU_TABLE_ID_RESUMES, rid)
    raw_s = (orig or {}).get("fields", {}).get("结构化数据", "")
    if isinstance(raw_s, list):
        raw_s = "".join(x.get("text", "") for x in raw_s if isinstance(x, dict))
    if raw_s:
        parsed.setdefault("personalInfo", {}).update(json.loads(raw_s).get("personalInfo") or {})


async def mark_delivered_record(chat_id: str, record_id: str) -> None:
    """跟进状态 → 已投递，并记录投递日期。"""
    from app.core.feishu_client import feishu_client

    await feishu_client.update_record(settings.FEISHU_TABLE_ID_JOBS, record_id, {
        "跟进状态": "已投递",
        # 多维表格日期字段要求毫秒时间戳（读取端 feishu_service 按 int(ts)/1000 解析），字符串会 DatetimeFieldConvFail
        "投递日期": int(datetime.now().timestamp() * 1000),
    })
    logger.info(f"[简历编辑] 跟进状态已更新为已投递 | record_id={record_id}")
    await send_feishu_message(
        chat_id,
        "✅ 跟进状态已更新为「已投递」，投递日期已记录到多维表格。祝面试顺利！🎯",
        "chat_id",
    )


_CONFIRM_REPLY_WORDS = _CONFIRM_WORDS + ("是", "是的", "对", "好的", "嗯", "确认", "确认执行")
# 「A 改为 B」式指令的转向词：A 部分作为原文锚点做一致性校验
_TURN_WORDS = ("改为", "改成", "换成", "调整为", "改作")


def _instruction_source_fragment(instruction: str) -> str:
    """取指令中「改为/改成…」之前的原文引用部分（锚点），无转向词返回空。"""
    idx = min((i for i in (instruction.find(w) for w in _TURN_WORDS) if i >= 0), default=-1)
    return instruction[:idx] if idx > 0 else ""


def _squash(s: Any) -> str:
    """去全部标点/空白并小写（CJK 属于 \\w，会保留），用于跨标点差异的文本比对。"""
    return re.sub(r"[\W_]+", "", str(s or "")).lower()


def _fragment_in_resume(fragment: str, resume_text: str, min_match: int = 6) -> bool:
    """原文锚点能否在简历中找到（去标点后最长公共子串 ≥ min_match）。锚点太短不构成校验依据，放行。"""
    a, b = _squash(fragment), _squash(resume_text)
    if len(a) < min_match:
        return True
    m = difflib.SequenceMatcher(None, a, b).find_longest_match(0, len(a), 0, len(b))
    return m.size >= min_match


async def handle_edit_message(chat_id: str, text: str, confirmed_target: str | None = None) -> None:
    """编辑流统一入口：待确认岗位 / 确认生成 / 取消 / 新修改指令（含多轮迭代）。

    confirmed_target：用户已通过候选点选/显式确认的岗位——跳过上下文解析与原文一致性反问，直接执行。
    """
    t = (text or "").strip()

    # 反问确认阶段（原文一致性校验未通过）：「确认」按原岗位执行；取消放弃；其余当新指令重新解析
    raw = _pending_target_confirm.pop(chat_id, None)
    if raw:
        try:
            pend = json.loads(raw) or {}
        except (json.JSONDecodeError, TypeError):
            pend = {}
        if t in _CANCEL_WORDS:
            await send_feishu_message(chat_id, "好的，本次修改已取消，多维表格保持原样。", "chat_id")
            return
        if t in _CONFIRM_REPLY_WORDS and pend.get("record_id"):
            await _edit_on_record(chat_id, str(pend["record_id"]), str(pend.get("instruction") or t),
                                  skip_target_check=True)
            return
        # 其余回复视为新指令：重新走目标解析（不 return）

    session = _get_edit_session(chat_id)

    if session:
        if t in _CANCEL_WORDS:
            _edit_sessions.pop(chat_id, None)
            await send_feishu_message(chat_id, "好的，本次修改已取消，多维表格保持原样。", "chat_id")
            return
        if any(w in t for w in _CONFIRM_WORDS):
            await _confirm_and_render(chat_id, session)
            return
        # 其余文本 = 在已改结果上继续迭代
        base = json.loads(session["updated"])
        record_id = session["record_id"]
        await _apply_instruction(chat_id, record_id, base, t)
        return

    # 新修改指令：目标 = 用户显式确认的岗位 > 双指针较新的上下文 > 定位反问（单命中也不直连，防误定位改错简历）
    record_id = confirmed_target or _resolve_context_target(chat_id)
    if not record_id:
        candidates = await find_job_candidates(t)
        if not candidates:
            await send_feishu_message(
                chat_id,
                "🔍 没有在岗位表找到匹配的岗位，本次修改未执行。\n请带上「公司名 + 岗位名」再发一次（如：唯品会 AI产品运营，把个人总结改成…）。",
                "chat_id",
            )
            return
        _pending_locate[chat_id] = json.dumps({"candidates": candidates, "instruction": t}, ensure_ascii=False)
        await send_feishu_card(chat_id, build_candidates_card(candidates))
        await send_feishu_message(
            chat_id,
            f"🎯 您要修改哪个岗位的简历？找到 {len(candidates)} 个匹配，点选确认后我立即执行你的修改指令。",
            "chat_id",
        )
        return

    await _edit_on_record(chat_id, record_id, t, skip_target_check=bool(confirmed_target))


async def _load_resume_base(record_id: str) -> dict[str, Any] | None:
    """读岗位的 AI改写JSON 并解析为 V2 dict（旧格式 markdown 现场升级+回写）。失败返回 None。"""
    from app.core.feishu_client import feishu_client

    rec = await feishu_client.fetch_bitable_record_by_id(settings.FEISHU_TABLE_ID_JOBS, record_id)
    fields = (rec or {}).get("fields", {}) or {}
    content = fields.get("AI改写JSON", "")
    if isinstance(content, list):
        content = "".join(x.get("text", "") for x in content if isinstance(x, dict))
    content = (content or "").strip()
    base = None
    if content.startswith("{"):
        try:
            base = json.loads(content)
        except json.JSONDecodeError:
            base = None
    if base is None and content and not content.lstrip().startswith("❌"):
        # 🌟 旧记录为 markdown：现场升级为 V2 JSON（含隐私合并）并回写字段，之后直接读结构化
        try:
            from ai_agents.markdown_to_json import parse_markdown_to_json

            base = await asyncio.to_thread(parse_markdown_to_json, content)
            await _merge_privacy(base)
            await feishu_client.update_record(settings.FEISHU_TABLE_ID_JOBS, record_id,
                                              {"AI改写JSON": json.dumps(base, ensure_ascii=False)})
            logger.info(f"[简历编辑] 旧记录已升级为 V2 JSON | record_id={record_id}")
        except Exception as e:
            base = None
            logger.warning(f"[简历编辑] 旧记录升级失败: {e}")
    return base


async def _edit_on_record(chat_id: str, record_id: str, instruction: str, skip_target_check: bool = False) -> None:
    """按已定岗位执行修改指令：读简历 → （旧格式现场升级）→ 原文一致性校验 → LLM 定向修改。"""
    base = await _load_resume_base(record_id)
    if base is None:
        await send_feishu_message(
            chat_id,
            "⚠️ 该岗位的简历内容无法解析为结构化格式。请重新走一次评估，或到网页定制面板手动编辑。",
            "chat_id",
        )
        return

    # 原文一致性校验：上下文岗位的简历里找不到指令引用的原文 → 反问确认（防上下文过期/口误指错岗位）
    if not skip_target_check:
        anchor = _instruction_source_fragment(instruction)
        if anchor and not _fragment_in_resume(anchor, json.dumps(base, ensure_ascii=False)):
            _pending_target_confirm[chat_id] = json.dumps(
                {"record_id": record_id, "instruction": instruction}, ensure_ascii=False)
            await send_feishu_message(
                chat_id,
                f"⚠️ 在当前岗位的简历里没找到你要改的原文「{_brief(anchor, 30)}」。\n"
                "回复「确认」就按当前岗位执行；要改别的岗位，请带上「公司名 + 岗位名」重新发指令。",
                "chat_id",
            )
            return

    await _apply_instruction(chat_id, record_id, base, instruction)


async def _apply_instruction(chat_id: str, record_id: str, base: dict[str, Any], instruction: str) -> None:
    await send_feishu_message(chat_id, "✏️ 正在按你的指令修改简历内容…", "chat_id")
    try:
        edited = await _llm_edit_resume(base, instruction)
    except Exception as e:
        logger.exception(f"[简历编辑] LLM 定向修改失败 | record_id={record_id}: {e}")
        await send_feishu_message(chat_id, f"❌ 修改失败：{e}\n可换一种表述重试。", "chat_id")
        return

    diff = _diff_summary(base, edited)
    _set_edit_session(chat_id, {
        "record_id": record_id,
        "stage": "confirm",
        "updated": json.dumps(edited, ensure_ascii=False),
        "orig": json.dumps(base, ensure_ascii=False),
    })
    await send_feishu_message(
        chat_id,
        f"📝 已按指令修改，改动如下：\n{diff}\n\n"
        "回复「确认生成」重新出 PDF/图片物料；继续描述修改可继续迭代；回复「取消修改」放弃。",
        "chat_id",
    )


async def _confirm_and_render(chat_id: str, session: dict[str, Any]) -> None:
    """确认生成：回写 AI改写JSON → 重渲染物料 → 回写附件 → 发聊天框 → 引导已投递。"""
    import re as _re
    import tempfile
    from pathlib import Path as _Path

    from app.automation.materials import _render_custom_resume_materials
    from app.core import feishu_utils
    from app.core.feishu_client import feishu_client
    from app.core.feishu_messaging import upload_file_to_feishu, upload_image_to_feishu

    record_id = session["record_id"]
    edited = json.loads(session["updated"])
    # 编辑会话必须等「渲染+回写」全部成功后再出栈：先 pop 的话，渲染一旦失败，
    # 用户确认过的多轮修改稿不可恢复，且「稍后重试」会拿表里的旧 JSON 覆盖并假报成功。

    await send_feishu_message(chat_id, "🛠️ 已确认修改，正在重新渲染物料（约 1~2 分钟）…", "chat_id")

    # 隐私合并（与正式渲染链一致：改写内容不含个人信息）
    try:
        await _merge_privacy(edited)
    except Exception as merge_err:
        logger.warning(f"[简历编辑] 隐私合并失败（按改写原文渲染）: {merge_err}")

    # 取公司/岗位命名物料
    rec = await feishu_client.fetch_bitable_record_by_id(settings.FEISHU_TABLE_ID_JOBS, record_id)
    fields = (rec or {}).get("fields", {}) or {}

    def _txt(v: Any) -> str:
        if isinstance(v, str):
            return v.strip()
        if isinstance(v, list):
            return "".join(x.get("text", "") for x in v if isinstance(x, dict)).strip()
        return str(v or "").strip()

    company = _txt(fields.get("公司名称")) or "未知公司"
    job = _txt(fields.get("岗位名称")) or "未知岗位"
    cleaned = _re.sub(r'[\/\\:\*\?"<>\|\s]+', '_', f"{company}_{job}").strip("_") or "定制简历"

    mats = await _render_custom_resume_materials(edited, cleaned)
    if not mats:
        # 会话仍保留（未 pop），此时重试「确认生成」是真实有效的
        await send_feishu_message(
            chat_id,
            "❌ 物料渲染失败，你的修改稿仍保留未丢。请稍后重新发送「确认生成」重试。",
            "chat_id",
        )
        return

    # 回写：结构化内容 + 新附件
    await feishu_client.update_record(settings.FEISHU_TABLE_ID_JOBS, record_id, {
        "AI改写JSON": json.dumps(edited, ensure_ascii=False),
        "PDF备份": [{"file_token": mats["pdf_token"], "name": f"{mats['name']}.pdf"}],
        "图片保存": [{"file_token": mats["img_token"], "name": f"{mats['name']}-长图.jpg"}],
    })
    _edit_sessions.pop(chat_id, None)  # 回写成功（不可回退点），编辑会话才允许出栈

    # 发聊天框：逐个统计真实送达结果，失败如实汇报，绝不假报成功
    sent_names: list[str] = []
    failed_names: list[str] = []
    for token, is_img, fname in ((mats["pdf_token"], False, f"{mats['name']}.pdf"),
                                 (mats["img_token"], True, f"{mats['name']}-长图.jpg")):
        tmp = ""
        try:
            with tempfile.NamedTemporaryFile(suffix=".pdf" if not is_img else ".jpg", delete=False) as f:
                tmp = f.name
            ok = await asyncio.to_thread(feishu_utils.download_feishu_file, token, tmp)
            if not ok:
                failed_names.append(fname)
                continue
            data = await asyncio.to_thread(_Path(tmp).read_bytes)
            if is_img:
                sent = bool(await send_feishu_image(chat_id, await upload_image_to_feishu(data)))
            else:
                sent = bool(await send_feishu_file(chat_id, await upload_file_to_feishu(data, fname)))
            (sent_names if sent else failed_names).append(fname)
        except Exception as e:
            logger.warning(f"[简历编辑] 新物料发送失败 {fname}: {e}")
            failed_names.append(fname)
        finally:
            if tmp:
                _Path(tmp).unlink(missing_ok=True)

    logger.info(f"[简历编辑] 物料重渲染完成并回写 | record_id={record_id} | sent={sent_names} failed={failed_names}")
    if failed_names:
        await send_feishu_message(
            chat_id,
            f"⚠️ 新版物料已回写多维表格，但聊天框发送失败 {len(failed_names)} 份（{'、'.join(failed_names)}），"
            "可在表格附件列下载。继续修改可直接发指令；投递完成后回复「已投递」。",
            "chat_id",
        )
    else:
        await send_feishu_message(
            chat_id,
            "✅ 新版物料已生成并发送（多维表格附件已同步更新）。\n"
            "继续修改可直接发指令；投递完成后回复「已投递」，我会帮你更新跟进状态。",
            "chat_id",
        )


def clear_edit_session(chat_id: str) -> bool:
    """用户转投其他话题时静默丢弃未确认的编辑会话（落盘同步）。"""
    return _edit_sessions.pop(chat_id, None) is not None


def build_delivered_card(record_id: str) -> dict[str, Any]:
    """物料交付后的状态卡片：满意投递后一键更新跟进状态。"""
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": "green",
            "title": {"tag": "plain_text", "content": "📮 投递完成了吗？"},
        },
        "elements": [
            {
                "tag": "note",
                "elements": [{
                    "tag": "plain_text",
                    "content": "💡 想改简历内容？直接发修改指令（如：把个人总结第二段改成…），确认后我重新出物料。投递完成后点下方按钮更新状态。",
                }],
            },
            {
                "tag": "action",
                "actions": [{
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "📮 已投递，更新状态"},
                    "type": "primary",
                    "value": {"action": "mark_delivered", "record_id": record_id},
                }],
            },
        ],
    }
