"""评估流水线的聊天反馈域：进度卡（单卡 PATCH）+ 单岗位启动 + 中断恢复执行器。

从 job_entry_chat.py 拆出（模块化瘦身 2/2）；上游入口（确认词拦截/卡片按钮分发）
留在门面，经 re-export 或函数内懒导入调用本模块。
依赖方向: 本模块 → materials_delivery → eval_report（单向，无环）。
"""
import logging
import os
import time
from typing import Any

from app.automation import inflight_registry
from app.core.config import settings
from app.core.feishu_messaging import (
    send_feishu_card,
    send_feishu_message,
    update_feishu_card,
)
from app.services.materials_delivery import _deliver_materials_to_chat

logger = logging.getLogger(__name__)


_inflight_pipelines: set = set()


async def _launch_single_job_pipeline(chat_id: str, record_id: str) -> None:
    """触发单岗位 LangGraph 流水线：跳过清洗直跑评估/改写，stop_at_review=True 保证绝不自动投递。"""
    if record_id in _inflight_pipelines:
        await send_feishu_message(chat_id, "⏳ 这个岗位的评估正在进行中，跑完会自动送达物料，稍等～", "chat_id")
        return
    if inflight_registry.has(record_id):
        await send_feishu_message(
            chat_id,
            "⏳ 检测到该岗位有一次未完成的评估（可能因服务重启中断），正在自动恢复，跑完会送达物料；如长时间无进展可稍后再点。",
            "chat_id",
        )
        return
    _inflight_pipelines.add(record_id)
    try:
        await _run_pipeline_with_feedback(chat_id, record_id)
    finally:
        _inflight_pipelines.discard(record_id)


# 进度卡阶段（key → 展示名）；状态: pending ⏳ / running 🔄 / done ✅
_PROGRESS_STAGES = (
    ("eval", "AI 初评 + 深度评估"),
    ("rewrite", "简历改写 & 打招呼语"),
    ("materials", "物料渲染与交付"),
)


def build_progress_card(
    company: str,
    job: str,
    stages: dict[str, str],
    grade: str = "",
    elapsed_seconds: int = 0,
    final_note: str = "",
    failed_reason: str = "",
) -> dict[str, Any]:
    """评估进度卡：单卡原地更新（PATCH），替代逐条文字刷屏。"""

    failed = bool(failed_reason)
    # 完成标志 = 物料交付完成（D/F 级早停不改写时，改写阶段保持 ⏳ 属实况）
    finished = not failed and stages.get("materials") == "done"
    if failed:
        template, title = "red", "⚠️ 评估中断"
    elif finished:
        template, title = "green", "🏁 评估完成"
    else:
        template, title = "blue", "🚀 正在评估"

    lines = []
    for key, label in _PROGRESS_STAGES:
        state = stages.get(key, "pending")
        mark = {"done": "✅", "running": "🔄"}.get(state, "⏳")
        extra = ""
        if key == "eval" and state == "done" and grade:
            extra = f" · 综合评级 **{grade}**"
        lines.append(f"{mark} {label}{extra}")
    stage_md = "\n".join(lines)

    elapsed_md = f"⏱️ 已进行 {elapsed_seconds} 秒 · 预计 3~8 分钟" if not finished and not failed else ""
    if failed:
        body = f"原因：{failed_reason}\n可在网页指挥中心查看失败详情后重试。"
    elif final_note:
        # 完成卡只显示结语；进行中的中间态提示（渲染物料中/断点恢复中）保留点阵，让用户看到推进到哪了
        body = final_note if finished else f"{final_note}\n\n{stage_md}"
    else:
        body = stage_md

    elements: list[dict[str, Any]] = []
    if elapsed_md:
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": elapsed_md}})
        elements.append({"tag": "hr"})
    elements.append({"tag": "div", "text": {"tag": "lark_md", "content": body}})
    elements.append({
        "tag": "note",
        "elements": [{"tag": "plain_text", "content": "完成后自动发送 PDF/长图/招呼语 · 已停复核断点，绝不自动投递"},
        ],
    })

    return {
        "config": {"wide_screen_mode": True},
        "header": {"template": template, "title": {"tag": "plain_text", "content": f"{title}：{company} · {job}"}},
        "elements": elements,
    }


