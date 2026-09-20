"""
审批放行与投递执行路由 (Delivery Router)
========================================
负责：
- 岗位物料完备性检查 (/check-job-materials)
- 缺失物料自动补齐与放行 (/auto-heal-and-approve)
- 单岗位审批/放行/拒绝 (/resume)
- 批量审批/放行/拒绝 (/resume_batch)
- 立即发射待投递就绪岗位 (/deliver_approved)
"""
import asyncio
import json
import logging
import os
import random
import sys
import urllib.parse
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from langgraph.types import Command
from pydantic import BaseModel

from app.automation import scheduler, upload_quota
from app.automation.db import mark_job_approved
from app.core import feishu_utils
from app.core.feishu_utils import extract_feishu_text as _txt
from app.core.utils import sanitize_filename
from app.services import feishu_service

logger = logging.getLogger(__name__)
router = APIRouter()


def _mark_approved_guarded(rid: str) -> bool:
    """B14：登记放行标记并接住返回值。失败时飞书状态已写成功，不回滚不报 failed，
    只记录日志——图断点岗位会由波次双保险打回复核，用户重新批准即可，不能静默丢标记。"""
    try:
        ok = mark_job_approved(rid)
        if not ok:
            logger.error(f"[B14] 放行标记写入 SQLite 失败（岗位 {rid}）：波次双保险可能把该岗位打回复核，请留意重试")
        return bool(ok)
    except Exception as e:
        logger.error(f"[B14] 放行标记写入异常（岗位 {rid}）: {e}")
        return False


def _get_autopilot_config() -> dict[str, Any]:
    """动态获取配置（优先使用 app.automation.router 上的补丁对象）。"""
    r = sys.modules.get("app.automation.router")
    if r and hasattr(r, "get_autopilot_config"):
        return r.get_autopilot_config()
    from app.automation.db import get_autopilot_config as _db_cfg
    return _db_cfg()


class ResumeRequest(BaseModel):
    thread_id: str
    action: str = "approve"


class ResumeBatchRequest(BaseModel):
    thread_ids: list[str]
    action: str = "approve"


class DeliverApprovedRequest(BaseModel):
    thread_ids: list[str] | None = None


class CheckMaterialsRequest(BaseModel):
    record_id: str


class AutoHealRequest(BaseModel):
    record_id: str


_DELIVERY_BG_TASKS: set[asyncio.Task] = set()

# B13 补口：正在被后台投递 worker 处理的岗位 record_id 台账。
# 批量删除据此拦截，避免岗位在投递流水线中途被物理删除污染整批状态。
_ACTIVE_DELIVERY_RECORD_IDS: set[str] = set()


async def _deliver_approved_worker(thread_ids: list[str]):
    """后台串行执行已放行（待投递）岗位的自动化投递。

    多平台流水线编排协议：
    Step 1: 扫描并按平台聚合 (BOSS, 智联, 猎聘, 51job) 并统计；
    Step 2: 严格按平台顺序调度：BOSS -> 智联 -> 猎聘 -> 51job；
    Step 3~6: 每个平台内部划分为「精投队列」与「海投队列」，默认先精后海；
             同时维护平台的批次上下文（海投单次删传，后续极速复用）。
             51job 例外：附件上传按日限次，海投整批只耗 1 次上传而精投逐岗 1 次，
             故 51job 先海投后精投；精投发射前预检当日配额，耗尽则逐岗登记 [风控]
             失败留待次日，不再唤起引擎。
    """
    if not thread_ids:
        logger.info("📭 [deliver_approved_worker] 无待投递岗位，任务退出")
        return

    # P3 加固：批次内按 record_id 去重（保序），防止重复条目被 delivery_node
    # 防重复发射守卫误拦成失败
    _seen_rids: set[str] = set()
    unique_thread_ids: list[str] = []
    for t in thread_ids:
        rid = feishu_service.extract_record_id(t)
        if rid and rid in _seen_rids:
            continue
        if rid:
            _seen_rids.add(rid)
        unique_thread_ids.append(t)
    thread_ids = unique_thread_ids

    logger.info(f"🚀 [deliver_approved_worker] 收到 {len(thread_ids)} 个就绪岗位的批量发射指令，启动多平台智能编排...")

    # B13：整批登记到投递台账，批次结束后释放；批量删除据此拦截运行中的投递岗位
    delivery_guard_ids = {rid for rid in (feishu_service.extract_record_id(t) for t in thread_ids) if rid}
    _ACTIVE_DELIVERY_RECORD_IDS.update(delivery_guard_ids)
    from app.automation import run_snapshot as _rs
    _rs.mark_job_delivering(delivery_guard_ids)

    try:
        await _deliver_approved_worker_inner(thread_ids)
    finally:
        _ACTIVE_DELIVERY_RECORD_IDS.difference_update(delivery_guard_ids)
        _rs.unmark_job_delivering(delivery_guard_ids)


def _shutdown_zhilian_browser():
    """整批投递结束后关闭智联常驻浏览器（引擎侧批次内复用，单岗不再重复冷启动 Edge）。"""
    try:
        import os as _os
        backend_dir = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
        zhilian_dir = _os.path.join(backend_dir, "zhilian_scraper")
        if zhilian_dir not in sys.path:
            sys.path.insert(0, zhilian_dir)
        import zhilian_auto_delivery
        zhilian_auto_delivery.shutdown_shared_browser()
    except Exception as e:
        logger.warning(f"关闭智联常驻浏览器异常（不影响流程）: {e}")


