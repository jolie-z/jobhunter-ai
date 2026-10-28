"""
多平台在线简历编辑器 - 单平台与选项 API 路由 (/api/resume-editor/*)
"""

import json
import os

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from .common import (
    DATA_DIR,
    DICT_DIR,
    PLATFORMS,
    WORK_FIELD_OPTIONS_MAP,
    atomic_write_json,
)

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
    """获取平台选项数据（只读字典，随包）"""
    file_path = os.path.join(DICT_DIR, f"{platform}_options.json")
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
    file_path = os.path.join(DICT_DIR, filename)
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
    file_path = os.path.join(DICT_DIR, "zhilian_language_certificates.json")
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
        file_path = os.path.join(DICT_DIR, "zhilian_work_skills_progress.json")
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
    """保存平台数据到本地 JSON（2026-10-23 起为模块级增量合并）。

    - 请求体只需携带变化的模块：顶层键整体替换同名模块，未提及的模块原样保留
      （根治「局部数据当全量发」把未带模块整份销毁的事故——测试桩曾把 17 模块的
      boss_fields.json 覆盖成 1 模块）；
    - 值为 null 表示删除该模块；整表清空请走 /clear-data；
    - 旧调用方发全量文档行为不变（全量 = 所有模块都被替换，结果与覆盖写等价）；
    - 现有文件损坏（解析失败/顶层非 dict）一律 fail-closed 500 拒绝合并，
      绝不降级当空文件（防「损坏文件被局部载荷二次销毁」）；
    - 写入前对旧文件做快照备份，响应 backup 字段带备份路径，误操作可回滚。
    """
    import logging
    _log = logging.getLogger(__name__)

    if not isinstance(data, dict):
        return JSONResponse(
            content={"success": False, "message": "保存载荷必须是模块字典（顶层键=模块名）"},
            status_code=400,
        )

    file_path = os.path.join(DATA_DIR, f"{platform}_fields.json")
    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        existing: dict | None = None
        if os.path.exists(file_path):
            try:
                with open(file_path, encoding="utf-8") as f:
                    loaded = json.load(f)
            except Exception as parse_e:
                _log.error(f"[save/{platform}] 本地数据损坏，fail-closed 拒绝合并: {file_path} ({parse_e})")
                raise HTTPException(
                    status_code=500,
                    detail=f"{platform} 本地数据损坏（{parse_e}），已拒绝合并写入。请先从 snapshots/ 快照恢复或重新采集重建后再保存。",
                )
            if not isinstance(loaded, dict):
                _log.error(f"[save/{platform}] 本地数据顶层非模块字典（{type(loaded).__name__}），fail-closed 拒绝合并: {file_path}")
                raise HTTPException(
                    status_code=500,
                    detail=f"{platform} 本地数据格式异常（顶层为 {type(loaded).__name__} 而非模块字典），已拒绝合并写入。请先从 snapshots/ 快照恢复或重新采集重建。",
                )
            existing = loaded

        from .common import merge_platform_fields
        merged = merge_platform_fields(existing, data)

        # 空载荷 = 真 no-op（code-review P2 采纳）：跳过备份与落盘，不推高文件 mtime
        if not data:
            return JSONResponse(content={
                "success": True,
                "message": f"{platform}无可变更模块，未执行写入",
                "modules": len(merged),
                "backup": None,
            })

        # 覆盖前备份旧文件（与采集落盘/writeback-save 同款保险）；失败不阻断保存
        backup_path: str | None = None
        if existing is not None:
            try:
                from resume_editor.platforms.browser_common import backup_json_file
                backup_path = backup_json_file(file_path, f"{platform}_save")
                _log.info(f"[save/{platform}] 已备份旧数据: {backup_path}")
            except Exception as bk_e:
                backup_path = None
                _log.warning(f"[save/{platform}] 保存前备份失败（不阻断保存）: {bk_e}")

        atomic_write_json(file_path, merged)
        note = "" if backup_path else "（未生成备份快照）"
        return JSONResponse(content={
            "success": True,
            "message": f"{platform}数据已保存（增量合并，共 {len(merged)} 个模块）{note}",
            "modules": len(merged),
            "backup": backup_path,
        })
    except HTTPException:
        raise
    except ValueError as ve:
        return JSONResponse(content={"success": False, "message": str(ve)}, status_code=400)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