async def _run_pipeline_with_feedback(
    chat_id: str,
    record_id: str,
    card_msg_id: str | None = None,
    started_epoch: float | None = None,
    stages: dict[str, str] | None = None,
    grade: str = "",
    resume: bool = False,
) -> None:
    """评估进度卡模式：单卡原地更新（PATCH），完成后置绿并交付物料，不再逐条文字刷屏。

    resume=True（服务重启恢复）：复用旧进度卡与原始开始时间（墙钟，跨重启计时连续），
    登记表已有记录不重复登记；物料若重启前已送达则跳过补发。
    """
    import time as _time

    from app.automation.full_auto import run_single_job_pipeline_async

    logger.info(f"[聊天录入] 触发单岗位评估流水线 | chat_id={chat_id} | record_id={record_id} | resume={resume}")

    # 先取公司/岗位用于进度卡标题
    from app.core.feishu_client import feishu_client

    company, job = "", ""
    try:
        rec = await feishu_client.fetch_bitable_record_by_id(settings.FEISHU_TABLE_ID_JOBS, record_id)
        fields0 = (rec or {}).get("fields", {}) or {}

        def _t0(v: Any) -> str:
            if isinstance(v, str):
                return v.strip()
            if isinstance(v, list):
                return "".join(x.get("text", "") for x in v if isinstance(x, dict)).strip()
            return str(v or "").strip()

        company, job = _t0(fields0.get("公司名称")), _t0(fields0.get("岗位名称"))
    except Exception as e:
        logger.warning(f"[聊天录入] 进度卡标题取岗位信息失败: {e}")
    reg_entry = inflight_registry.get(record_id) if resume else None
    company = company or (reg_entry or {}).get("company") or "未知公司"
    job = job or (reg_entry or {}).get("job") or "未知岗位"

    if stages is None:
        stages = {k: "pending" for k, _ in _PROGRESS_STAGES}
        stages["eval"] = "running"
    grade = grade or ""
    # 计时基线用墙钟 epoch：进程内跑用本地时钟、跨重启恢复用登记时间，两者同一坐标系
    started = float(started_epoch) if started_epoch is not None else _time.time()

    def _elapsed() -> int:
        return max(0, int(_time.time() - started))

    # 首发进度卡（后续所有进展原地 PATCH 这一张卡）；恢复模式复用旧卡续写。
    # 发送失败（限流/闪断）绝不能杀死整条评估链路：降级为无卡模式并文字兜底，
    # 保证用户点完「评估」后至少有一条「已启动」的回执，且 inflight 登记不中断。
    if not resume or not card_msg_id:
        try:
            card_msg_id = await send_feishu_card(chat_id, build_progress_card(company, job, stages))
        except Exception as card_err:
            logger.warning(f"[聊天录入] 进度卡首发异常: {card_err}，退化为无进度卡模式")
            card_msg_id = None
        if not card_msg_id:
            logger.warning("[聊天录入] 进度卡发送失败，退化为无进度卡模式（仅最终回执）")
            await send_feishu_message(
                chat_id,
                "🚀 评估已启动（预计 3~8 分钟）。进度卡暂时发不出去，完成后会直接收到结果与物料通知。",
                "chat_id",
            )

    if not resume:
        inflight_registry.register(
            record_id, chat_id=chat_id, card_msg_id=card_msg_id or "",
            company=company, job=job, started_epoch=started,
        )

    async def _refresh_card(final_note: str = "", failed_reason: str = "") -> None:
        if not card_msg_id:
            return
        ok = await update_feishu_card(card_msg_id, build_progress_card(
            company, job, stages, grade=grade, elapsed_seconds=_elapsed(),
            final_note=final_note, failed_reason=failed_reason,
        ))
        if not ok:
            logger.warning("[聊天录入] 进度卡原地更新失败（继续流程）")

    _NODE_TO_STAGE = {"evaluate_node": "eval", "rewrite_node": "rewrite", "quick_greeting_node": "rewrite"}

    async def _on_node_done(node_name: str, update: dict) -> None:
        nonlocal grade
        stage = _NODE_TO_STAGE.get(node_name)
        if not stage:
            return
        stages[stage] = "done"
        grade_now = str((update or {}).get("grade") or "").strip()
        if grade_now:
            grade = grade_now
        nxt = next((k for k, _ in _PROGRESS_STAGES if stages.get(k) == "pending"), None)
        if nxt:
            stages[nxt] = "running"
        await _refresh_card()

    try:
        res = await run_single_job_pipeline_async(
            record_id=record_id, stop_at_review=True, on_node_done=_on_node_done, resume=resume,
        )
        res = res if isinstance(res, dict) else {}
        outcome = (res.get("outcome") or "").strip()
        # outcome=stopped/waiting 时 error 字段装的是「跟进状态」文案（如 简历人工复核），不是失败
        status = (res.get("status") or "").strip() or (res.get("error") or "").strip() or "物料已产出"

        if outcome == "failed":
            stages["materials"] = "pending"
            await _refresh_card(failed_reason=status or "未知原因")
            # 失败通知不能只依赖进度卡 PATCH（卡片可能已删/更新失败），文字兜底保证用户必达
            await send_feishu_message(
                chat_id,
                f"❌ 评估未完成：{status or '未知原因'}\n可在网页指挥中心查看失败详情后重试。",
                "chat_id",
            )
            return

        # 物料渲染与交付（恢复场景若重启前已送达则跳过，防止物料重复投递）
        if (inflight_registry.get(record_id) or {}).get("materials_delivered"):
            stages["materials"] = "done"
            await _refresh_card(final_note="✅ 物料此前已送达（服务重启前后衔接），无需重复发送。")
            return
        stages["materials"] = "running"
        await _refresh_card(final_note="✅ 评估与改写完成，正在渲染并交付物料…")
        delivered_ok = await _deliver_materials_to_chat(chat_id, record_id, company, job)
        if delivered_ok:
            inflight_registry.mark_materials_delivered(record_id)
        else:
            # 物料有发送失败：不标记「已送达」（否则重启恢复会永久跳过补发），文字如实告知
            stages["materials"] = "pending"
            await send_feishu_message(
                chat_id,
                "⚠️ 物料渲染完成，但部分文件发送失败。内容已回写多维表格附件列；"
                "可重新发起一次评估触发补发，或稍后在表格附件中查看。",
                "chat_id",
            )
            return
        stages["materials"] = "done"
        await _refresh_card(final_note="✅ 物料（PDF/长图/招呼语/评估报告）已送达下方消息。\n"
                                      "想改简历内容？直接发修改指令；投递完成后回复「已投递」。")
    except Exception as e:
        logger.exception(f"[聊天录入] 评估流水线执行异常 | record_id={record_id}: {e}")
        await _refresh_card(failed_reason=str(e)[:200])
        await send_feishu_message(
            chat_id,
            f"❌ 评估流程执行失败：{e}\n可在网页指挥中心查看失败详情后重试。",
            "chat_id",
        )
    finally:
        # 正常/异常路径都注销登记；只有进程被硬杀时才留现场给恢复器
        inflight_registry.unregister(record_id)


