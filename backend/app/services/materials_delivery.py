"""物料交付：评估完成后把 PDF/长图/招呼语/评估报告 直接送达聊天框。

从 job_entry_chat.py 拆出；依赖 eval_report（报告附件回写）；
对 resume_edit_chat 的交付锚点登记走函数内懒导入（防循环）。
job_entry_chat 保留同名 re-export，既有调用方与测试路径不受影响。
"""
import asyncio
import json
import logging
import re
from typing import Any

from app.core.config import settings
from app.core.feishu_messaging import send_feishu_card, send_feishu_message
from app.services.eval_report import (
    _ensure_eval_report_field,  # noqa: F401  # 测试 monkeypatch 接缝，勿删
    _generate_eval_report_image,
    _store_eval_report_attachment,
)

logger = logging.getLogger(__name__)


async def _deliver_materials_to_chat(chat_id: str, record_id: str, company: str = "", job: str = "") -> bool:
    """评估完成后把物料直接发到聊天框：PDF 简历 + 图片长图 + 打招呼语 + 岗位复核卡片。

    返回 True=关键物料（该发的 PDF/长图）全部真实送达；False=有发送失败或无物料。
    调用方（评估反馈链路）据此决定是否标记「已送达」——假成功会让重启恢复永久跳过补发。
    """
    import tempfile
    from pathlib import Path as _Path

    from app.core import feishu_utils
    from app.core.feishu_client import feishu_client
    from app.core.feishu_messaging import (
        send_feishu_file,
        send_feishu_image,
        upload_file_to_feishu,
        upload_image_to_feishu,
    )

    rec = await feishu_client.fetch_bitable_record_by_id(settings.FEISHU_TABLE_ID_JOBS, record_id)
    fields = (rec or {}).get("fields", {}) or {}

    def _tokens(field_val: Any) -> list[str]:
        if isinstance(field_val, list):
            return [a.get("file_token") for a in field_val if isinstance(a, dict) and a.get("file_token")]
        return []

    def _text(field_val: Any) -> str:
        if field_val is None:
            return ""
        if isinstance(field_val, str):
            return field_val.strip()
        if isinstance(field_val, list):
            return "".join(
                str(item.get("text", "")) for item in field_val if isinstance(item, dict)
            ).strip()
        return str(field_val).strip()

    company = _text(fields.get("公司名称")) or company or "未知公司"
    job = _text(fields.get("岗位名称")) or job or "未知岗位"

    async def _send_attachment(tokens: list[str], filename: str, is_image: bool) -> bool:
        for token in tokens[:1]:
            tmp_path = ""
            try:
                with tempfile.NamedTemporaryFile(suffix=".jpg" if is_image else ".pdf", delete=False) as f:
                    tmp_path = f.name
                ok = await asyncio.to_thread(feishu_utils.download_feishu_file, token, tmp_path)
                if not ok:
                    continue
                data = await asyncio.to_thread(_Path(tmp_path).read_bytes)
                if is_image:
                    img_key = await upload_image_to_feishu(data)
                    # send_feishu_image/file 返回真实送达结果，失败不得当成功
                    return bool(await send_feishu_image(chat_id, img_key))
                file_key = await upload_file_to_feishu(data, filename)
                return bool(await send_feishu_file(chat_id, file_key))
            except Exception as e:
                logger.warning(f"[聊天录入] 物料下载/发送失败 token={token}: {e}")
            finally:
                if tmp_path:
                    _Path(tmp_path).unlink(missing_ok=True)
        return False

    delivered: list[str] = []

    pdf_tokens = _tokens(fields.get("PDF备份")) or _tokens(fields.get("PDF 备份"))
    img_tokens = _tokens(fields.get("图片保存"))

    # 按需渲染：记录有改写结果但没挂物料（如自定义 Skill 模式会故意清空附件）时，现场渲染并挂回
    if not pdf_tokens and not img_tokens:
        rewrite_content = _text(fields.get("AI改写JSON"))
        if rewrite_content and not rewrite_content.lstrip().startswith("❌"):
            try:
                logger.info(f"[聊天录入] 记录无物料，按需渲染 PDF/长图 | record_id={record_id}")
                from app.automation.materials import _render_custom_resume_materials

                # 「AI改写JSON」存 V2 JSON（方案 A）时直接使用；旧记录为 markdown 时走 LLM 解析兜底
                parsed: dict[str, Any] | None = None
                if rewrite_content.lstrip().startswith("{"):
                    try:
                        parsed = json.loads(rewrite_content)
                    except json.JSONDecodeError:
                        parsed = None
                if parsed is None:
                    from ai_agents.markdown_to_json import parse_markdown_to_json
                    parsed = await asyncio.to_thread(parse_markdown_to_json, rewrite_content)

                # 补齐个人隐私（与 workflow 渲染行为一致；新格式已拼接时此处为幂等覆盖）
                try:
                    from app.services.feishu_service import get_active_resume_record_id

                    active_rid = await asyncio.to_thread(get_active_resume_record_id)
                    if active_rid:
                        orig = await feishu_client.get_record(settings.FEISHU_TABLE_ID_RESUMES, active_rid)
                        raw_s = (orig or {}).get("fields", {}).get("结构化数据", "")
                        if isinstance(raw_s, list):
                            raw_s = "".join(x.get("text", "") for x in raw_s if isinstance(x, dict))
                        if raw_s and isinstance(parsed, dict):
                            orig_json = json.loads(raw_s)
                            parsed.setdefault("personalInfo", {}).update(orig_json.get("personalInfo") or {})
                except Exception as merge_err:
                    logger.warning(f"[聊天录入] 个人隐私补齐失败（按改写原文渲染）: {merge_err}")

                cleaned = re.sub(r'[\/\\:\*\?"<>\|\s]+', '_', f"{company}_{job}").strip("_") or "专属定制简历"
                mats = await _render_custom_resume_materials(parsed, cleaned)
                if mats:
                    pdf_tokens, img_tokens = [mats["pdf_token"]], [mats["img_token"]]
                    await feishu_client.update_record(settings.FEISHU_TABLE_ID_JOBS, record_id, {
                        "PDF备份": [{"file_token": mats["pdf_token"], "name": f"{mats['name']}.pdf"}],
                        "图片保存": [{"file_token": mats["img_token"], "name": f"{mats['name']}-长图.jpg"}],
                    })
                    logger.info(f"[聊天录入] 按需渲染完成并已挂回附件 | record_id={record_id}")
            except Exception as e:
                logger.warning(f"[聊天录入] 按需渲染物料失败（继续尝试已有附件）: {e}")

    pdf_ok = await _send_attachment(pdf_tokens, f"{company}-{job}-简历.pdf", is_image=False)
    if pdf_ok:
        delivered.append("PDF 简历")
    img_ok = await _send_attachment(img_tokens, f"{company}-{job}-简历长图.jpg", is_image=True)
    if img_ok:
        delivered.append("简历长图")

    greeting = _text(fields.get("打招呼语"))
    if greeting:
        await send_feishu_message(chat_id, f"💬 打招呼语（长按可复制）：\n{greeting}", "chat_id")
        delivered.append("打招呼语")

    if not delivered:
        await send_feishu_message(
            chat_id,
            "⚠️ 没找到可发送的物料（PDF/长图/打招呼语均为空）。可能该岗位走了无需物料的轨道，"
            "或物料还在渲染中——可稍后在多维表格附件列查看。",
            "chat_id",
        )
        return False

    summary = "、".join(delivered)
    await send_feishu_message(chat_id, f"📦 物料已送达：{summary}。可点击下方快捷操作进行复核与流转。", "chat_id")

    # 成功判定：表里登记过的关键物料（PDF/长图）必须真实送达；表里本就没有的项不算失败
    critical_ok = (pdf_ok or not pdf_tokens) and (img_ok or not img_tokens)
    if not critical_ok:
        logger.warning(f"[聊天录入] 关键物料未全部送达 pdf_ok={pdf_ok} img_ok={img_ok} | record_id={record_id}")
        return False

    summary = "、".join(delivered)
    await send_feishu_message(chat_id, f"📦 物料已送达：{summary}。可点击下方快捷操作进行复核与流转。", "chat_id")

    # 评估报告可视化长图（HTML 渲染），HTML 原件同步存「评估报告」附件字段
    try:
        report_bytes = await _generate_eval_report_image(fields)
        if report_bytes:
            await send_feishu_message(chat_id, "📊 评估报告（可视化长图：AI 初评 8 维得分 + 深度评估报告）：", "chat_id")
            report_key = await upload_image_to_feishu(report_bytes)
            await send_feishu_image(chat_id, report_key)
            await _store_eval_report_attachment(record_id, fields, report_bytes)
    except Exception as report_err:
        logger.warning(f"[聊天录入] 评估报告生成/发送失败（不影响物料交付）: {report_err}")

    # 登记最近交付岗位 + 发送全生命周期交互卡片（带最新状态与操作按钮）
    try:
        from app.services import resume_edit_chat
        from app.services.chat_agent.card_builder import build_job_selected_card

        resume_edit_chat.record_delivered_context(chat_id, record_id)
        status = _text(fields.get("跟进状态")) or "简历人工复核"
        grade = _text(fields.get("综合评级 (A-F)"))
        card = build_job_selected_card(
            {
                "company": company,
                "title": job,
                "city": _text(fields.get("城市")),
                "salary": _text(fields.get("薪资")),
                "platform": _text(fields.get("招聘平台")),
                "status": status,
                "grade": grade,
            },
            record_id=record_id,
            card_title=f"🎯 岗位物料已就绪：{company} · {job}",
        )
        await send_feishu_card(chat_id, card)
    except Exception as card_err:
        logger.warning(f"[聊天录入] 岗位物料就绪卡片发送失败: {card_err}")

    return True