async def _deliver_approved_worker_inner(thread_ids: list[str]):
    from app.core.feishu_utils import extract_job_grade, is_custom_record

    PLATFORM_ORDER = ["boss", "zhilian", "liepin", "51job", "other"]
    by_platform: dict[str, dict[str, list]] = {
        p: {"custom": [], "mass": []} for p in PLATFORM_ORDER
    }

    # 🌟 平台白名单与定时波次同源（auto_deliver_platforms）：配置里关闭的平台，手动批量也不再投递
    allowed_platforms = set(_get_autopilot_config().get("auto_deliver_platforms", ["boss", "liepin", "51job", "zhilian"]))

    # Step 1: 预扫描拉取各岗位的元数据并按平台及精海分类
    for t_id in thread_ids:
        try:
            rec = await asyncio.to_thread(feishu_service.get_job_record_from_feishu, t_id, feishu_service.TABLE_ID)
            fields = rec.get("fields", {}) if rec else {}

            # 双保险：跟进状态已是「已投递」的岗位直接跳过，防重复投递/重复打招呼
            if _txt(fields.get("跟进状态", "")).strip() == "已投递":
                logger.info(f"  ⏭️ [跳过] {t_id} 跟进状态已是「已投递」，防重复发射")
                continue

            raw_plat = (_txt(fields.get("招聘平台", "")) or "").lower()

            if "boss" in raw_plat:
                plat_key = "boss"
            elif "智联" in raw_plat or "zhilian" in raw_plat:
                plat_key = "zhilian"
            elif "猎聘" in raw_plat or "liepin" in raw_plat:
                plat_key = "liepin"
            elif "51" in raw_plat or "前程" in raw_plat or "job51" in raw_plat:
                plat_key = "51job"
            else:
                plat_key = "other"

            if plat_key not in allowed_platforms:
                logger.info(f"  ⏭️ [跳过] {t_id} 平台 [{plat_key}] 未在自动投递平台白名单中")
                continue

            grade = extract_job_grade(fields).upper()
            # 🌟 统一精投判定口径（与 delivery_node / CLI 取数共用 is_custom_record，杜绝口径漂移）
            is_custom = is_custom_record(fields)

            item_info = {
                "t_id": t_id,
                "platform": plat_key,
                "is_custom": is_custom,
                "grade": grade,
                "company": _txt(fields.get("公司名称", "")),
                "title": _txt(fields.get("岗位名称", "")),
                "fields": fields,
            }

            if is_custom:
                by_platform[plat_key]["custom"].append(item_info)
            else:
                by_platform[plat_key]["mass"].append(item_info)

        except Exception as e:
            logger.warning(f"⚠️ [投递编排] 预拉取岗位 {t_id} 元数据异常: {e}")
            by_platform["other"]["mass"].append({"t_id": t_id, "platform": "other", "is_custom": False, "grade": "C", "company": "", "title": "", "fields": {}})

    # 🌟 海投物料保鲜：手动批量同样发射前统一重刷海投母本物料（渲染一次、复用全批）
    all_mass_items = [it for plat in PLATFORM_ORDER for it in by_platform[plat]["mass"]]
    if all_mass_items:
        from app.automation.materials import refresh_mass_materials_for_jobs
        refreshed = await refresh_mass_materials_for_jobs(
            [{"job_id": it.get("t_id"), "is_custom": it.get("is_custom", False)} for it in all_mass_items],
            label="手动批量投递",
        )
        if refreshed:
            logger.info(f"♻️ [手动批量投递] 已为 {refreshed} 个海投岗位刷新最新母本物料")

    # 统计并打印清晰的调度大盘日志
    c_boss = len(by_platform["boss"]["custom"])
    m_boss = len(by_platform["boss"]["mass"])
    c_zhi = len(by_platform["zhilian"]["custom"])
    m_zhi = len(by_platform["zhilian"]["mass"])
    c_lie = len(by_platform["liepin"]["custom"])
    m_lie = len(by_platform["liepin"]["mass"])
    c_51 = len(by_platform["51job"]["custom"])
    m_51 = len(by_platform["51job"]["mass"])

    logger.info("=" * 70)
    logger.info("📋 [批量投递编排大盘 (Step 1 ~ Step 6 状态总览)]")
    logger.info(f"   🔹 BOSS 直聘 : 总计 {c_boss + m_boss} 个 (精投 {c_boss} | 海投 {m_boss})")
    logger.info(f"   🔹 智联招聘 : 总计 {c_zhi + m_zhi} 个 (精投 {c_zhi} | 海投 {m_zhi})")
    logger.info(f"   🔹 猎聘平台 : 总计 {c_lie + m_lie} 个 (精投 {c_lie} | 海投 {m_lie})")
    logger.info(f"   🔹 51Job平台: 总计 {c_51 + m_51} 个 (精投 {c_51} | 海投 {m_51})")
    logger.info("   调度流水线规划执行顺序: BOSS直聘 → 智联招聘 → 猎聘 → 51Job")
    logger.info("   平台内顺序: 先精投后海投；51Job 例外为先海投后精投（附件上传按日限次，海投整批仅耗 1 次）")
    if c_51 and upload_quota.is_exhausted_today():
        logger.warning(f"   ⛔ 51Job 今日附件上传配额已耗尽，{c_51} 个精投岗将登记 [风控] 留待次日，海投岗仍按当日复用规则发射")
    logger.info("=" * 70)

    # Step 2: 严格按平台顺序串行调度
    total_ok = 0
    total_fail = 0
    from app.automation import abort as abort_mod
    for plat in PLATFORM_ORDER:
        if abort_mod.is_aborted():
            logger.warning("🛑 [deliver_approved_worker] 检测到全局终止信号 (abort)，安全中止后续平台投递")
            break

        custom_list = by_platform[plat]["custom"]
        mass_list = by_platform[plat]["mass"]
        total_plat_jobs = len(custom_list) + len(mass_list)
        if total_plat_jobs == 0:
            continue

        logger.info(f"\n🚀 ===== 开始执行 [{plat.upper()}] 平台投递任务 (共 {total_plat_jobs} 岗) =====")
        batch_mass_uploaded = False

        # Step 3~6 细化：单平台内默认先精后海；51job 附件上传按日限次，海投整批只耗
        # 1 次上传、精投逐岗 1 次，先海投才能在有限配额下覆盖最多岗位
        if plat == "51job":
            queue_plan = [("mass", mass_list), ("custom", custom_list)]
        else:
            queue_plan = [("custom", custom_list), ("mass", mass_list)]

        for q_idx, (q_kind, q_items) in enumerate(queue_plan):
            if not q_items or abort_mod.is_aborted():
                continue
            has_next_queue = any(items for _, items in queue_plan[q_idx + 1:])
            q_label = "海投" if q_kind == "mass" else "精投"
            q_icon = "🌊" if q_kind == "mass" else "🎯"
            logger.info(f"{q_icon} [{plat}] 执行{q_label}批次 (共 {len(q_items)} 岗)...")
            for idx, item in enumerate(q_items):
                if abort_mod.is_aborted():
                    logger.warning(f"🛑 [deliver_approved_worker] 检测到全局终止信号 (abort)，安全中止 [{plat}] {q_label}批次")
                    break
                t_id = item["t_id"]
                # 51job 精投配额熔断：今日已撞 720721 则不唤起引擎，自动停止后续精投进度，未执行岗位完好保留在「待投递」队列
                if plat == "51job" and q_kind == "custom" and upload_quota.is_exhausted_today():
                    remaining = len(q_items) - idx
                    logger.warning(
                        f"⛔ [51job 精投] 今日附件上传配额已耗尽（720721），自动停止后续精投进度。"
                        f"剩余 {remaining} 个未执行岗位完好保留在「待投递」队列中，等待下次投递启动。"
                    )
                    break
                if q_kind == "mass":
                    logger.info(f"📌 [{plat} 海投 {idx+1}/{len(q_items)}] 正在发射: {item['company']} - {item['title']} ({t_id}) (当批已传: {batch_mass_uploaded})")
                    deliv_res = await _deliver_single_job_helper(t_id, item, batch_mass_uploaded=batch_mass_uploaded)
                    # 若本次执行成功，标记当批次海投简历已就绪，后续岗位极速复用
                    if deliv_res:
                        batch_mass_uploaded = True
                else:
                    logger.info(f"📌 [{plat} 精投 {idx+1}/{len(q_items)}] 正在发射: {item['company']} - {item['title']} ({t_id})")
                    deliv_res = await _deliver_single_job_helper(t_id, item, batch_mass_uploaded=False)
                if deliv_res:
                    total_ok += 1
                else:
                    total_fail += 1
                    # 51job 精投若本岗在执行中触发了附件上传配额耗尽，立即终止后续精投
                    if plat == "51job" and q_kind == "custom" and upload_quota.is_exhausted_today():
                        remaining = len(q_items) - (idx + 1)
                        if remaining > 0:
                            logger.warning(
                                f"⛔ [51job 精投] 本岗触发今日附件上传配额限制（720721），自动安全停止本轮后续精投。"
                                f"后续 {remaining} 个未进行的岗位完好保留在「待投递」队列中，等待下次投递启动。"
                            )
                        break
                if idx < len(q_items) - 1 or has_next_queue:
                    if not os.environ.get("PYTEST_CURRENT_TEST"):
                        wait_s = random.randint(15, 25)
                        logger.info(f"💤 [{plat}] 防风控保护：等待 {wait_s} 秒后继续投递下一个岗位...")
                        await asyncio.sleep(wait_s)

        logger.info(f"🏁 ===== [{plat.upper()}] 平台投递完毕 =====\n")

    # 🌟 整批收尾：先关常驻浏览器再打落幕战报（INFO 已放开进白盒控制台）
    _shutdown_zhilian_browser()
    logger.info("🎉🎉 [deliver_approved_worker] 全平台批量投递任务已全部安全落幕！")
    logger.info(f"✅ 已完成所有投递：成功 {total_ok} · 失败 {total_fail}")


