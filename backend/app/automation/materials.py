"""
海投物料补全
==================
把配置里指定的「海投简历」一次性渲染成 PDF + 长图，
挂到飞书里缺物料的新线索记录上：

- 猎聘 / 51job / 智联 的投递引擎硬性要求「PDF备份」附件
- BOSS 投递引擎发送的是「图片保存」里的图片简历

原则：
- 渲染一次、复用 N 条（同一份海投简历挂给所有缺料记录）
- 每轮有上限（MAX_FILL_PER_RUN），避免链路被物料挂载拖太长
- 只处理「新线索」状态（未投递、未淘汰的待处理线索）
- 任何一步失败都不抛出，只记日志（物料缺失不应阻断整条链路，
  缺料的记录会在投递段按各平台原有逻辑报失败）
"""
import asyncio
import logging
import time
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)

MAX_FILL_PER_RUN = 60          # 单轮最多挂载条数
SCAN_PAGES = 3                 # 最多扫描 3 页新线索（每页 100）


def _find_records_missing_materials(limit: int) -> list[str]:
    """找出缺 PDF备份 的新线索记录 ID（同步，内部走飞书搜索接口）。"""
    from app.services.feishu_service import APP_TOKEN, TABLE_ID, get_tenant_access_token

    token = get_tenant_access_token()
    if not token:
        return []
    url = (f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}"
           f"/tables/{TABLE_ID}/records/search")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    missing: list[str] = []
    page_token = None
    for _ in range(SCAN_PAGES):
        payload = {
            "filter": {"conjunction": "and", "conditions": [
                {"field_name": "跟进状态", "operator": "is", "value": ["新线索"]}]},
            "page_size": 100,
        }
        if page_token:
            payload["page_token"] = page_token
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=30,
                                 proxies={"http": None, "https": None})  # type: ignore[dict-item]  # requests stub 过严：None 值运行时合法
            data = resp.json().get("data", {})
        except Exception as e:
            logger.warning(f"[物料补全] 搜索新线索失败: {e}")
            break
        for rec in data.get("items", []):
            fields = rec.get("fields", {})
            if not fields.get("PDF备份"):
                missing.append(rec["record_id"])
                if len(missing) >= limit:
                    return missing
        if not data.get("has_more"):
            break
        page_token = data.get("page_token")
    return missing


# 🌟 海投通用物料内存缓存：(timestamp, mats_dict)，TTL 10 分钟，杜绝批量海投重复启动 Playwright 渲染与上传
# key 必须带 need_image 维度：智联/51job/猎聘只渲染 PDF（无 img_token），若与 BOSS 共用同一条缓存，
# 10 分钟 TTL 内 BOSS 岗会命中缺长图的物料导致挂载失败/投递中断
_MASS_MATERIALS_CACHE: dict[tuple[str, bool], tuple[float, dict[str, str]]] = {}
_MASS_MATERIALS_CACHE_TTL = 600


async def resolve_mass_resume_id(config: dict[str, Any] | None) -> str:
    """海投母本简历 ID 的唯一取值口径：配置优先（去空白），缺失时回退飞书当前激活简历。

    quick_greeting 预挂载、delivery 自愈、auto-heal 的 PDF/长图分支、发射前物料保鲜
    必须共用这一处，否则同一岗位在不同路径可能选中不同简历；纯空格配置若不 strip 会被
    `or` 当成有效 ID 漏过兜底，最终以空简历渲染上传。
    """
    resume_id = str((config or {}).get("mass_apply_resume_id") or "").strip()
    if resume_id:
        return resume_id
    from app.services.feishu_service import get_active_resume_record_id
    resume_id = str((await asyncio.to_thread(get_active_resume_record_id)) or "").strip()
    logger.info(f"🛠️ [物料] 配置未指定海投母本简历，自动回退飞书当前激活简历: {resume_id or '(仍为空)'}")
    return resume_id


