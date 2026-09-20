"""
多平台在线简历编辑器 - 单平台与选项 API 路由 (/api/resume-editor/*)
"""

import json
import os

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from .common import DATA_DIR, PLATFORMS, WORK_FIELD_OPTIONS_MAP, atomic_write_json

router = APIRouter(prefix="/api/resume-editor", tags=["简历编辑器-单平台"])

# 内存缓存
_work_skills_cache = None
_lang_certs_cache = None


@router.get("/all")
def get_all_resumes():
    """获取所有平台简历数据"""
    result = {}
    for platform in PLATFORMS:
        file_path = os.path.join(DATA_DIR, f"{platform}_fields.json")
        try:
            if os.path.exists(file_path):
                with open(file_path, encoding="utf-8") as f:
                    result[platform] = json.load(f)
            else:
                result[platform] = None
        except Exception as e:
            result[platform] = {"error": str(e)}
    return JSONResponse(content={"success": True, "data": result})


@router.get("/options/{platform}")
def get_options(platform: str):
    """获取平台选项数据"""
    file_path = os.path.join(DATA_DIR, f"{platform}_options.json")
    try:
        if os.path.exists(file_path):
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)
            return JSONResponse(content={"success": True, "data": data})
        else:
            return JSONResponse(
                content={"success": False, "message": f"{platform}选项数据不存在"},
                status_code=404,
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/options/{platform}/{field}")
def get_field_options(platform: str, field: str):
    """获取平台特定字段的选项列表（职位/技能/行业等）"""
    field_map = WORK_FIELD_OPTIONS_MAP.get(platform)
    if not field_map:
        return JSONResponse(content={"success": False, "message": f"不支持的平台: {platform}"}, status_code=404)
    filename = field_map.get(field)
    if not filename:
        return JSONResponse(content={"success": False, "message": f"不支持的字段: {field}"}, status_code=404)
    file_path = os.path.join(DATA_DIR, filename)
    try:
        if os.path.exists(file_path):
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)
            return JSONResponse(content={"success": True, "data": data})
        else:
            return JSONResponse(content={"success": False, "message": f"选项文件不存在: {filename}"}, status_code=404)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/zhilian/language-certificates/{lang_code}")
def get_language_certificates(lang_code: int):
    """获取指定语种的证书列表"""
    file_path = os.path.join(DATA_DIR, "zhilian_language_certificates.json")
    try:
        if os.path.exists(file_path):
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)
            lang_data = data.get(str(lang_code))
            if lang_data:
                return JSONResponse(content={"success": True, "data": lang_data.get("certificates", [])})
            else:
                return JSONResponse(content={"success": True, "data": []})
        else:
            return JSONResponse(content={"success": False, "message": "证书数据不存在"}, status_code=404)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/zhilian/work-skills/{job_type_id}")
def get_zhilian_work_skills(job_type_id: str):
    """根据职位code获取对应的工作技能标签数据"""
    global _work_skills_cache
    if _work_skills_cache is None:
        file_path = os.path.join(DATA_DIR, "zhilian_work_skills_progress.json")
        if os.path.exists(file_path):
            with open(file_path, encoding="utf-8") as f:
                _work_skills_cache = json.load(f)
        else:
            _work_skills_cache = {}
    entry = _work_skills_cache.get(job_type_id)
    if entry and entry.get("skills"):
        return JSONResponse(content={"success": True, "data": entry["skills"]})
    return JSONResponse(content={"success": True, "data": []})


@router.get("/total")
def get_total():
    """获取总简历数据"""
    file_path = os.path.join(DATA_DIR, "total_fields.json")
    try:
        if os.path.exists(file_path):
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)
            return JSONResponse(content={"success": True, "data": data})
        else:
            return JSONResponse(content={"success": True, "data": {}})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/total/save")
def save_total(data: dict):
    """保存总简历数据"""
    file_path = os.path.join(DATA_DIR, "total_fields.json")
    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        atomic_write_json(file_path, data)
        return JSONResponse(content={"success": True, "message": "总简历数据已保存"})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{platform}")
def get_resume(platform: str):
    """获取指定平台的简历数据"""
    file_path = os.path.join(DATA_DIR, f"{platform}_fields.json")
    try:
        if os.path.exists(file_path):
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)
            return JSONResponse(content={"success": True, "data": data})
        else:
            return JSONResponse(
                content={"success": False, "message": f"{platform}简历数据不存在"},
                status_code=404,
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/save/{platform}")
def save_resume(platform: str, data: dict):
    """保存平台数据到本地 JSON"""
    file_path = os.path.join(DATA_DIR, f"{platform}_fields.json")
    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        atomic_write_json(file_path, data)
        return JSONResponse(content={"success": True, "message": f"{platform}数据已保存"})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