async def _record_batch_delivery_failure(t_id: str, item: dict, error: str) -> None:
    """手动批量投递失败登记进失败台账并同步回写飞书「投递失败」：岗位随即进入「执行失败」Tab 并标注失败原因。"""
    try:
        from app.automation import run_snapshot as _rs
        fields = item.get("fields") or {}
        link_obj = fields.get("岗位链接", {})
        job_url = link_obj.get("link", "") if isinstance(link_obj, dict) else str(link_obj or "")
        err_msg = str(error or "未知错误")[:200]
        _rs.record_delivery_failure(
            job_id=t_id,
            error=err_msg,
            company=item.get("company") or "",
            job_name=item.get("title") or "",
            platform=item.get("platform") or "zhilian",
            job_url=job_url,
            grade=item.get("grade") or "D",
        )
        # 🌟 同步将飞书「跟进状态」写入为「投递失败」，彻底打通飞书多维表格终态闭环（非阻塞）
        from app.services import feishu_service
        await asyncio.to_thread(feishu_service.mark_job_delivery_failed, t_id, err_msg)
    except Exception as e:
        logger.warning(f"[投递编排] 登记失败台账或回写飞书异常 ({t_id}): {e}")


async def _deliver_single_job_helper(t_id: str, item: dict, batch_mass_uploaded: bool = False) -> bool:
    """辅助执行单岗位投递（兼容 LangGraph 状态机断点与直接 delivery_node 调用）"""
    from app.automation.workflow import delivery_node
    config = {"configurable": {"thread_id": t_id}}
    try:
        fields = item.get("fields") or {}
        follow_status = _txt(fields.get("跟进状态", "")).strip()
        fail_log = _txt(fields.get("自动投递失败日志", "")).strip()
        retry_greeting_only = bool(follow_status == "已投递" or "[微聊受阻]" in fail_log or "微聊受阻" in fail_log)

        state = await scheduler.pipeline_app.aget_state(config) if (scheduler.pipeline_app and not retry_greeting_only) else None
        if state and state.next and state.next[0] == "manual_review_node":
            logger.info(f"🚀 [状态机流转] 恢复图状态机投递岗位 {t_id}...")
            async for event in scheduler.pipeline_app.astream(Command(resume=True), config):
                for node_name, _node_state in event.items():
                    logger.info(f"⚙️ [Node: {node_name}] {t_id} 状态已流转")
            final = await scheduler.pipeline_app.aget_state(config)
            vals = (final.values or {}) if final else {}
            if vals.get("status") == "已投递":
                return True
            await _record_batch_delivery_failure(t_id, item, str(vals.get("error") or vals.get("status") or "未知结果"))
            return False
        else:
            pdf_atts = fields.get("PDF备份") or fields.get("PDF 备份") or []
            pdf_file_name = pdf_atts[0].get("name", "").replace(".pdf", "") if pdf_atts else ""
            mock_state = {
                "job_id": t_id,
                "record_id": t_id,
                "platform": item.get("platform") or _txt(fields.get("招聘平台", "")) or "zhilian",
                "company_name": item.get("company") or _txt(fields.get("公司名称", "")) or "",
                "job_name": item.get("title") or _txt(fields.get("岗位名称", "")) or "",
                "grade": item.get("grade") or "C",
                "is_custom": item.get("is_custom", False),
                "pdf_filename": pdf_file_name,
                "greeting": _txt(fields.get("打招呼语", "")),
                "feishu_fields": fields,
                "final_markdown": _txt(fields.get("AI改写JSON", "")) or "",
                "batch_mass_uploaded": batch_mass_uploaded,
                "retry_greeting_only": retry_greeting_only,
            }
            res = await delivery_node(mock_state)
            if "error" in res:
                await _record_batch_delivery_failure(t_id, item, str(res.get("error") or ""))
                return False
            return True
    except Exception as e:
        logger.error(f"❌ 投递岗位 {t_id} 异常: {e}", exc_info=True)
        await _record_batch_delivery_failure(t_id, item, f"投递异常: {str(e)[:120]}")
        return False


