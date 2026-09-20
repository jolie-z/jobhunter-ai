"""
批量为今日流转/待审批岗位补充挂载物料（PDF备份 & 图片保存）
=====================================================
- 精投岗位（A/B 级 或 包含 AI改写JSON）：
  严格读取专属「AI改写JSON」，渲染专属定制 PDF。
  若是 BOSS直聘 则额外生成定制长图；智联/51job/猎聘仅生成定制 PDF。
- 海投岗位（C/D 级，无定制改写）：
  读取当前启用的海投基准简历（recvm2xeFZufaD），渲染并按「公司名_岗位名.pdf」命名挂载。
  若是 BOSS直聘 则额外生成海投长图；智联/51job/猎聘仅生成 PDF。
"""
import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path

# 将 backend 加入 sys.path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("batch_heal_materials")

from app.core.config import settings
from app.core.feishu_client import feishu_client
from app.core.feishu_utils import extract_feishu_text, is_custom_record
from app.automation.materials import _render_custom_resume_materials
from app.core.pdf_renderer import render_resume_pdf, render_resume_image
from app.services.export_service import upload_file_to_feishu_async
from app.services.feishu_service import get_active_resume_record_id, get_job_record_from_feishu

TARGET_RECORD_IDS = [
    'recvvfm6j0Youh', 'recvvfm80rujR1', 'recvvfm9tqlZ0S', 'recvvfmaWewEQX',
    'recvvfmcse2b6P', 'recvvfmdXNQdPm', 'recvvfmfqIKAYG', 'recvvfmgSDgfM5',
    'recvvfmjLNraCd', 'recvvfmldJdTtF', 'recvvfmmGgR1SD', 'recvvfmo72Z8T9',
    'recvvfmpDqWAhm', 'recvvfmr3qJ1Vy', 'recvvfmsxHLtoH', 'recvvfmudXZZCx'
]

def sanitize_name(text: str) -> str:
    cleaned = "".join(c for c in text if c not in r'\/:*?"<>|').strip()
    return cleaned.replace(" ", "_")[:50] or "未知"

