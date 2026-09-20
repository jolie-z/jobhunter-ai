"""AI 诊断官（自愈体系 L3）：对持续失败的投递岗位产出结构化诊断报告。

触发时机：岗位在失败台账里 failure_count ≥ DIAG_THRESHOLD（连续自动重试上限，
说明 L1 已放行过、L2 已修过仍失败——环境手段用尽，需要查明真正死因）。

信息源（全部只读）：
1. 后端日志尾部（kill -9 级别的原始 Traceback 都在这里，如 DrissionPage
   的 NO_SUCH_TAB / NoRectError——引擎返回值里看不到的真相）；
2. 飞书「自动投递失败日志」字段（引擎内部 _log_failure 写入的死因）；
3. 失败台账条目（错误文本/失败次数/自愈记录/岗位与平台信息）。

产出（JSON，存入失败台账 diagnosis 字段，前端失败卡「AI 诊断」按钮展示）：
- root_cause    人话死因（一句话）
- category      引擎缺陷 / 环境故障 / 物料问题 / 岗位问题 / 未知
- confidence    high / medium / low
- fix_hint      给老板的处理建议（重试能好/要人工/要改代码）
- ticket_md     修复工单（Markdown）——category=引擎缺陷 时生成，
                可直接粘给编码 agent 执行修复，实现「AI 发现 bug → AI 修 bug」闭环。

安全边界：诊断官只读日志与台账、只写诊断结果，绝不直接修改业务代码或投递配置；
修复动作永远等老板确认后由人工拉起编码 agent 执行（投递链路是真世界动作，不可全自动）。
"""

import asyncio
import json
import logging
import re
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# 连续失败达到该次数即触发自动诊断（与 L1 的 MAX_AUTO_RETRIES 对齐）
DIAG_THRESHOLD = 2

# 后端日志文件候选（取存在且最新修改的那个）
_LOG_CANDIDATES = [
    Path(__file__).resolve().parents[2] / "backend_uvicoin_reload.log",
    Path(__file__).resolve().parents[2] / "backend.log",
]

_LOG_TAIL_BYTES = 200_000  # 只读日志尾部 200KB，足够覆盖最近几次投递的完整 Traceback

_SYSTEM_PROMPT = (
    "你是招聘自动化系统的投递故障诊断官。根据给出的岗位投递失败信息（错误文本、"
    "浏览器日志片段、引擎内部失败日志），输出严格的 JSON 诊断报告，字段：\n"
    'root_cause: 一句话人话死因（中文，具体到环节，如"微聊发送前目标标签页已被关闭导致 NO_SUCH_TAB"）；\n'
    'category: 五选一 —— 引擎缺陷(代码bug)/环境故障(浏览器态或登录态)/物料问题(简历附件)/岗位问题(下架或链接失效)/未知；\n'
    'confidence: high/medium/low；\n'
    "fix_hint: 给运营者的处理建议（一句话，说明重试能否自愈还是需要人工/改代码）；\n"
    "ticket_md: 若 category 为引擎缺陷，生成给编码 agent 的修复工单（Markdown：现象/根因/涉及文件线索/验收标准），"
    "否则填空串。\n"
    "只输出 JSON 本体，不要 markdown 代码块包裹，不要多余解释。"
)


def _latest_log_file() -> Path:
    """取候选日志中最近被写入的那个；都不存在返回 None。"""
    existing = [p for p in _LOG_CANDIDATES if p.exists()]
    if not existing:
        return None
    return max(existing, key=lambda p: p.stat().st_mtime)


def _read_log_tail(max_bytes: int = _LOG_TAIL_BYTES) -> str:
    log_path = _latest_log_file()
    if not log_path:
        return ""
    try:
        size = log_path.stat().st_size
        with open(log_path, "rb") as f:
            if size > max_bytes:
                f.seek(size - max_bytes)
            raw = f.read()
        return raw.decode("utf-8", errors="ignore")
    except Exception as e:
        logger.warning(f"[DiagAgent] 读取日志失败: {e}")
        return ""


def _extract_relevant_log(log_text: str, platform: str = "", _job_name: str = "", max_chars: int = 6000) -> str:
    """从日志尾部抽取与本次失败相关的片段：以引擎报错行为锚点，向前带上下文。"""
    if not log_text:
        return ""
    anchors = []
    if platform:
        anchors.append(f"{platform}投递引擎")
    anchors += ["Traceback", "RuntimeError", "Error"]
    lines = log_text.splitlines()
    hits = []
    for i, line in enumerate(lines):
        if any(a in line for a in anchors):
            hits.append(i)
    if not hits:
        return log_text[-max_chars:]
    # 取最后一个锚点附近（锚点行 + 前后文）拼接
    last = hits[-1]
    start = max(0, last - 30)
    chunk = "\n".join(lines[start:last + 5])
    return chunk[-max_chars:]