@router.post("/check-job-materials")
async def check_job_materials(req: CheckMaterialsRequest):
    """检查指定飞书岗位记录的投递物料是否齐全。"""
    rid = feishu_service.extract_record_id(req.record_id)
    rec = await asyncio.to_thread(feishu_service.get_job_record_from_feishu, rid, feishu_service.TABLE_ID)
    if not rec:
        raise HTTPException(status_code=404, detail=f"未找到飞书记录 {rid}")

    fields = rec.get("fields", {})
    job_link_obj = fields.get("岗位链接", {})
    job_url = job_link_obj.get("link", "") if isinstance(job_link_obj, dict) else str(job_link_obj or "")
    has_url = bool(job_url and job_url.strip() not in ("#", "-", ""))

    pdf_attachments = fields.get("PDF备份", [])
    has_pdf = bool(isinstance(pdf_attachments, list) and len(pdf_attachments) > 0 and pdf_attachments[0].get("file_token"))

    img_attachments = fields.get("图片保存", [])
    has_image = bool(isinstance(img_attachments, list) and len(img_attachments) > 0 and img_attachments[0].get("file_token"))

    greeting = _txt(fields.get("打招呼语", "")).strip()
    has_greeting = bool(greeting)

    raw_plat = _txt(fields.get("招聘平台", "")).lower()
    is_51job = "51job" in raw_plat or "前程" in raw_plat
    has_custom_json = bool(_txt(fields.get("AI改写JSON", "")).strip())

    # 🌟 定制岗防混投：挂的附件若是「我的简历/通用简历」这类海投命名 PDF，视为物料不齐。
    # 预检不过 → 走补料/批量批准的自愈渲染定制 PDF，杜绝旧通用简历 + 定制打招呼语混投
    attached_pdf_name = (
        pdf_attachments[0].get("name", "")
        if isinstance(pdf_attachments, list) and pdf_attachments and isinstance(pdf_attachments[0], dict)
        else ""
    )
    pdf_is_generic = has_custom_json and has_pdf and attached_pdf_name.startswith(
        ("我的简历", "通用简历", "海投简历", "e2e_base")
    )

    if is_51job:
        is_ready = has_url and (has_pdf or has_image) and not pdf_is_generic
    else:
        is_ready = has_url and (has_pdf or has_image) and has_greeting and not pdf_is_generic

    return {
        "status": "success",
        "data": {
            "record_id": rid,
            "has_url": has_url,
            "has_pdf": has_pdf,
            "has_image": has_image,
            "has_greeting": has_greeting,
            "has_custom_json": has_custom_json,
            "pdf_is_generic": pdf_is_generic,
            "is_ready": is_ready,
            "platform": raw_plat,
            "job_name": _txt(fields.get("岗位名称", "")) or "未知岗位",
            "company_name": _txt(fields.get("公司名称", "")) or "未知公司",
        }
    }


