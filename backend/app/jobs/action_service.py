import asyncio
import logging
from typing import Any

import httpx
from fastapi import HTTPException

from app.core.config import settings
from app.core.feishu_client import feishu_client
from app.jobs.schemas import AIPolishRequest
from common.config import get_openai_client

logger = logging.getLogger(__name__)

async def ai_polish_service(payload: AIPolishRequest) -> str:
    """调用大模型进行局部简历润色"""
    temp_client = get_openai_client()
    if not temp_client:
        raise ValueError("AI 服务未配置（缺少 api_key）")

    model_name = settings.OPENAI_MODEL or "gpt-4o"
    def _call_openai():
        return temp_client.chat.completions.create(
            model=model_name,
            messages=[
                {
                    "role": "system",
                    "content": "你是一位顶级的资深 HR 和简历优化专家。请根据用户的要求，对提供的简历片段进行润色。必须严格遵守：只输出最终润色后的纯文本内容，绝对不要包含任何多余的解释、问候语，也绝对不要使用 markdown 代码块包裹（如 ``` 符号）。",
                },
                {"role": "user", "content": f"原始文本：{payload.selected_text}\n润色要求：{payload.instruction}"},
            ],
            timeout=30,
        )

    try:
        resp = await asyncio.to_thread(_call_openai)
        polished = (resp.choices[0].message.content or "").strip()
        return polished if polished else payload.selected_text
    except Exception as e:
        print(f"❌ AI 润色异常: {e}")
        raise ValueError("AI 润色服务暂时不可用，请稍后重试。")

async def update_job_status_service(job_id: str, status: str) -> str:
    """更新岗位的跟进状态"""
    # 提取纯 record_id
    from app.services.feishu_service import extract_record_id
    record_id = extract_record_id(job_id)

    # 救援闭环：人工把「疑似重复」改成其他状态 = 复核放行，记入去重白名单，
    # 此后任何查重关卡（自动链路/手动批量）都不再拦它，避免纠错被系统反复推翻
    if status != "疑似重复":
        try:
            from app.core.feishu_utils import extract_feishu_text
            old_rec = await asyncio.to_thread(
                get_job_record_from_feishu, record_id, settings.FEISHU_TABLE_ID_JOBS)
            if extract_feishu_text((old_rec or {}).get("fields", {}).get("跟进状态", "")) == "疑似重复":
                from app.services.job_dedup_gate import record_dedup_override
                record_dedup_override(record_id)
        except Exception as e:
            print(f"⚠️ 记录去重放行白名单失败（不影响状态更新）: {e}")

    token = await feishu_client.get_tenant_access_token()
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{settings.FEISHU_APP_TOKEN}/tables/{settings.FEISHU_TABLE_ID_JOBS}/records/{record_id}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    async with httpx.AsyncClient() as client:
        resp = await client.put(url, headers=headers, json={"fields": {"跟进状态": status}}, timeout=15.0)
        data = resp.json()
        if data.get("code") != 0:
            raise ValueError(f"更新飞书失败: {data.get('msg')}")
    # 写入成功后单条补丁缓存（原先是整表清空导致下次全量重拉）
    from app.core.feishu_client import schedule_job_cache_patch
    schedule_job_cache_patch(record_id)
    return record_id

from app.jobs.schemas import SaveLiveFieldsRequest, UpdateScheduleRequest  # noqa: E402
from app.services.feishu_service import (  # noqa: E402
    extract_record_id,
    update_feishu_record,
)
from app.services.map_service import get_amap_navigation_url  # noqa: E402