def _parse_json_loose(raw: str) -> dict:
    """宽松解析 LLM 返回的 JSON（剥掉可能的代码块包裹）。"""
    text = (raw or "").strip()
    text = re.sub(r"^```(json)?|```$", "", text, flags=re.MULTILINE).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("LLM 返回中未找到 JSON 对象")
    return json.loads(text[start:end + 1])


def needs_diagnosis(failure: dict) -> bool:
    """是否需要（重新）诊断：连续失败达阈值且尚未有诊断，或失败次数比上次诊断时又多了。"""
    count = int((failure or {}).get("failure_count") or 0)
    if count < DIAG_THRESHOLD:
        return False
    diag = (failure or {}).get("diagnosis") or {}
    return not diag or int(diag.get("for_failure_count") or 0) < count


async def diagnose_failure(job_id: str) -> dict:
    """诊断指定岗位的持续失败，报告写入失败台账 diagnosis 字段并返回。

    任何异常都不抛出（诊断是旁路能力，失败只记日志）。
    """
    from app.automation import run_snapshot as _rs

    failure = (_rs.get_delivery_failures() or {}).get(str(job_id))
    if not failure:
        return {"status": "error", "message": "失败台账中不存在该岗位，无需诊断"}

    if not needs_diagnosis(failure):
        return {"status": "success", "data": failure.get("diagnosis"),
                "message": "已有诊断结果且失败次数未新增，直接复用"}

    from app.core.feishu_utils import extract_feishu_text as _txt
    from app.services.feishu_service import TABLE_ID, get_job_record_from_feishu

    engine_fail_log = ""
    try:
        rec = await asyncio.to_thread(get_job_record_from_feishu, str(job_id), TABLE_ID)
        if rec:
            engine_fail_log = _txt(rec.get("fields", {}).get("自动投递失败日志", ""))
    except Exception as e:
        logger.warning(f"[DiagAgent] 读取飞书失败日志异常: {e}")

    log_text = await asyncio.to_thread(_read_log_tail)
    log_excerpt = _extract_relevant_log(
        log_text, failure.get("platform") or "", failure.get("job_name") or "")

    user_prompt = (
        f"【岗位】{failure.get('company_name') or '未知公司'} - {failure.get('job_name') or '未知岗位'}"
        f"（平台: {failure.get('platform') or '未知'}）\n"
        f"【连续失败次数】{failure.get('failure_count')}\n"
        f"【最新错误文本】{failure.get('error') or '无'}\n"
        f"【已执行的自愈动作】{json.dumps(failure.get('heal_log') or [], ensure_ascii=False)}\n"
        f"【引擎内部失败日志(飞书)】{engine_fail_log or '无'}\n"
        f"【后端日志相关片段】\n{log_excerpt or '无'}"
    )

    diagnosis = {
        "root_cause": "LLM 诊断不可用，请查看后端日志人工排查",
        "category": "未知",
        "confidence": "low",
        "fix_hint": "建议查看后端日志中最后一个 Traceback 附近的上下文",
        "ticket_md": "",
    }
    try:
        from app.core.llm_client import get_openai_client
        from common.config import OPENAI_MODEL
        client = get_openai_client()
        if not client:
            raise RuntimeError("未配置 LLM API Key")
        response = await asyncio.to_thread(
            client.chat.completions.create,
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
        )
        raw = (response.choices[0].message.content or "").strip()
        parsed = _parse_json_loose(raw)
        diagnosis = {
            "root_cause": str(parsed.get("root_cause") or diagnosis["root_cause"])[:200],
            "category": str(parsed.get("category") or "未知")[:20],
            "confidence": str(parsed.get("confidence") or "low")[:10],
            "fix_hint": str(parsed.get("fix_hint") or "")[:300],
            "ticket_md": str(parsed.get("ticket_md") or "")[:4000],
        }
    except Exception as e:
        logger.warning(f"[DiagAgent] LLM 诊断失败: {e}")
        diagnosis["root_cause"] = f"LLM 诊断失败（{str(e)[:80]}），请人工查看后端日志"

    diagnosis["diagnosed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    diagnosis["for_failure_count"] = int(failure.get("failure_count") or 0)

    # 写回失败台账
    with _rs._lock:
        entry = _rs._delivery_failures.get(str(job_id))
        if entry is not None:
            entry["diagnosis"] = diagnosis
            _rs._save_to_db()

    return {"status": "success", "data": diagnosis}