def _get_feishu_tmp_download_urls(file_tokens: list[str]) -> dict[str, str]:
    """批量换取飞书 Drive 附件的免登临时直链 (0.05s 直连 CDN)。"""
    if not file_tokens:
        return {}
    token = feishu_utils.get_tenant_access_token()
    if not token:
        return {}
    query_str = "&".join([f"file_tokens={t}" for t in file_tokens])
    url = f"https://open.feishu.cn/open-apis/drive/v1/medias/batch_get_tmp_download_url?{query_str}"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        resp = feishu_utils.safe_feishu_request("GET", url, headers=headers)
        data = resp.json()
        if data.get("code") == 0:
            urls = {}
            for item in data.get("data", {}).get("tmp_download_urls", []):
                t = item.get("file_token")
                u = item.get("tmp_download_url")
                if t and u:
                    urls[t] = u
            return urls
    except Exception as e:
        logger.warning(f"获取飞书素材临时下载链接异常: {e}")
    return {}


@router.get("/job-material-urls")
async def get_job_material_urls(job_id: str):
    """提取岗位投递物料，识别所属平台并提供 inline 原生预览与 attachment 下载直链。"""
    logger.info(f"🔗 [get_job_material_urls] 提取飞书真实物料: job_id={job_id}")
    rid = feishu_service.extract_record_id(job_id)
    if not rid or rid.startswith("raw_"):
        return {"status": "success", "data": {"record_id": rid or "", "has_materials": False, "is_boss": False, "greeting_msg": ""}}

    rec = await asyncio.to_thread(feishu_service.get_job_record_from_feishu, rid, feishu_service.TABLE_ID)
    if not rec:
        raise HTTPException(status_code=404, detail=f"未找到飞书记录 {rid}")

    fields = rec.get("fields", {})
    pdf_list = fields.get("PDF备份") or fields.get("PDF 备份") or []
    img_list = fields.get("图片保存") or []
    greeting = str(_txt(fields.get("打招呼语", "")) or "").strip()

    pdf_token = pdf_list[0].get("file_token") if (isinstance(pdf_list, list) and pdf_list and isinstance(pdf_list[0], dict)) else None
    pdf_name = pdf_list[0].get("name") if (pdf_token and isinstance(pdf_list[0], dict)) else "简历.pdf"

    img_token = img_list[0].get("file_token") if (isinstance(img_list, list) and img_list and isinstance(img_list[0], dict)) else None
    img_name = img_list[0].get("name") if (img_token and isinstance(img_list[0], dict)) else "简历长图.jpg"

    raw_plat = str(_txt(fields.get("招聘平台", "")) or "").strip().lower()
    is_boss = "boss" in raw_plat

    q_pdf = urllib.parse.quote(pdf_name)
    q_img = urllib.parse.quote(img_name)

    return {
        "status": "success",
        "data": {
            "record_id": rid,
            "has_materials": bool(pdf_token or img_token),
            "has_pdf": bool(pdf_token),
            "has_image": bool(img_token),
            "pdf_name": pdf_name,
            "image_name": img_name,
            "is_boss": is_boss,
            "platform": raw_plat,
            "delivered_material": "image" if is_boss else "pdf",
            "greeting_msg": greeting,
            "pdf_stream_url": f"/api/automation/feishu-file-stream?file_token={pdf_token}&filename={q_pdf}&disposition=inline" if pdf_token else "",
            "pdf_download_url": f"/api/automation/feishu-file-stream?file_token={pdf_token}&filename={q_pdf}&disposition=attachment" if pdf_token else "",
            "image_stream_url": f"/api/automation/feishu-file-stream?file_token={img_token}&filename={q_img}&disposition=inline" if img_token else "",
            "image_download_url": f"/api/automation/feishu-file-stream?file_token={img_token}&filename={q_img}&disposition=attachment" if img_token else "",
        }
    }


@router.get("/feishu-file-stream")
async def feishu_file_stream(file_token: str, filename: str = "document.pdf", disposition: str = "inline"):
    """流式中转飞书原件并改写 Content-Disposition，实现原生 inline 预览与指定 attachment 下载。"""
    urls = await asyncio.to_thread(_get_feishu_tmp_download_urls, [file_token])
    cdn_url = urls.get(file_token)
    if not cdn_url:
        raise HTTPException(status_code=404, detail="无法获取该附件直链")

    encoded = urllib.parse.quote(filename)
    disp = "inline" if disposition == "inline" else "attachment"
    headers = {
        "Content-Disposition": f'{disp}; filename="{encoded}"; filename*=UTF-8\'\'{encoded}',
        "Cache-Control": "public, max-age=3600",
    }

    client = httpx.AsyncClient(timeout=30.0, follow_redirects=True)
    req = client.build_request("GET", cdn_url)
    resp = await client.send(req, stream=True)

    async def _stream():
        try:
            async for chunk in resp.aiter_bytes(65536):
                yield chunk
        finally:
            await resp.aclose()
            await client.aclose()

    return StreamingResponse(
        _stream(),
        status_code=resp.status_code,
        media_type=resp.headers.get("Content-Type", "application/pdf" if filename.lower().endswith(".pdf") else "image/jpeg"),
        headers=headers,
    )


# 🌟 auto_heal_and_approve 单岗并发防重入锁（防止用户狂点或并发请求击穿渲染资源）
_AUTO_HEAL_INFLIGHT_RECORDS: set[str] = set()