async def _render_mass_resume_materials(resume_record_id: str, need_image: bool = True) -> dict[str, str] | None:
    """渲染海投简历为 PDF (+可选长图) 并上传飞书，返回 {pdf_token, img_token, name}。

    上传文件名使用简历库记录的「简历版本」名称（如"海投简历"），
    让飞书附件与平台侧附件都能看出最终投的是哪份简历。
    """
    return await _render_mass_resume_materials_with_name_internal(resume_record_id, None, need_image=need_image)


async def _render_mass_resume_materials_with_name(resume_record_id: str, custom_pdf_name: str, need_image: bool = True) -> dict[str, str] | None:
    """渲染海投简历为 PDF (+可选长图) 并上传飞书，返回 {pdf_token, img_token, name}。

    resume_record_id: 海投简历配置 ID
    custom_pdf_name: 自定义 PDF 文件名（如"广州数据集团_公卫 AI 产品经理.pdf"）
    need_image: 是否需要长图（BOSS直聘必需，智联/51job/猎聘仅需PDF可跳过长图大幅提速）

    用于逐个岗位动态命名场景，HR 收到的是 `公司_岗位.pdf` 而非 '海投简历.pdf'
    """
    return await _render_mass_resume_materials_with_name_internal(resume_record_id, custom_pdf_name, need_image=need_image)


