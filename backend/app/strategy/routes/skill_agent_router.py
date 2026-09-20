import asyncio
import json
import logging
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.core.config import settings
from app.core.feishu_client import feishu_client
from app.jobs.task_manager import task_event_manager
from app.services.feishu_service import extract_record_id

logger = logging.getLogger("strategy_skill_agent_router")
logger.setLevel(logging.INFO)

router = APIRouter()


class TestSkillRewriteRequest(BaseModel):
    job_id: str
    jd_text: str
    job_name: str
    skill_id: str | None = None
    include_diagnosis: bool = True


class SkillRewriteAndSaveRequest(BaseModel):
    job_id: str = ""
    jd_text: str = ""
    job_name: str = ""
    resume_record_id: str | None = None
    skill_id: str | None = None
    include_diagnosis: bool = True


def _safe_extract_text(field_val):
    if not field_val:
        return ""
    if isinstance(field_val, list):
        return "".join([str(item.get("text", "")) if isinstance(item, dict) else str(item) for item in field_val])
    return str(field_val)


@router.post("/test_skill_rewrite")
async def test_skill_rewrite_api(payload: TestSkillRewriteRequest):
    """单独测试新版 Skill 简历改写功能"""
    try:
        from ai_agents.engine_facade import process_resume_rewrite

        diagnosis_dict = {}
        if payload.include_diagnosis:
            try:
                clean_id = extract_record_id(payload.job_id)
                record = await feishu_client.get_record(settings.FEISHU_TABLE_ID_JOBS, clean_id)
                if record:
                    fields = record.get("fields", {})
                    analysis_report = _safe_extract_text(fields.get("深度分析诊断报告(AI)"))
                    if analysis_report:
                        diagnosis_dict = json.loads(analysis_report)
                    else:
                        diagnosis_dict = {
                            "dream_picture": _safe_extract_text(fields.get("理想画像与能力信号")),
                            "ats_ability_analysis": _safe_extract_text(fields.get("核心能力词典")),
                            "resume_audit": _safe_extract_text(fields.get("简历逐行审计")),
                            "strong_fit_assessment": _safe_extract_text(fields.get("高杠杆匹配点")),
                            "risk_red_flags": _safe_extract_text(fields.get("致命硬伤与毒点")),
                            "deep_action_plan": _safe_extract_text(fields.get("破局行动计划")),
                        }
            except Exception as e:
                logger.warning(f"test_skill_rewrite_api 无法读取诊断报告: {e}")

        final_md, usage = await asyncio.to_thread(
            process_resume_rewrite,
            jd_text=payload.jd_text,
            diagnosis_dict=diagnosis_dict,
            job_name=payload.job_name,
            rewrite_mode="skill",
            skill_id=payload.skill_id or "",
            include_diagnosis=payload.include_diagnosis,
        )
        return {"status": "success", "data": {"markdown": final_md, "usage": usage}}
    except Exception as e:
        logger.exception(f"test_skill_rewrite error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/skill_rewrite_and_save")