@router.post("/auto-heal-and-approve")
async def auto_heal_and_approve(req: AutoHealRequest):
    """自动补齐岗位缺失的物料（PDF/长图/打招呼语）并放行进入「待投递」队列。"""
    from app.automation.materials import (
        _render_custom_resume_materials,
        _render_mass_resume_materials_with_name,
        resolve_mass_resume_id,
    )

    rid = feishu_service.extract_record_id(req.record_id)
    if rid in _AUTO_HEAL_INFLIGHT_RECORDS:
        logger.info(f"⏳ [auto_heal_and_approve] 岗位 {rid} 正在后台补料放行中，直接返回处理中状态")
        return {
            "status": "processing",
            "message": "岗位物料正在后台生成与放行中，请稍候...",
        }

    _AUTO_HEAL_INFLIGHT_RECORDS.add(rid)
    try:
        rec = await asyncio.to_thread(feishu_service.get_job_record_from_feishu, rid, feishu_service.TABLE_ID)
        if not rec:
            raise HTTPException(status_code=404, detail=f"未找到飞书记录 {rid}")

        fields = rec.get("fields", {})
        job_title = _txt(fields.get("岗位名称", "")) or "未知岗位"
        company_name = _txt(fields.get("公司名称", "")) or "未知公司"
        raw_plat = _txt(fields.get("招聘平台", "")).lower()
        is_51job = "51job" in raw_plat or "前程" in raw_plat
        is_boss = "boss" in raw_plat
        # 🌟 平台按需生成物料：仅 BOSS 直聘必需长图；智联/51job/猎聘仅需 PDF 附件，跳过长图排版与上传大幅提速
        need_image = is_boss

        # 🌟 规范命名海投物料：HR 视角收到的是「公司名_岗位名.pdf」
        pdf_name = f"{company_name}_{job_title}.pdf"
        patch_fields: dict[str, Any] = {}

        raw_custom_json = _txt(fields.get("AI改写JSON", "")).strip()
        # 🌟 统一精投判定口径（is_custom_record：AI改写JSON/评级AB），
        # 与投递编排/待审批取数同源。此前 startswith("{") 曾把 markdown 降级存的定制改写
        # 误判成海投，导致通用物料与海投通用打招呼语覆盖刚花 token 生成的定制内容
        is_custom = feishu_utils.is_custom_record(fields)

        pdf_attachments = fields.get("PDF备份", [])
        has_valid_pdf = bool(isinstance(pdf_attachments, list) and len(pdf_attachments) > 0 and pdf_attachments[0].get("file_token"))
        existing_pdf_name = pdf_attachments[0].get("name", "") if has_valid_pdf else ""

        img_attachments = fields.get("图片保存", [])
        has_valid_img = bool(isinstance(img_attachments, list) and len(img_attachments) > 0 and img_attachments[0].get("file_token"))

        # 🌟 防脏物料穿透：
        # 海投岗：附件缺失 / 旧通用命名 / 未按「公司_岗位」命名 -> 强制重刷
        # 精投岗：挂的却是「我的简历/通用简历」这类海投命名 PDF，或挂了别的岗位的定制简历
        #   -> 必须重渲染定制简历。此前 is_stale_mass_pdf 被 not is_custom 短路，精投岗挂着
        #   旧通用简历也被当合规物料直接放行（旧通用简历 + 定制打招呼语混投）。
        #   命名比对同时容忍原始与 sanitize_filename 净化两种前缀（公司名含空格/标点时二者不同），
        #   与 check_job_materials.pdf_is_generic 预检同口径
        expected_pdf_prefix = f"{company_name}_{job_title}"
        expected_clean_prefix = sanitize_filename(expected_pdf_prefix, "专属定制简历")
        is_stale_mass_pdf = not is_custom and (
            not existing_pdf_name or
            existing_pdf_name.startswith(("通用简历", "e2e_base", "海投简历")) or
            not existing_pdf_name.startswith(expected_pdf_prefix)
        )
        is_stale_custom_pdf = is_custom and has_valid_pdf and (
            existing_pdf_name.startswith(("我的简历", "通用简历", "海投简历", "e2e_base")) or
            not existing_pdf_name.startswith((expected_pdf_prefix, expected_clean_prefix))
        )

        async def _call_render_custom(data: dict, name: str, need_img: bool):
            try:
                return await _render_custom_resume_materials(data, name, need_image=need_img)
            except TypeError:
                return await _render_custom_resume_materials(data, name)

        async def _call_render_mass(res_id: str, name: str, need_img: bool):
            try:
                return await _render_mass_resume_materials_with_name(res_id, name, need_image=need_img)
            except TypeError:
                return await _render_mass_resume_materials_with_name(res_id, name)

        if not has_valid_pdf or is_stale_mass_pdf or is_stale_custom_pdf:
            if is_custom:
                try:
                    struct_data = json.loads(raw_custom_json)
                    materials_res = await _call_render_custom(struct_data, pdf_name, need_image)
                except HTTPException:
                    raise
                except Exception as e:
                    raise HTTPException(
                        status_code=422,
                        detail=f"岗位【{job_title}】的精投简历内容无效，已中止自动放行，请先在定制工作台重新保存并生成 PDF",
                    ) from e
                if not materials_res:
                    raise HTTPException(
                        status_code=422,
                        detail=f"岗位【{job_title}】的精投简历渲染失败，已中止自动放行，请先在定制工作台重新生成 PDF",
                    )
            else:
                autopilot_cfg = _get_autopilot_config()
                active_resume_id = await resolve_mass_resume_id(autopilot_cfg)
                logger.info(f"🎨 [auto_heal] 岗位【{job_title}】海投物料渲染 (resume_id={active_resume_id}, need_image={need_image})")
                materials_res = await _call_render_mass(active_resume_id, pdf_name, need_image)

            if not materials_res or not (materials_res.get("pdf_token") or materials_res.get("img_token")):
                raise HTTPException(
                    status_code=422,
                    detail=f"岗位【{job_title}】无法生成简历附件（PDF/长图），已中止自动放行，请前往定制面板手动生成后再批准",
                )

            pdf_token = materials_res.get("pdf_token")
            img_token = materials_res.get("img_token")
            if pdf_token:
                patch_fields["PDF备份"] = [{"file_token": pdf_token, "name": f"{company_name}_{job_title}.pdf"}]
            if img_token:
                patch_fields["图片保存"] = [{"file_token": img_token, "name": f"{company_name}_{job_title}-长图.jpg"}]
        elif not has_valid_img and is_boss:
            # BOSS 直投岗必需图片长图，缺则补齐（精投岗按定制 JSON 渲染，防通用长图混投）
            autopilot_cfg = _get_autopilot_config()
            img_materials = None
            if is_custom:
                try:
                    struct_data = json.loads(raw_custom_json)
                    img_materials = await _call_render_custom(struct_data, pdf_name, True)
                except HTTPException:
                    raise
                except Exception as e:
                    raise HTTPException(
                        status_code=422,
                        detail=f"岗位【{job_title}】的精投简历内容无效，无法生成 BOSS 长图，请先在定制工作台重新保存",
                    ) from e
                if not img_materials or not img_materials.get("img_token"):
                    raise HTTPException(
                        status_code=422,
                        detail=f"岗位【{job_title}】的精投长图生成失败，已中止自动放行，请先在定制工作台重新生成",
                    )
            else:
                active_resume_id = await resolve_mass_resume_id(autopilot_cfg)
                logger.info(f"🎨 [auto_heal] 岗位【{job_title}】BOSS 长图补齐渲染 (resume_id={active_resume_id})")
                img_materials = await _call_render_mass(active_resume_id, pdf_name, True)
            if not img_materials or not img_materials.get("img_token"):
                raise HTTPException(
                    status_code=422,
                    detail=f"岗位【{job_title}】无法生成简历长图（BOSS直聘必需），已中止自动放行",
                )
            patch_fields["图片保存"] = [{"file_token": img_materials["img_token"], "name": f"{company_name}_{job_title}-长图.jpg"}]

        # 🌟 打招呼语处理：海投岗位统一使用系统配置的「海投通用打招呼语」，杜绝硬编码假兜底
        if not is_51job:
            autopilot_cfg = _get_autopilot_config()
            mass_greeting = str(autopilot_cfg.get("mass_apply_greeting") or "").strip()
            if not is_custom:
                # 海投岗位严格门禁：必须配置有海投打招呼语
                if not mass_greeting:
                    raise HTTPException(
                        status_code=400,
                        detail="尚未配置「海投通用打招呼语」，请前往「全链路中心-打招呼语模块」配置后再执行海投",
                    )
                patch_fields["打招呼语"] = mass_greeting
            else:
                current_greeting = _txt(fields.get("打招呼语", "")).strip()
                if not current_greeting:
                    raise HTTPException(
                        status_code=400,
                        detail=f"岗位【{job_title}】缺少精投专属打招呼语，请先在定制工作台保存后再执行投递",
                    )

        cur_status = _txt(fields.get("跟进状态", "")).strip()
        if cur_status == "已投递":
            logger.info(f"ℹ️ [auto_heal_and_approve] 岗位 {rid} 状态已为「已投递」，拦截倒流为「待投递」")
            return {
                "status": "success",
                "message": f"岗位【{job_title}】已处于「已投递」状态，无需重复放行"
            }

        patch_fields["跟进状态"] = "待投递"

        logger.info(f"✨ [auto_heal_and_approve] 正在补齐并更新飞书 {rid}: {list(patch_fields.keys())}")
        ok = await asyncio.to_thread(feishu_service.update_feishu_record, rid, patch_fields)
        if not ok:
            raise HTTPException(status_code=502, detail=f"飞书状态更新失败，岗位 {rid} 可能已被删除")

        await asyncio.to_thread(_mark_approved_guarded, rid)
        return {
            "status": "success",
            "message": f"岗位【{job_title}】物料已自动补齐并成功放行至「待投递」队列"
        }
    finally:
        _AUTO_HEAL_INFLIGHT_RECORDS.discard(rid)