async def _render_mass_resume_materials_with_name_internal(resume_record_id: str, custom_pdf_name: str | None, need_image: bool = True) -> dict[str, str] | None:
    """内部实现：渲染海投简历为 PDF (+可选长图) 并上传飞书。

    resume_record_id: 海投简历配置 ID
    custom_pdf_name: 自定义 PDF 文件名（None 时使用简历版本名）
    need_image: 是否需要长图
    """
    import json

    # 🌟 海投通用物料批次复用（custom_pdf_name 为空时代表通用简历模板）
    # 避免在批量海投流水线中，多个缺物料岗位重复启动 Playwright 渲染和重复上传飞书
    if not custom_pdf_name and resume_record_id:
        cache_key = (resume_record_id, need_image)
        cached = _MASS_MATERIALS_CACHE.get(cache_key)
        if cached:
            cached_time, cached_res = cached
            if time.time() - cached_time < _MASS_MATERIALS_CACHE_TTL:
                logger.info(f"✨ [物料复用] 命中海投简历物料缓存({cache_key})，直接复用已上传的 PDF/长图")
                return cached_res

    from app.core.config import settings
    from app.core.feishu_client import feishu_client
    from app.core.feishu_utils import extract_feishu_text
    from app.core.pdf_renderer import (
        render_html_to_image,
        render_html_to_pdf,
        render_resume_image,
        render_resume_pdf,
    )
    from app.core.resume_html_builder import build_resume_html
    from app.services.export_service import upload_file_to_feishu_async

    # 确定文件名与简历数据：优先自定义名，否则读简历版本名
    resume_dict = None
    if custom_pdf_name and custom_pdf_name.endswith('.pdf'):
        name = custom_pdf_name[:-4]
    else:
        name = "海投简历"

    try:
        rec = await feishu_client.get_record(settings.FEISHU_TABLE_ID_RESUMES, resume_record_id)
        if rec:
            fields = rec.get("fields", {})
            vname = extract_feishu_text(fields.get("简历版本", ""))
            if vname.strip() and not custom_pdf_name:
                name = vname.strip()
            raw_struct = fields.get("结构化数据", "")
            if isinstance(raw_struct, list):
                raw_struct = "".join([x.get("text", "") for x in raw_struct])
            if raw_struct:
                resume_dict = json.loads(raw_struct)
    except Exception as e:
        logger.warning(f"[物料补全] 读取指定海投简历数据异常: {e}")

    # 🌟 自愈容错：若未读到指定ID数据，自动回退读取系统当前启用的基准简历「结构化数据」
    # （否则 resume_dict 为 None 时本地引擎会渲染并上传一份空简历，比兜底失败更糟）
    if not resume_dict:
        try:
            from app.services.feishu_service import get_active_resume_record_id
            active_rid = await asyncio.to_thread(get_active_resume_record_id)
            if active_rid and active_rid != resume_record_id:
                active_rec = await feishu_client.get_record(settings.FEISHU_TABLE_ID_RESUMES, active_rid)
                raw_active = (active_rec or {}).get("fields", {}).get("结构化数据", "")
                if isinstance(raw_active, list):
                    raw_active = "".join([x.get("text", "") for x in raw_active])
                if raw_active:
                    resume_dict = json.loads(raw_active)
                    logger.info(f"✨ [物料补全] 指定简历 {resume_record_id} 无结构化数据，已回退命中系统基准启用简历 {active_rid}")
        except Exception as e:
            logger.warning(f"[物料补全] 尝试回退基准简历失败: {e}")

    # 🌟 写入临时文件并渲染
    ts = int(time.time())
    tmp_pdf = Path(f"/tmp/mass_resume_{ts}.pdf")
    tmp_img = Path(f"/tmp/mass_resume_{ts}.jpg")
    try:
        # 单一可信源：Playwright 渲染只认 FRONTEND_BASE_URL（已声明字段且带默认值，不会 AttributeError）
        frontend_base = settings.FRONTEND_BASE_URL.rstrip("/")
        pdf_bytes = None
        img_bytes = None

        # 🌟 优先使用前端高保真打印路由渲染（与页面「预览PDF」100% 像素级对齐）
        target_rid = resume_record_id
        if not target_rid:
            from app.services.feishu_service import get_active_resume_record_id
            target_rid = await asyncio.to_thread(get_active_resume_record_id)

        if target_rid:
            try:
                url = f"{frontend_base}/print/resume?record_id={target_rid}&template=classic"
                logger.info(f"🎨 正在使用前端高保真打印路由渲染【{name}】物料: {url}")
                if need_image:
                    pdf_bytes, img_bytes = await asyncio.gather(
                        render_resume_pdf(url, page_size="A4"),
                        render_resume_image(url),
                    )
                else:
                    pdf_bytes = await render_resume_pdf(url, page_size="A4")
            except Exception as e:
                logger.warning(f"⚠️ 前端高保真路由渲染异常，自动回退本地引擎: {e}")

        # 🌟 若前端路由渲染未成功，兜底采用本地纯净 HTML 引擎
        if not pdf_bytes or (need_image and not img_bytes):
            logger.info(f"🎨 回退使用纯净 HTML 引擎直接渲染【{name}】物料...")
            html_str = build_resume_html(resume_dict or {})
            if need_image:
                pdf_bytes, img_bytes = await asyncio.gather(
                    render_html_to_pdf(html_str, page_size="A4"),
                    render_html_to_image(html_str),
                )
            else:
                pdf_bytes = await render_html_to_pdf(html_str, page_size="A4")

        tmp_pdf.write_bytes(pdf_bytes)
        if need_image and img_bytes:
            tmp_img.write_bytes(img_bytes)
            pdf_token, img_token = await asyncio.gather(
                upload_file_to_feishu_async(tmp_pdf, file_name=f"{name}.pdf"),
                upload_file_to_feishu_async(tmp_img, file_name=f"{name}-长图.jpg"),
            )
            if not pdf_token or not img_token:
                logger.error("[物料补全] 上传飞书失败（token 为空）")
                return None
            res = {"pdf_token": pdf_token, "img_token": img_token, "name": name}
        else:
            pdf_token = await upload_file_to_feishu_async(tmp_pdf, file_name=f"{name}.pdf")
            if not pdf_token:
                logger.error("[物料补全] 上传飞书 PDF 失败（token 为空）")
                return None
            res = {"pdf_token": pdf_token, "name": name}

        if not custom_pdf_name and resume_record_id:
            _MASS_MATERIALS_CACHE[(resume_record_id, need_image)] = (time.time(), res)
        return res
    finally:
        for p in (tmp_pdf, tmp_img):
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass


async def _render_custom_resume_materials(
    resume_dict: dict[str, Any],
    custom_pdf_name: str,
    skin: str = "classic",
    need_image: bool = True,
) -> dict[str, str] | None:
    """渲染定制简历结构体为 PDF (+可选长图) 并上传飞书，返回 {pdf_token, img_token, name}。"""

    from app.core.pdf_renderer import render_html_to_image, render_html_to_pdf
    from app.core.resume_html_builder import build_resume_html
    from app.services.export_service import upload_file_to_feishu_async

    name = custom_pdf_name[:-4] if custom_pdf_name.endswith(".pdf") else custom_pdf_name
    ts = int(time.time())
    tmp_pdf = Path(f"/tmp/custom_resume_{ts}.pdf")
    tmp_img = Path(f"/tmp/custom_resume_{ts}.jpg")
    try:
        html_str = build_resume_html(resume_dict, skin=skin)
        if need_image:
            # 🌟 并发渲染 PDF 与 长图，耗时减半
            pdf_bytes, img_bytes = await asyncio.gather(
                render_html_to_pdf(html_str, page_size="A4"),
                render_html_to_image(html_str),
            )
            tmp_pdf.write_bytes(pdf_bytes)
            tmp_img.write_bytes(img_bytes)
            pdf_token, img_token = await asyncio.gather(
                upload_file_to_feishu_async(tmp_pdf, file_name=f"{name}.pdf"),
                upload_file_to_feishu_async(tmp_img, file_name=f"{name}-长图.jpg"),
            )
            if not pdf_token or not img_token:
                logger.error("[物料渲染] 上传飞书定制物料失败（token 为空）")
                return None
            return {"pdf_token": pdf_token, "img_token": img_token, "name": name}
        else:
            # 🌟 针对非 BOSS 平台（智联/51job/猎聘），直接跳过长图排版与飞书上传，净省 10~15 秒
            pdf_bytes = await render_html_to_pdf(html_str, page_size="A4")
            tmp_pdf.write_bytes(pdf_bytes)
            pdf_token = await upload_file_to_feishu_async(tmp_pdf, file_name=f"{name}.pdf")
            if not pdf_token:
                logger.error("[物料渲染] 上传飞书定制 PDF 失败（token 为空）")
                return None
            return {"pdf_token": pdf_token, "name": name}
    finally:
        for p in (tmp_pdf, tmp_img):
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass


def _attach_materials(record_ids: list[str], pdf_token: str, img_token: str) -> int:
    """把 PDF + 长图附件挂到记录上，返回成功条数。"""
    from app.services.feishu_service import update_feishu_record

    ok = 0
    for rid in record_ids:
        try:
            if update_feishu_record(rid, {
                "PDF备份": [{"file_token": pdf_token}],
                "图片保存": [{"file_token": img_token}],
            }):
                ok += 1
        except Exception as e:
            logger.warning(f"[物料补全] 挂载失败 {rid}: {e}")
    return ok


async def ensure_mass_apply_materials(resume_record_id: str) -> dict:
    """主入口：给缺料新线索挂海投简历物料。

    返回 {"candidates": 扫描到的缺料数, "attached": 实际挂载数, "reason": ...}
    """
    summary = {"candidates": 0, "attached": 0, "reason": ""}
    if not resume_record_id:
        summary["reason"] = "未配置海投简历"
        return summary

    missing = await asyncio.to_thread(_find_records_missing_materials, MAX_FILL_PER_RUN)
    summary["candidates"] = len(missing)
    if not missing:
        summary["reason"] = "无缺料新线索"
        return summary

    materials = await _render_mass_resume_materials(resume_record_id)
    if not materials:
        summary["reason"] = "海投简历渲染/上传失败"
        return summary

    attached = await asyncio.to_thread(
        _attach_materials, missing, materials["pdf_token"], materials["img_token"])
    summary["attached"] = attached
    summary["reason"] = "ok"
    logger.info(f"[物料补全] 完成：缺料 {len(missing)} 条，成功挂载 {attached} 条")
    return summary