# ─── 服务重启后的中断评估恢复 ───

# 超过该时长的中断不再自动续跑（JD 可能已过期、用户意图可能已变），标红引导重评；可用环境变量覆盖
_RESUME_STALE_SECONDS = int(os.getenv("RESUME_STALE_SECONDS", "3600"))


async def resume_inflight_evaluations() -> None:
    """服务启动时恢复中断的聊天框评估（由 lifespan 后台任务调用）。

    逐条隔离：单条恢复失败不影响其余；登记项无论成败最后都注销，
    保证用户随时可以重新点击评估。
    """
    entries = inflight_registry.list_entries()
    if not entries:
        return
    print(f"🔄 [恢复] 检测到 {len(entries)} 条中断评估登记，开始逐条处理…", flush=True)
    for record_id, entry in entries.items():
        try:
            await _resume_one_inflight(record_id, entry)
        except Exception as e:
            logger.exception(f"[恢复] {record_id} 恢复失败: {e}")
            await _mark_card_failed(entry, f"自动恢复失败：{str(e)[:120]}")
        finally:
            inflight_registry.unregister(record_id)


async def _resume_one_inflight(record_id: str, entry: dict[str, Any]) -> None:
    chat_id = str(entry.get("chat_id") or "")
    card_msg_id = str(entry.get("card_msg_id") or "")
    started_epoch = float(entry.get("started_epoch") or 0)
    company = str(entry.get("company") or "")
    job = str(entry.get("job") or "")
    card_ctx = {"chat_id": chat_id, "card_msg_id": card_msg_id, "company": company, "job": job}

    age = time.time() - started_epoch
    if age > _RESUME_STALE_SECONDS:
        logger.info(f"[恢复] {record_id} 中断已 {int(age)} 秒（超阈值），不自动续跑，引导重评")
        await _mark_card_failed(
            card_ctx,
            f"评估因服务重启中断且已超过 {_RESUME_STALE_SECONDS // 60} 分钟，未自动恢复；请重新点击「评估这个岗位」。",
        )
        return

    # 查 checkpoint：没有图状态则无从续跑
    vals: dict[str, Any] = {}
    try:
        from app.automation import scheduler
        if scheduler.pipeline_app:
            state = await scheduler.pipeline_app.aget_state({"configurable": {"thread_id": record_id}})
            vals = dict(getattr(state, "values", None) or {})
    except Exception as e:
        logger.warning(f"[恢复] {record_id} 读取图状态失败: {e}")
    if not vals:
        await _mark_card_failed(
            card_ctx,
            "未找到可恢复的评估检查点（服务重启时评估尚未写入断点）；请重新点击「评估这个岗位」。",
        )
        return

    # 按已完成的图节点重建进度卡点阵（LangGraph 只在节点完成后写 checkpoint）
    stages = {k: "pending" for k, _ in _PROGRESS_STAGES}
    resumed_grade = str(vals.get("grade") or "")
    stages["eval"] = "done" if resumed_grade else "running"
    if resumed_grade:
        stages["rewrite"] = "running"
    if vals.get("final_markdown") or vals.get("greeting"):
        stages["rewrite"] = "done"
        stages["materials"] = "running"

    if card_msg_id:
        try:
            await update_feishu_card(card_msg_id, build_progress_card(
                company or "未知公司", job or "未知岗位", stages, grade=resumed_grade,
                elapsed_seconds=max(0, int(age)),
                final_note="↩️ 检测到服务重启，正在从断点恢复评估…",
            ))
        except Exception as e:
            logger.warning(f"[恢复] 断点恢复卡更新失败（忽略）: {e}")

    await _run_pipeline_with_feedback(
        chat_id, record_id,
        card_msg_id=card_msg_id or None,
        started_epoch=started_epoch,
        stages=stages,
        grade=resumed_grade,
        resume=True,
    )


async def _mark_card_failed(entry: dict[str, Any], reason: str) -> None:
    """把孤儿进度卡 PATCH 成红色中断态（尽力而为：无卡则发文字，更新失败静默）。"""
    card_msg_id = str(entry.get("card_msg_id") or "")
    try:
        if not card_msg_id:
            chat_id = str(entry.get("chat_id") or "")
            if chat_id:
                await send_feishu_message(chat_id, f"⚠️ {reason}", "chat_id")
            return
        await update_feishu_card(card_msg_id, build_progress_card(
            str(entry.get("company") or "未知公司"), str(entry.get("job") or "未知岗位"),
            {k: "pending" for k, _ in _PROGRESS_STAGES},
            failed_reason=reason,
        ))
    except Exception as e:
        logger.warning(f"[恢复] 中断卡标红失败（忽略）: {e}")




# 评估报告渲染已拆分至 app/services/eval_report.py（re-export 保持既有引用/测试路径）
from app.services.eval_report import (  # noqa: E402,F401
    _EVAL_REPORT_FIELD,
    _ensure_eval_report_field,
    _generate_eval_report_image,
    _store_eval_report_attachment,
    build_eval_report_html,
)