@router.post("/resume")
async def resume_workflow(req: ResumeRequest):
    """老板审批/放行/接管接口（双轨兼容）。"""
    logger.info(f"👨‍💻 审批指令: Thread/Record={req.thread_id}, Action={req.action}")
    rid = feishu_service.extract_record_id(req.thread_id)

    if req.action == "reject":
        ok = await asyncio.to_thread(feishu_service.update_feishu_record, rid, {"跟进状态": "已拒绝"})
        if not ok:
            raise HTTPException(status_code=502, detail=f"飞书状态更新失败，岗位 {rid} 可能已被删除")
        logger.info(f"✏️ 岗位 {rid} 已被老板拒绝，跟进状态记为「已拒绝」，AI草稿全部保留")
        return {
            "status": "rejected_manual",
            "node": "manual_review_node",
            "message": "已拒绝该岗位：跟进状态记为「已拒绝」，仅保留在全部岗位列表，AI草稿与评估数据已完整保留。",
        }

    rec = await asyncio.to_thread(feishu_service.get_job_record_from_feishu, rid, feishu_service.TABLE_ID)
    cur_status = _txt((rec or {}).get("fields", {}).get("跟进状态", "")).strip()
    if cur_status == "已投递":
        logger.info(f"ℹ️ [resume] 岗位 {rid} 状态已为「已投递」，拦截倒流为「待投递」")
        return {
            "status": "delivered",
            "node": "delivered",
            "message": "岗位已处于「已投递」状态，无需重复放行",
        }

    ok = await asyncio.to_thread(feishu_service.update_feishu_record, rid, {"跟进状态": "待投递"})
    if not ok:
        raise HTTPException(status_code=502, detail=f"飞书状态更新失败，岗位 {rid} 可能已被删除")
    await asyncio.to_thread(_mark_approved_guarded, rid)

    autopilot_cfg = _get_autopilot_config()
    if autopilot_cfg.get("custom_deliver_mode") == "scheduled":
        fire_time = autopilot_cfg.get("custom_deliver_time", "14:00")
        return {
            "status": "scheduled",
            "node": "ready_to_deliver",
            "message": f"已放行并登记待发射：将在每天 {fire_time} 的精投发射任务中统一投递。",
        }

    return {
        "status": "approved",
        "node": "ready_to_deliver",
        "message": "已放行并进入「待投递」队列，可随时立即触发或等待自动投递。",
    }


