"""
Skills API Router - Resume Dynamic Skills
===========================================
提供简历改写技能的 CRUD、多格式安全导入（.md / .zip / 文件夹 / GitHub 仓库）和执行功能
"""

import os
import sys

from fastapi import (
    APIRouter,
    Form,
    HTTPException,
)
from fastapi.responses import JSONResponse

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from ai_agents.skills.skill_loader import get_skill_manager

router = APIRouter(prefix="/resume-editor/skills", tags=["动态技能管理"])

# 上传/导入端点拆分至 skills_upload（500 行纪律）；include 置于既有路由注册前，
# 子路由无前缀，最终路径 /api/resume-editor/skills/* 不变
from app.api.routes.skills_upload import router as skills_upload_router  # noqa: E402

router.include_router(skills_upload_router)



@router.get("/")
async def list_available_skills():
    """列出所有可用的简历改写技能（包含单文件与多文件技能包，精准过滤掉 greeting 等非简历技能）"""
    try:
        manager = get_skill_manager()
        raw_skills = manager.list_skills()

        # 🌟 过滤：仅保留简历改写相关 Skill，彻底排除 greeting_writer 等打招呼语技能
        skills_list = [
            s for s in raw_skills
            if not s.get("id", "").startswith("greeting_") and s.get("id") != "greeting_writer"
        ]

        current_skill_id = manager.current_skill_id
        if not current_skill_id or current_skill_id.startswith("greeting_") or current_skill_id == "greeting_writer":
            default_skill = manager.get_default_skill()
            if default_skill and not default_skill.id.startswith("greeting_") and default_skill.id != "greeting_writer":
                current_skill_id = default_skill.id
            elif skills_list:
                current_skill_id = skills_list[0].get("id")

        return {
            "success": True,
            "skills": skills_list,
            "current_skill_id": current_skill_id,
            "count": len(skills_list)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/default")
async def get_default_skill():
    """获取默认技能的元数据"""
    try:
        manager = get_skill_manager()
        default_skill = manager.get_default_skill()

        if not default_skill:
            raise HTTPException(status_code=404, detail="No default skill found")

        return {
            "success": True,
            "skill": {
                "id": default_skill.id,
                "name": default_skill.name,
                "version": default_skill.version,
                "description": default_skill.description,
                "is_package": default_skill.is_package,
                "references_count": default_skill.references_count,
                "file": default_skill.file_path.name
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse(
            content={"success": False, "error": str(e)},
            status_code=500
        )


@router.get("/{skill_id}")
async def get_skill_detail(skill_id: str):
    """获取指定技能的详细信息（含组装后的 Prompt 与 Reference 资料清单）"""
    try:
        manager = get_skill_manager()

        if skill_id not in manager.skills:
            raise HTTPException(
                status_code=404,
                detail=f"Skill not found: {skill_id}"
            )

        skill_meta = manager.skills[skill_id]
        assembled_content = manager.get_skill_content(skill_id)

        return {
            "success": True,
            "skill": {
                "id": skill_meta.id,
                "name": skill_meta.name,
                "version": skill_meta.version,
                "description": skill_meta.description,
                "file": skill_meta.file_path.name,
                "path": str(skill_meta.file_path),
                "is_package": skill_meta.is_package,
                "is_official": skill_meta.is_official,
                "references_count": skill_meta.references_count,
                "reference_names": skill_meta.reference_names,
                "loaded_at": skill_meta.created_at.isoformat(),
                "content_preview": assembled_content[:600] + "..." if assembled_content else None,
                "full_content_length": len(assembled_content) if assembled_content else 0
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse(
            content={"success": False, "error": str(e)},
            status_code=500
        )



@router.post("/execute/{skill_id}")
async def execute_skill(
    skill_id: str,
    resume_data: str = Form(...),
    jd_text: str = Form(""),
    include_diagnosis: str = Form("true")
):
    """执行技能进行简历改写"""
    try:
        import json

        from ai_agents.skill_executor import execute_skill_execution

        resume_dict = json.loads(resume_data) if resume_data else {}
        include_diag = include_diagnosis.lower() == "true"

        manager = get_skill_manager()
        if skill_id not in manager.skills:
            raise HTTPException(
                status_code=404,
                detail=f"Skill not found: {skill_id}"
            )

        result = execute_skill_execution(
            job_record_id="dynamic-skill-task",
            skill_id=skill_id,
            resume_data=resume_dict,
            include_diagnosis=include_diag,
            jd_text=jd_text or ""
        )

        return {
            "success": True,
            "skill_id": skill_id,
            "task_id": result.get("task_id"),
            "storage_dir": result.get("storage_dir"),
            "token_used": result.get("token_used"),
            "message": "Skill execution started"
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