async def refresh_mass_materials_for_jobs(jobs: list[dict[str, Any]], label: str = "发射波次") -> int:
    """发射前海投物料保鲜：用当前配置的海投母本统一重渲染 PDF/长图并批量覆盖挂载。

    此前海投岗挂载的 PDF 备份是「流水线处理当时」的物料：老板日后换了新通用简历，
    旧挂载不会自愈——预览与实际投出去的都是旧简历（智联批次还会拿首岗旧物料全批复用）。
    发射波次开跑时统一刷一遍（渲染一次、复用 N 条），保证海投外发的永远是当前版本；
    精投岗物料为逐岗专属定制，不存在过期问题，不在刷新范围。

    jobs: 岗位列表，元素需带 job_id/record_id/t_id 之一与 is_custom 标记（缺省视为海投）。
    返回成功刷新挂载的岗位数；任何一步失败都只记日志不抛出（物料刷新失败不阻断发射，
    岗位仍按原挂载物料投递，与既有兜底口径一致）。
    """
    # 单测旁路：波次测试用桩数据直发，走真实渲染/飞书会把用例拖进网络与凭据依赖
    import os
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return 0

    def _rid(j: dict[str, Any]) -> str:
        for key in ("job_id", "record_id", "t_id"):
            raw = str(j.get(key) or "")
            if raw:
                return raw
        return ""

    try:
        from app.automation.db import get_autopilot_config
        from app.core.config import settings
        from app.core.feishu_utils import is_custom_record
        from app.services.feishu_service import (
            extract_record_id,
            get_job_record_from_feishu,
            update_feishu_record,
        )

        # 发射前不能信任批量预扫描时的快照：用户可能刚在定制工作台保存，
        # 但旧快照仍带 is_custom=False。每条记录重新读一次，避免海投母本覆盖精投物料。
        mass_jobs: list[dict[str, Any]] = []
        for job in (jobs or []):
            raw_id = _rid(job)
            rid = extract_record_id(raw_id)
            if not rid:
                continue
            fresh_record = await asyncio.to_thread(
                get_job_record_from_feishu,
                rid,
                settings.FEISHU_TABLE_ID_JOBS,
            )
            if not fresh_record:
                logger.warning(f"[海投物料保鲜·{label}] 无法重新读取岗位 {rid}，跳过刷新以避免覆盖人工物料")
                continue
            fresh_fields = fresh_record.get("fields") or {}
            if is_custom_record(fresh_fields):
                logger.info(f"[海投物料保鲜·{label}] 岗位 {rid} 已升格精投，跳过海投母本刷新")
                continue
            mass_jobs.append({**job, "record_id": rid, "is_custom": False})

        if not mass_jobs:
            return 0

        config = get_autopilot_config()
        mass_resume_id = await resolve_mass_resume_id(config)
        if not mass_resume_id:
            logger.warning(f"[海投物料保鲜·{label}] 未配置海投母本简历，跳过刷新（按原挂载物料发射）")
            return 0

        materials = await _render_mass_resume_materials(mass_resume_id)
        if not materials or not materials.get("pdf_token"):
            logger.warning(f"[海投物料保鲜·{label}] 海投物料渲染/上传失败，跳过刷新（按原挂载物料发射）")
            return 0

        mass_name = materials.get("name") or "海投简历"
        attachments = {
            "PDF备份": [{"file_token": materials["pdf_token"], "name": f"{mass_name}.pdf"}],
            "图片保存": [{"file_token": materials.get("img_token", ""), "name": f"{mass_name}-长图.jpg"}],
        }

        refreshed = 0
        for j in mass_jobs:
            rid = extract_record_id(_rid(j))
            if not rid:
                continue
            try:
                if await asyncio.to_thread(update_feishu_record, rid, attachments):
                    refreshed += 1
            except Exception as e:
                logger.warning(f"[海投物料保鲜·{label}] 挂载失败 {rid}: {e}")
        if refreshed:
            logger.info(f"[海投物料保鲜·{label}] 已用当前海投母本「{mass_name}」刷新 {refreshed}/{len(mass_jobs)} 个海投岗位物料")
        return refreshed
    except Exception as e:
        logger.warning(f"[海投物料保鲜·{label}] 刷新异常（不影响发射）: {e}", exc_info=True)
        return 0