@router.post("/resume_batch")
async def resume_workflow_batch(req: ResumeBatchRequest):
    """批量审批/放行/接管接口（双轨兼容）。"""
    if not req.thread_ids:
        return {"status": "error", "message": "未选择任何需要审批的简历"}

    logger.info(f"👨‍💻 批量审批指令: {len(req.thread_ids)} 个岗位, Action={req.action}")

    results = {"success": 0, "failed": 0, "details": []}
    autopilot_cfg = _get_autopilot_config()
    scheduled_mode = req.action == "approve" and autopilot_cfg.get("custom_deliver_mode") == "scheduled"

    for t_id in req.thread_ids:
        rid = feishu_service.extract_record_id(t_id)
        try:
            if req.action == "reject":
                ok = await asyncio.to_thread(feishu_service.update_feishu_record, rid, {"跟进状态": "已拒绝"})
                if not ok:
                    raise ValueError("飞书状态更新失败（记录可能已被删除）")
                results["success"] += 1
                results["details"].append({"thread_id": rid, "status": "rejected_manual"})
                continue

            rec = await asyncio.to_thread(feishu_service.get_job_record_from_feishu, rid, feishu_service.TABLE_ID)
            cur_status = _txt((rec or {}).get("fields", {}).get("跟进状态", "")).strip()
            if cur_status == "已投递":
                logger.info(f"ℹ️ [resume_batch] 岗位 {rid} 状态已为「已投递」，拦截倒流为「待投递」")
                results["success"] += 1
                results["details"].append({
                    "thread_id": rid,
                    "status": "delivered",
                    "node": "delivered"
                })
                continue

            ok = await asyncio.to_thread(feishu_service.update_feishu_record, rid, {"跟进状态": "待投递"})
            if not ok:
                raise ValueError("飞书状态更新失败（记录可能已被删除）")
            await asyncio.to_thread(_mark_approved_guarded, rid)

            results["success"] += 1
            results["details"].append({
                "thread_id": rid,
                "status": "scheduled" if scheduled_mode else "approved",
                "node": "ready_to_deliver"
            })
        except Exception as e:
            results["failed"] += 1
            results["details"].append({"thread_id": rid, "error": str(e)})
            logger.error(f"批量处理 {rid} 失败: {e}")

    return {"status": "success", "data": results}


# 🌟 批量投递防抖锁：同一时刻只允许一轮批量投递 worker 运行，
# 双击/重复触发/与定时波次重叠都会被拒之门外（串行锁只保证不并发打架，不去重）
_deliver_worker_lock = asyncio.Lock()


async def _guarded_deliver_worker(worker, thread_ids: list[str]):
    """持锁运行批量投递 worker，锁生命周期覆盖整轮投递。"""
    async with _deliver_worker_lock:
        await worker(thread_ids)


@router.post("/deliver_approved")
async def deliver_approved_jobs(req: DeliverApprovedRequest):
    """立即触发已放行（待投递）岗位的自动化投递。"""
    if _deliver_worker_lock.locked():
        return {
            "status": "busy",
            "message": "已有一轮批量投递在运行中，请等待其完成后再触发（防重复投递/重复打招呼）",
            "data": {"count": 0},
        }

    thread_ids = req.thread_ids or []
    if not thread_ids:
        scheduled_jobs = await asyncio.to_thread(feishu_service.get_scheduled_delivery_jobs_from_feishu)
        thread_ids = [j.get("job_id") for j in scheduled_jobs if j.get("job_id")]

    if not thread_ids:
        return {"status": "success", "message": "当前没有待投递的岗位", "data": {"count": 0}}

    logger.info(f"🚀 [deliver_approved] 启动后台批量投递，岗位数量: {len(thread_ids)}")
    r = sys.modules.get("app.automation.router")
    worker = getattr(r, "_deliver_approved_worker", _deliver_approved_worker) if r else _deliver_approved_worker
    task = asyncio.create_task(_guarded_deliver_worker(worker, thread_ids))
    _DELIVERY_BG_TASKS.add(task)
    task.add_done_callback(_DELIVERY_BG_TASKS.discard)

    return {
        "status": "success",
        "message": f"已启动 {len(thread_ids)} 个岗位的自动化投递任务。",
        "data": {"count": len(thread_ids), "thread_ids": thread_ids}
    }