async def main():
    logger.info("🚀 [Batch Heal] 开始执行今日岗位物料智能全自动补齐...")
    frontend_base = (
        getattr(settings, "FRONTEND_BASE_URL", None)
        or getattr(settings, "FRONTEND_URL", None)
        or "http://localhost:3000"
    ).rstrip("/")

    active_resume_id = await asyncio.to_thread(get_active_resume_record_id) or "recvm2xeFZufaD"
    logger.info(f"📋 当前生效基准海投简历 ID: {active_resume_id}")

    # 1. 预先一次性渲染海投基准简历的 PDF 与长图 Bytes（大幅降低批次耗时，杜绝重复启动 9 次浏览器渲染）
    logger.info(f"🎨 预渲染海投基准简历物料...")
    mass_url = f"{frontend_base}/print/resume?record_id={active_resume_id}&template=classic"
    try:
        mass_pdf_bytes, mass_img_bytes = await asyncio.gather(
            render_resume_pdf(mass_url, page_size="A4"),
            render_resume_image(mass_url),
        )
        logger.info(f"✅ 海投基准简历预渲染完成: PDF {len(mass_pdf_bytes)} bytes, Image {len(mass_img_bytes)} bytes")
    except Exception as e:
        logger.error(f"❌ 海投基准简历预渲染失败: {e}")
        return

    results = []

    for idx, rid in enumerate(TARGET_RECORD_IDS, 1):
        logger.info(f"\n[{idx}/{len(TARGET_RECORD_IDS)}] 正在检查/处理岗位: {rid}")
        rec = await feishu_client.get_record(settings.FEISHU_TABLE_ID_JOBS, rid)
        if not rec:
            logger.warning(f"⚠️ 未找到飞书记录: {rid}")
            results.append({"rid": rid, "status": "未找到记录"})
            continue

        fields = rec.get("fields", {})
        company = sanitize_name(extract_feishu_text(fields.get("公司名称", "")) or "未知公司")
        title = sanitize_name(extract_feishu_text(fields.get("岗位名称", "")) or "未知岗位")
        raw_plat = extract_feishu_text(fields.get("招聘平台", "")).lower()
        is_boss = "boss" in raw_plat
        is_custom = is_custom_record(fields)
        track_name = "精投(专属定制)" if is_custom else "海投(通用基准)"
        plat_name = "BOSS直聘" if is_boss else ("51job" if "51" in raw_plat else ("智联" if "智联" in raw_plat or "zhilian" in raw_plat else "猎聘"))

        pdf_att = fields.get("PDF备份") or fields.get("PDF 备份") or []
        img_att = fields.get("图片保存") or []
        has_pdf = bool(isinstance(pdf_att, list) and len(pdf_att) > 0 and pdf_att[0].get("file_token"))
        has_img = bool(isinstance(img_att, list) and len(img_att) > 0 and img_att[0].get("file_token"))

        # 如果是非 BOSS 且已有 PDF，或者 BOSS 且已有 PDF + 图片，跳过
        if has_pdf and (not is_boss or has_img):
            logger.info(f"⏩ 【{company} · {title}】物料已完整，跳过。")
            results.append({
                "rid": rid,
                "company": company,
                "title": title,
                "plat": plat_name,
                "track": track_name,
                "status": "已存在物料(跳过)",
                "pdf_token": pdf_att[0].get("file_token", ""),
                "img_token": img_att[0].get("file_token", "") if img_att else ""
            })
            continue

        file_base_name = f"{company}_{title}"
        pdf_file_name = f"{file_base_name}.pdf"
        img_file_name = f"{file_base_name}-长图.jpg"

        patch_fields = {}

        if is_custom:
            # 精投岗位：必须读专属「AI改写JSON」
            raw_json_str = extract_feishu_text(fields.get("AI改写JSON", "")).strip()
            if not raw_json_str:
                logger.error(f"❌ 精投岗位【{company} · {title}】缺失 AI改写JSON，跳过！")
                results.append({
                    "rid": rid,
                    "company": company,
                    "title": title,
                    "plat": plat_name,
                    "track": track_name,
                    "status": "失败(缺失AI改写JSON)",
                })
                continue
            
            try:
                struct_data = json.loads(raw_json_str)
            except Exception as e:
                logger.error(f"❌ 精投岗位【{company} · {title}】AI改写JSON 解析失败: {e}")
                results.append({
                    "rid": rid,
                    "company": company,
                    "title": title,
                    "plat": plat_name,
                    "track": track_name,
                    "status": f"失败(JSON解析错: {e})",
                })
                continue

            logger.info(f"🎨 正在渲染精投定制物料: {file_base_name} (need_image={is_boss})...")
            mats = await _render_custom_resume_materials(
                struct_data,
                pdf_file_name,
                need_image=is_boss
            )
            if not mats or not mats.get("pdf_token"):
                logger.error(f"❌ 精投岗位【{company} · {title}】物料渲染或上传失败！")
                results.append({
                    "rid": rid,
                    "company": company,
                    "title": title,
                    "plat": plat_name,
                    "track": track_name,
                    "status": "渲染/上传失败",
                })
                continue

            patch_fields["PDF备份"] = [{"file_token": mats["pdf_token"], "name": pdf_file_name}]
            if is_boss and mats.get("img_token"):
                patch_fields["图片保存"] = [{"file_token": mats["img_token"], "name": img_file_name}]

            pdf_token_result = mats.get("pdf_token")
            img_token_result = mats.get("img_token", "")
        else:
            # 海投岗位：复用已预渲染的高保真海投物料并定制文件名上传
            logger.info(f"📦 正在上传海投通用物料附件: {file_base_name} (need_image={is_boss})...")
            tmp_pdf_path = Path(f"/tmp/{rid}_{int(time.time())}.pdf")
            tmp_pdf_path.write_bytes(mass_pdf_bytes)
            try:
                pdf_token = await upload_file_to_feishu_async(tmp_pdf_path, file_name=pdf_file_name)
            finally:
                tmp_pdf_path.unlink(missing_ok=True)

            patch_fields["PDF备份"] = [{"file_token": pdf_token, "name": pdf_file_name}]
            pdf_token_result = pdf_token
            img_token_result = ""

            if is_boss:
                tmp_img_path = Path(f"/tmp/{rid}_{int(time.time())}.jpg")
                tmp_img_path.write_bytes(mass_img_bytes)
                try:
                    img_token = await upload_file_to_feishu_async(tmp_img_path, file_name=img_file_name)
                finally:
                    tmp_img_path.unlink(missing_ok=True)
                patch_fields["图片保存"] = [{"file_token": img_token, "name": img_file_name}]
                img_token_result = img_token

        # 回写飞书
        logger.info(f"💾 回写飞书多维表格: {patch_fields.keys()}")
        ok = await feishu_client.update_record(settings.FEISHU_TABLE_ID_JOBS, rid, patch_fields)
        if ok:
            logger.info(f"✅ 成功补齐并挂载物料: {company} · {title}")
            results.append({
                "rid": rid,
                "company": company,
                "title": title,
                "plat": plat_name,
                "track": track_name,
                "status": "成功补齐",
                "pdf_token": pdf_token_result,
                "img_token": img_token_result
            })
        else:
            logger.error(f"❌ 飞书 update_record 失败: {rid}")
            results.append({
                "rid": rid,
                "company": company,
                "title": title,
                "plat": plat_name,
                "track": track_name,
                "status": "飞书回写失败",
            })

    print("\n" + "="*80)
    print("📊 批量物料补齐结果汇总表")
    print("="*80)
    for r in results:
        print(f"[{r.get('status')}] {r.get('track')} | {r.get('plat')} | {r.get('company')} - {r.get('title')} | PDF: {r.get('pdf_token') or '-'} | IMG: {r.get('img_token') or '-'}")
    print("="*80)

if __name__ == "__main__":
    asyncio.run(main())