async def update_interview_schedule_service(payload: UpdateScheduleRequest) -> dict[str, Any]:
    pure_record_id = extract_record_id(payload.job_id)
    timestamp_ms = None

    if payload.interview_time:
        try:
            from datetime import datetime, timedelta, timezone
            time_str = payload.interview_time
            if len(time_str) == 16:
                dt = datetime.strptime(time_str, "%Y-%m-%dT%H:%M")
            else:
                dt = datetime.fromisoformat(time_str)
            tz_beijing = timezone(timedelta(hours=8))
            dt = dt.replace(tzinfo=tz_beijing)
            timestamp_ms = int(dt.timestamp() * 1000)
        except ValueError:
            pass

    fields_to_update = {
        "跟进状态": payload.follow_status
    }

    online_keywords = ["腾讯会议", "飞书", "钉钉", "Zoom", "线上", "视频", "电话", "http", "会议号", "在线"]

    if payload.interview_location and payload.interview_location.strip():
        location = payload.interview_location.strip()
        fields_to_update["面试地点"] = location

        is_online = any(keyword.lower() in location.lower() for keyword in online_keywords)
        if is_online:
            fields_to_update["高德导航直达"] = None
            print("  [💻] 线上地点已识别（命中关键词），清空高德导航链接")
        else:
            amap_url = await asyncio.to_thread(get_amap_navigation_url, location)
            fields_to_update["高德导航直达"] = {
                "link": amap_url,
                "text": "📍 点击查看地图导航"
            }
            print(f"  [🗺️] 线下地址精准导航已生成: {location}")

    if timestamp_ms:
        fields_to_update["面试时间"] = timestamp_ms

    if payload.resume_qa is not None:
        fields_to_update["简历专项QA"] = payload.resume_qa

    tunnel_domain = getattr(settings, "TUNNEL_DOMAIN", "")
    if tunnel_domain:
        fields_to_update["PDF链接直达"] = f"{tunnel_domain}/api/get_pdf/{pure_record_id}"

    success = await asyncio.to_thread(
        update_feishu_record,
        record_id=pure_record_id,
        fields_to_update=fields_to_update,
        table_id=settings.FEISHU_TABLE_ID_JOBS,
    )
    if success:
        return {"status": "success"}
    else:
        raise ValueError("同步飞书失败，请检查字段状态")

async def save_live_fields_service(payload: SaveLiveFieldsRequest) -> dict[str, Any]:
    pure_record_id = extract_record_id(payload.job_id)
    fields_to_update: dict[str, Any] = {}
    if payload.live_record is not None:
        fields_to_update["现场面试记录"] = payload.live_record
    if payload.resume_qa is not None:
        fields_to_update["简历专项QA"] = payload.resume_qa
    if not fields_to_update:
        return {"status": "success", "message": "无字段需要更新"}
    success = await asyncio.to_thread(
        update_feishu_record,
        record_id=pure_record_id,
        fields_to_update=fields_to_update,
        table_id=settings.FEISHU_TABLE_ID_JOBS,
    )
    if success:
        return {"status": "success", "updated_fields": list(fields_to_update.keys())}
    raise ValueError("飞书写入失败")


from app.core.feishu_utils import feishu_field_to_plain_str  # noqa: E402
from app.services.feishu_service import get_job_record_from_feishu  # noqa: E402


async def update_job_field(job_id: str, fields: dict) -> dict[str, Any]:
    pure_record_id = extract_record_id(job_id)
    success = await asyncio.to_thread(
        update_feishu_record,
        record_id=pure_record_id,
        fields_to_update=fields,
        table_id=settings.FEISHU_TABLE_ID_JOBS
    )
    if success:
        from app.core.feishu_client import schedule_job_cache_patch
        schedule_job_cache_patch(pure_record_id)
        return {"status": "success", "message": "更新成功", "job_id": pure_record_id, "updated_fields": fields}
    else:
        raise ValueError("更新飞书字段失败")