async def skill_rewrite_and_save_api(payload: SkillRewriteAndSaveRequest):
    """正式版 Skill 简历改写（带 Markdown 转 JSON 与数据库落盘）"""
    try:
        from ai_agents.engine_facade import process_resume_rewrite

        if payload.resume_record_id:
            if not payload.resume_record_id.startswith("rec"):
                raise HTTPException(
                    status_code=400,
                    detail="该简历尚未同步到飞书（本地草稿），请先在简历库点击「保存并同步」后再改写",
                )
        elif not payload.job_id:
            raise HTTPException(
                status_code=400,
                detail="需要提供 job_id（岗位模式）或 resume_record_id（简历库模式）",
            )

        diagnosis_dict = {}
        original_personal_info: dict = {}
        resume_override = ""
        clean_id = ""
        clean_rid = ""

        # ===== 1. 诊断报告 =====
        if payload.job_id:
            clean_id = extract_record_id(payload.job_id)
            record = await feishu_client.get_record(settings.FEISHU_TABLE_ID_JOBS, clean_id)
            if not record and not payload.resume_record_id:
                raise HTTPException(status_code=404, detail="Job not found")
            if record:
                fields = record.get("fields", {})
                analysis_report = _safe_extract_text(fields.get("深度分析诊断报告(AI)"))
                if analysis_report:
                    try:
                        diagnosis_dict = json.loads(analysis_report)
                    except json.JSONDecodeError:
                        pass
                if not diagnosis_dict:
                    diagnosis_dict = {
                        "dream_picture": _safe_extract_text(fields.get("理想画像与能力信号")),
                        "ats_ability_analysis": _safe_extract_text(fields.get("核心能力词典")),
                        "resume_audit": _safe_extract_text(fields.get("简历逐行审计")),
                        "strong_fit_assessment": _safe_extract_text(fields.get("高杠杆匹配点")),
                        "risk_red_flags": _safe_extract_text(fields.get("致命硬伤与毒点")),
                        "deep_action_plan": _safe_extract_text(fields.get("破局行动计划")),
                    }

        # ===== 2. 底稿与隐私数据 =====
        if payload.resume_record_id:
            if not payload.jd_text.strip():
                raise HTTPException(status_code=400, detail="简历库模式需要提供 jd_text（如 A级岗位画像）")
            clean_rid = extract_record_id(payload.resume_record_id)
            resume_rec = await feishu_client.get_record(settings.FEISHU_TABLE_ID_RESUMES, clean_rid)
            if not resume_rec:
                raise HTTPException(status_code=404, detail="简历记录不存在")
            raw_structured = _safe_extract_text(resume_rec.get("fields", {}).get("结构化数据", ""))
            if not raw_structured.strip():
                raise HTTPException(status_code=400, detail="该简历没有结构化数据，无法作为改写底稿")
            try:
                src_dict = json.loads(raw_structured)
            except Exception:
                raise HTTPException(status_code=500, detail="结构化数据不是合法 JSON，无法改写")
            original_personal_info = src_dict.pop("personalInfo", {}) or {}
            resume_override = json.dumps(src_dict, ensure_ascii=False)
        else:
            try:
                import httpx

                token = await feishu_client.get_tenant_access_token()
                if token:
                    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{settings.FEISHU_APP_TOKEN}/tables/{settings.FEISHU_TABLE_ID_RESUMES}/records/search"
                    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
                    payload_search = {
                        "filter": {
                            "conjunction": "and",
                            "conditions": [{"field_name": "当前状态", "operator": "is", "value": ["启用"]}],
                        }
                    }
                    async with httpx.AsyncClient() as client:
                        resp = await client.post(url, headers=headers, json=payload_search, timeout=10)
                        resp.raise_for_status()
                        items = resp.json().get("data", {}).get("items", [])
                        if items:
                            raw_text = _safe_extract_text(items[0].get("fields", {}).get("结构化数据", ""))
                            if raw_text:
                                data_dict = json.loads(raw_text)
                                original_personal_info = data_dict.get("personalInfo", {})
            except Exception as e:
                logger.error(f"拉取简历库并剥离个人隐私数据失败: {e}")
                raise HTTPException(status_code=502, detail=f"拉取飞书简历数据失败，请重试: {e}")

        # ===== 3. 执行推演 =====
        final_md, usage = await asyncio.to_thread(
            process_resume_rewrite,
            jd_text=payload.jd_text,
            diagnosis_dict=diagnosis_dict,
            job_name=payload.job_name,
            rewrite_mode="skill",
            original_resume_override=resume_override,
            skill_id=payload.skill_id or "",
            include_diagnosis=payload.include_diagnosis,
            job_record_id=clean_id or clean_rid or "default",
        )

        if not final_md or final_md.lstrip().startswith("❌"):
            logger.error(f"skill_rewrite_and_save: 引擎返回错误文本，拒绝落盘: {str(final_md)[:200]}")
            raise HTTPException(status_code=502, detail=str(final_md)[:300])

        # ===== 4. 轻量级解析转 JSON + 缝合隐私数据 =====
        from ai_agents.markdown_to_json import parse_markdown_to_json

        parsed_json = await asyncio.to_thread(parse_markdown_to_json, final_md)

        # 本地多产物归档安全备份
        try:
            from ai_agents.skills.skill_dirs import (
                extract_files_from_skill_output,
                save_skill_result,
            )

            target_job_id = clean_id or clean_rid or "default"
            target_skill_id = payload.skill_id or "default"
            artifact_files = extract_files_from_skill_output(final_md)

            save_skill_result(
                job_record_id=target_job_id,
                skill_id=target_skill_id,
                files=artifact_files,
                token_usage=usage if isinstance(usage, dict) else {},
                output_type="multi_markdown",
            )
        except Exception as e:
            logger.warning(f"保存 Skill 运行本地归档失败: {e}")

        if not original_personal_info:
            original_personal_info = {
                "name": "未填写",
                "phone": "未填写",
                "email": "未填写",
                "location": "未填写",
            }

        if "personalInfo" not in parsed_json or not parsed_json["personalInfo"]:
            parsed_json["personalInfo"] = original_personal_info
        else:
            parsed_json["personalInfo"].update(original_personal_info)

        # ===== 5. 落盘飞书 =====
        ai_rewrite_json_str = json.dumps(parsed_json, ensure_ascii=False)
        if payload.resume_record_id:
            try:
                backup_dir = Path(__file__).resolve().parent.parent.parent.parent / "data" / "resume_backups"
                backup_dir.mkdir(parents=True, exist_ok=True)
                backup_name = f"{clean_rid}_{time.strftime('%Y%m%d_%H%M%S')}_before_rewrite.json"
                (backup_dir / backup_name).write_text(raw_structured or "{}", encoding="utf-8")
            except Exception as e:
                logger.warning(f"改写前备份旧结构化数据失败: {e}")

            success = await feishu_client.update_record(
                table_id=settings.FEISHU_TABLE_ID_RESUMES,
                record_id=clean_rid,
                fields={"结构化数据": ai_rewrite_json_str},
            )
            if not success:
                raise HTTPException(status_code=502, detail="改写已完成，但写回简历库失败。请稍后重试")
        else:
            success = await feishu_client.update_record(
                table_id=settings.FEISHU_TABLE_ID_JOBS,
                record_id=clean_id,
                fields={
                    "AI改写JSON": ai_rewrite_json_str,
                    "跟进状态": "简历人工复核",
                },
            )
            if not success:
                raise HTTPException(status_code=502, detail="改写已完成，但写回岗位记录失败。请稍后重试")

        return {
            "status": "success",
            "data": {
                "parsed_json": parsed_json,
                "markdown": final_md,
                "usage": usage,
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"skill_rewrite_and_save error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/skill_rewrite_async")
async def skill_rewrite_async_api(payload: SkillRewriteAndSaveRequest):
    """异步启动 Skill 改写智能体，立即返回 task_id，并通过 /skill_agent_logs 开启 SSE 实时推演流"""
    task_id = f"skill_task_{uuid.uuid4().hex[:12]}"
    queue = task_event_manager.register_task(task_id)

    async def _run_skill_worker():
        try:
            queue.put_nowait({
                "type": "init",
                "task_id": task_id,
                "message": "🚀 正在初始化 Skill 智能体改写任务...",
                "job_name": payload.job_name,
                "skill_id": payload.skill_id or "default",
            })

            from ai_agents.engine_facade import process_resume_rewrite

            clean_id = (payload.job_id or "").strip()
            clean_rid = (payload.resume_record_id or "").strip()
            diagnosis_dict = {}
            original_personal_info: dict = {}
            resume_override = ""

            if not payload.resume_record_id and clean_id:
                try:
                    job_record = await feishu_client.get_record(settings.FEISHU_TABLE_ID_JOBS, clean_id)
                    fields = job_record.get("fields", {})
                    raw_diag = fields.get("AI诊断报告", "")
                    if isinstance(raw_diag, str) and raw_diag.strip():
                        try:
                            diagnosis_dict = json.loads(raw_diag)
                        except Exception:
                            pass
                except Exception as e:
                    logger.warning(f"获取岗位诊断失败: {e}")

            if payload.resume_record_id and clean_rid:
                try:
                    resume_record = await feishu_client.get_record(settings.FEISHU_TABLE_ID_RESUMES, clean_rid)
                    raw_struct = _safe_extract_text(resume_record.get("fields", {}).get("结构化数据", ""))
                    if raw_struct:
                        data_dict = json.loads(raw_struct)
                        original_personal_info = data_dict.pop("personalInfo", {}) or {}
                        resume_override = json.dumps(data_dict, ensure_ascii=False)
                except Exception as e:
                    logger.warning(f"获取简历库数据失败: {e}")

            if not original_personal_info:
                try:
                    from app.services.feishu_service import FeishuService

                    fs = FeishuService()
                    token = await fs.get_tenant_access_token()
                    if token:
                        import httpx

                        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{settings.FEISHU_APP_TOKEN}/tables/{settings.FEISHU_TABLE_ID_RESUMES}/records/search"
                        headers = {
                            "Authorization": f"Bearer {token}",
                            "Content-Type": "application/json; charset=utf-8",
                        }
                        payload_search = {
                            "filter": {
                                "conjunction": "and",
                                "conditions": [{"field_name": "当前状态", "operator": "is", "value": ["启用"]}],
                            }
                        }
                        async with httpx.AsyncClient() as client:
                            resp = await client.post(url, headers=headers, json=payload_search, timeout=10)
                            if resp.status_code == 200:
                                items = resp.json().get("data", {}).get("items", [])
                                if items:
                                    raw_text = _safe_extract_text(items[0].get("fields", {}).get("结构化数据", ""))
                                    if raw_text:
                                        data_dict = json.loads(raw_text)
                                        original_personal_info = data_dict.get("personalInfo", {})
                except Exception as e:
                    logger.warning(f"获取启用简历隐私失败: {e}")

            def on_agent_event(event_type: str, data: dict):
                queue.put_nowait({"type": event_type, "timestamp": time.time(), **data})

            final_md, usage = await asyncio.to_thread(
                process_resume_rewrite,
                jd_text=payload.jd_text,
                diagnosis_dict=diagnosis_dict,
                job_name=payload.job_name,
                rewrite_mode="skill",
                original_resume_override=resume_override,
                skill_id=payload.skill_id or "",
                include_diagnosis=payload.include_diagnosis,
                job_record_id=clean_id or clean_rid or "default",
                on_event=on_agent_event,
            )

            if not final_md or final_md.lstrip().startswith("❌"):
                queue.put_nowait({
                    "type": "error",
                    "detail": str(final_md)[:300],
                    "message": f"❌ 改写失败: {str(final_md)[:150]}",
                })
                return

            from ai_agents.markdown_to_json import parse_markdown_to_json

            parsed_json = await asyncio.to_thread(parse_markdown_to_json, final_md)

            try:
                from ai_agents.skills.skill_dirs import (
                    extract_files_from_skill_output,
                    save_skill_result,
                )

                target_job_id = clean_id or clean_rid or "default"
                target_skill_id = payload.skill_id or "default"
                artifact_files = extract_files_from_skill_output(final_md)
                save_skill_result(
                    job_record_id=target_job_id,
                    skill_id=target_skill_id,
                    files=artifact_files,
                    token_usage=usage if isinstance(usage, dict) else {},
                    output_type="multi_markdown",
                )
            except Exception:
                pass

            if not original_personal_info:
                original_personal_info = {
                    "name": "未填写",
                    "phone": "未填写",
                    "email": "未填写",
                    "location": "未填写",
                }

            if "personalInfo" not in parsed_json or not parsed_json["personalInfo"]:
                parsed_json["personalInfo"] = original_personal_info
            else:
                parsed_json["personalInfo"].update(original_personal_info)

            ai_rewrite_json_str = json.dumps(parsed_json, ensure_ascii=False)
            if payload.resume_record_id:
                saved = await feishu_client.update_record(
                    table_id=settings.FEISHU_TABLE_ID_RESUMES,
                    record_id=clean_rid,
                    fields={"结构化数据": ai_rewrite_json_str},
                )
            else:
                saved = await feishu_client.update_record(
                    table_id=settings.FEISHU_TABLE_ID_JOBS,
                    record_id=clean_id,
                    fields={"AI改写JSON": ai_rewrite_json_str, "跟进状态": "简历人工复核"},
                )
            if not saved:
                queue.put_nowait({
                    "type": "error",
                    "detail": "改写完成但写回飞书失败",
                    "message": "❌ 改写已完成，但写回失败，请稍后重试",
                })
                return

            queue.put_nowait({
                "type": "complete",
                "status": "success",
                "message": "🎉 改写与多产物归档全部完成！",
                "data": {
                    "parsed_json": parsed_json,
                    "markdown": final_md,
                    "usage": usage,
                },
            })

        except Exception as e:
            logger.exception(f"Async skill worker error: {e}")
            queue.put_nowait({"type": "error", "detail": str(e), "message": f"❌ 智能体推演异常: {e}"})
        finally:
            queue.put_nowait(None)

    asyncio.create_task(_run_skill_worker())

    return {
        "status": "success",
        "task_id": task_id,
        "message": "Skill 智能体推演任务已成功创建，请连接 SSE 日志流。",
    }


@router.get("/skill_agent_logs")
async def skill_agent_logs_api(task_id: str = Query(..., description="异步改写任务ID")):
    """Skill 智能体 SSE 实时推演日志流"""
    queue = task_event_manager.get_queue(task_id)
    if not queue:
        raise HTTPException(status_code=404, detail="未找到对应的活动任务流，请确认任务是否已过期或未启动")

    async def event_generator():
        try:
            while True:
                event = await queue.get()
                if event is None:
                    yield 'data: {"type": "close", "message": "Stream closed."}\n\n'
                    break
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                queue.task_done()
        except asyncio.CancelledError:
            logger.info(f"SSE connection cancelled for task {task_id}")
        finally:
            task_event_manager.remove_task(task_id)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