async def batch_delete_jobs(job_ids: list[str]) -> dict[str, Any]:
    if not job_ids:
        return {"status": "success", "message": "没有需要删除的记录"}
    pure_record_ids = [extract_record_id(jid) for jid in job_ids]

    # B13：删除前校验待删岗位是否正在被后台批量任务处理（评估/深评/改写/投递等）。
    # 运行中任务持有的 record_id 若被物理删除，后续拉取/回写飞书必失败并污染整批状态。
    # B5 补口：pending（排队等锁）任务与投递 worker 台账中的岗位一并拦截。
    deleting_set = {rid for rid in pure_record_ids if rid}
    conflict_ids: list[str] = []
    try:
        from app.tasks.state import task_status
        for task in task_status.values():
            if task.get("status") not in ("running", "pending"):
                continue
            for running_jid in task.get("job_ids") or []:
                running_rid = extract_record_id(running_jid)
                if running_rid and running_rid in deleting_set:
                    conflict_ids.append(running_rid)
    except Exception as e:
        # 登记表读取异常不阻断删除（fail-open），删除本身仍走飞书校验
        logger.warning(f"校验运行中任务失败（不阻断删除）: {e}")
    try:
        from app.automation.routes.delivery_router import _ACTIVE_DELIVERY_RECORD_IDS
        for rid in deleting_set & _ACTIVE_DELIVERY_RECORD_IDS:
            conflict_ids.append(rid)
    except Exception as e:
        logger.warning(f"校验投递台账失败（不阻断删除）: {e}")
    if conflict_ids:
        conflict_ids = list(dict.fromkeys(conflict_ids))
        raise HTTPException(
            status_code=409,
            detail=f"以下 {len(conflict_ids)} 个岗位正在执行批量任务，删除会污染任务状态，请等任务结束后再删: {', '.join(conflict_ids)}",
        )

    from app.core.feishu_client import feishu_client
    result = await feishu_client.batch_delete_records(
        table_id=settings.FEISHU_TABLE_ID_JOBS,
        record_ids=pure_record_ids
    )
    deleted_record_ids = result["deleted"]
    failed_record_ids = result["failed"]

    if not deleted_record_ids:
        # 一批都没删掉：带上飞书原因返回 502，前端展示 detail 而非笼统"未知错误"
        raise HTTPException(status_code=502, detail=f"飞书批量删除失败: {result['error'] or '未知原因'}")

    # 按 前端原始id ↔ 纯record_id 对应关系回传实际删除项（部分失败时前端只移除已删除的岗位）
    deleted_set = set(deleted_record_ids)
    deleted_frontend_ids = [jid for jid, rid in zip(job_ids, pure_record_ids, strict=False) if rid in deleted_set]

    # 级联清理已删除岗位的本地归档 Skill 运行多产物文件夹
    for rid in deleted_record_ids:
        try:
            from ai_agents.skills.skill_dirs import delete_job_results
            delete_job_results(rid)
        except Exception as e:
            logger.warning(f"级联删除岗位本地产物失败 {rid}: {e}")

    # 同步清理本地岗位缓存（内存 + 快照）
    try:
        from app.core.cache import JobCache
        JobCache.remove_records(deleted_record_ids)
    except Exception as e:
        logger.warning(f"同步清理 JobCache 失败: {e}")

    if failed_record_ids:
        message = f"成功删除 {len(deleted_record_ids)} 个岗位及本地 Skill 产物；{len(failed_record_ids)} 个删除失败（{result['error'] or '未知原因'}），已保留在飞书"
    else:
        message = f"成功删除 {len(deleted_record_ids)} 个岗位及本地 Skill 产物"
    return {
        "status": "success",
        "message": message,
        "data": {"deleted_ids": deleted_frontend_ids, "failed_count": len(failed_record_ids)},
    }

async def get_job_transcript(job_id: str) -> dict[str, Any]:
    pure_record_id = extract_record_id(job_id)
    record = await asyncio.to_thread(get_job_record_from_feishu, pure_record_id, settings.FEISHU_TABLE_ID_JOBS)
    transcript = ""
    if record and "fields" in record:
        transcript = feishu_field_to_plain_str(record["fields"].get("面试记录", ""))
    return {"status": "success", "transcript": transcript}

from datetime import datetime  # noqa: E402

from app.agents.coach_agent import generate_interview_feedback  # noqa: E402
from app.jobs.schemas import SaveTranscriptRequest  # noqa: E402


async def save_transcript_action(payload: SaveTranscriptRequest) -> dict[str, Any]:
    pure_record_id = extract_record_id(payload.job_id)

    if payload.is_overwrite:
        success = await asyncio.to_thread(
            update_feishu_record,
            record_id=pure_record_id,
            fields_to_update={"面试记录": payload.transcript},
            table_id=settings.FEISHU_TABLE_ID_JOBS
        )
        return {"status": "success" if success else "failed"}

    report_md = ""
    if payload.generate_report:
        try:
            report_md = await generate_interview_feedback(
                jd_text=payload.jd_text,
                transcript=payload.transcript,
                role=payload.role,
                style=payload.style
            )
        except Exception as e:
            print(f"[⚠️] 报告生成失败: {e}")

    # fetch existing record
    record = await asyncio.to_thread(get_job_record_from_feishu, pure_record_id, settings.FEISHU_TABLE_ID_JOBS)
    existing = ""
    if record and "fields" in record:
        existing = feishu_field_to_plain_str(record["fields"].get("面试记录", ""))

    import uuid
    session_id = f"sess_{int(datetime.now().timestamp())}_{uuid.uuid4().hex[:6]}"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    new_block = (
        f"<!-- RECORD_ID:{session_id} -->\n"
        f"### 🕒 面试练习记录 ({timestamp}) [ROLE:{payload.role}|STYLE:{payload.style}]\n"
        f"{payload.transcript}{report_md}\n\n---\n\n"
    )
    final_text = new_block + existing

    from app.core.feishu_client import feishu_client
    success = await feishu_client.update_record(
        table_id=settings.FEISHU_TABLE_ID_JOBS,
        record_id=pure_record_id,
        fields={"面试记录": final_text}
    )
    return {"status": "success" if success else "failed", "new_record": final_text}

from app.jobs.schemas import SaveManualResumeRequest  # noqa: E402


async def save_manual_resume_action(payload: SaveManualResumeRequest) -> dict[str, Any]:
    pure_record_id = extract_record_id(payload.job_id)
    from app.core.feishu_client import feishu_client
    from app.core.feishu_utils import (
        extract_feishu_text,
        is_terminal_or_post_delivery_status,
    )

    # 🛡️ 终态保护：若岗位已处于已投递、已放弃、清洗淘汰等终态，仅更新简历物料，严禁倒流为「简历人工复核」
    cur_status = (getattr(payload, "current_status", None) or "").strip()
    if not cur_status:
        try:
            from app.services.feishu_service import get_job_record_from_feishu
            rec = await asyncio.to_thread(get_job_record_from_feishu, pure_record_id, settings.FEISHU_TABLE_ID_JOBS)
            if rec and isinstance(rec.get("fields"), dict):
                cur_status = extract_feishu_text(rec["fields"].get("跟进状态", "")).strip()
        except Exception as e:
            logger.warning(f"获取岗位当前跟进状态异常(fail-safe): {e}")

    fields_to_update: dict[str, Any] = {"AI改写JSON": payload.resume_text}
    if is_terminal_or_post_delivery_status(cur_status):
        logger.info(f"🛡️ [save_manual_resume_action] 岗位 {pure_record_id} 当前处于已投递/终态({cur_status})，仅保存简历内容，不倒流跟进状态")
    else:
        fields_to_update["跟进状态"] = "简历人工复核"

    success = await feishu_client.update_record(
        table_id=settings.FEISHU_TABLE_ID_JOBS,
        record_id=pure_record_id,
        fields=fields_to_update,
    )
    if success:
        return {
            "status": "success",
            "message": "简历已保存到飞书" if is_terminal_or_post_delivery_status(cur_status) else "简历已保存并同步至复核队列",
            "job_id": payload.job_id
        }
    else:
        raise ValueError("保存简历到飞书失败")
from ai_agents.qa_evaluator import qa_evaluate_resume  # noqa: E402
from app.jobs.schemas import QAEvaluateRequest  # noqa: E402


async def evaluate_qa_action(payload: QAEvaluateRequest) -> dict[str, Any]:
    pure_record_id = extract_record_id(payload.job_id)

    try:
        qa_report = await asyncio.to_thread(
            qa_evaluate_resume,
            payload.job_description,
            payload.resume_text
        )
    except Exception as e:
        raise ValueError(f"LLM 调用失败: {str(e)}")

    if not qa_report:
        raise ValueError("LLM 返回了空的质检报告")

    try:
        import json

        from app.core.feishu_client import feishu_client
        qa_report_json_str = json.dumps(qa_report, ensure_ascii=False, indent=2) if isinstance(qa_report, dict) else qa_report
        success = await feishu_client.update_record(
            table_id=settings.FEISHU_TABLE_ID_JOBS,
            record_id=pure_record_id,
            fields={"二次质检报告": qa_report_json_str}
        )
        return {
            "status": "success",
            "message": "QA 评估完成",
            "job_id": payload.job_id,
            "qa_report_saved": success,
            "qa_report": qa_report
        }
    except Exception:
        return {
            "status": "success",
            "message": "QA 评估完成，但保存到飞书失败",
            "job_id": payload.job_id,
            "qa_report_saved": False,
            "qa_report": qa_report
        }
