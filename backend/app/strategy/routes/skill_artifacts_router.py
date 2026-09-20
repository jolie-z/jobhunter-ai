import logging

from fastapi import APIRouter, HTTPException

from app.services.feishu_service import extract_record_id

logger = logging.getLogger("strategy_skill_artifacts_router")
logger.setLevel(logging.INFO)

router = APIRouter()


def _artifact_id_candidates(job_id: str) -> list[str]:
    """产物目录双口径解析（Q-M4-1）：

    写入侧历史存在两种口径——
    - 异步改写通道（岗位模式主通道）按调用方完整 jobId 建目录，如 `BOSS直聘-rec123`
      （skill_agent_router: target_job_id = payload.job_id 原样落盘）；
    - 同步通道按 extract_record_id 清洗后的纯 record_id 建目录（如 `rec123`）。
    读取/删除侧对两种口径都尝试，保证两类产物都可见、可清理；同 id 自动去重。
    非法/穿越路径段直接剔除，可能返回空列表（上层各路由安全空转，绝不回落 default 目录）。
    """
    candidates: list[str] = []
    raw = (job_id or "").strip()
    if raw:
        candidates.append(raw)
    cleaned = extract_record_id(raw)
    if cleaned and cleaned not in candidates:
        candidates.append(cleaned)

    # 防御纵深：路径穿越/非法路径段在候选层即剔除（目录拼接层 _is_safe_segment 还有二次兜底）。
    # 过滤后为空时返回空列表（各路由自然空转：list=空数据 / get=404 / delete=False），
    # 绝不 fallback 到 "default" 公共目录——否则非法输入会经 delete 路由误清空默认产物（R1 审查 P1）
    from ai_agents.skills.skill_dirs import _is_safe_segment

    return [c for c in candidates if _is_safe_segment(c)]


@router.get("/skill_artifacts/{job_id}")
async def list_skill_artifacts_api(job_id: str, skill_id: str | None = None):
    """获取指定 job 在本地归档的所有 Skill 产物清单（双口径目录合并去重）"""
    try:
        from ai_agents.skills.skill_dirs import list_job_skill_artifacts

        artifacts: list[dict] = []
        seen_paths: set[str] = set()
        for cid in _artifact_id_candidates(job_id):
            for item in list_job_skill_artifacts(cid, skill_id):
                path = item.get("path")
                if path and path in seen_paths:
                    continue
                if path:
                    seen_paths.add(path)
                artifacts.append(item)
        return {"status": "success", "data": artifacts}
    except Exception as e:
        logger.exception(f"list_skill_artifacts_api error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/skill_artifacts/{job_id}/{skill_id}/{filename}")
async def get_skill_artifact_content_api(job_id: str, skill_id: str, filename: str):
    """获取指定 Skill 产物文件 Markdown 原始内容（按双口径目录依次查找）"""
    try:
        from ai_agents.skills.skill_dirs import get_artifact_content

        content = None
        for cid in _artifact_id_candidates(job_id):
            content = get_artifact_content(cid, skill_id, filename)
            if content is not None:
                break
        if content is None:
            raise HTTPException(status_code=404, detail="Artifact not found")
        return {"status": "success", "data": {"content": content, "filename": filename}}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"get_skill_artifact_content_api error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/skill_artifacts/{job_id}")
async def delete_job_artifacts_api(job_id: str):
    """用户主动清空该岗位下的所有 Skill 运行本地产物（双口径目录都清）"""
    try:
        from ai_agents.skills.skill_dirs import delete_job_results

        success = False
        for cid in _artifact_id_candidates(job_id):
            if delete_job_results(cid):
                success = True
        return {"status": "success", "message": "已清空该岗位所有本地产物", "data": {"deleted": success}}
    except Exception as e:
        logger.exception(f"delete_job_artifacts_api error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/skill_artifacts/{job_id}/{skill_id}")
async def delete_skill_artifacts_api(job_id: str, skill_id: str):
    """用户主动清空该岗位下指定 Skill 的所有产物（双口径目录都清）"""
    try:
        from ai_agents.skills.skill_dirs import delete_skill_result

        success = False
        for cid in _artifact_id_candidates(job_id):
            if delete_skill_result(cid, skill_id):
                success = True
        return {"status": "success", "message": f"已清空技能 {skill_id} 的本地产物", "data": {"deleted": success}}
    except Exception as e:
        logger.exception(f"delete_skill_artifacts_api error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/skill_artifacts/{job_id}/{skill_id}/{filename}")
async def delete_single_artifact_api(job_id: str, skill_id: str, filename: str):
    """用户主动删除单个产物文件（按双口径目录依次查找删除）"""
    try:
        from ai_agents.skills.skill_dirs import delete_single_artifact

        success = False
        for cid in _artifact_id_candidates(job_id):
            if delete_single_artifact(cid, skill_id, filename):
                success = True
                break
        if not success:
            raise HTTPException(status_code=404, detail="文件不存在或删除失败")
        return {"status": "success", "message": f"已删除文件 {filename}", "data": {"deleted": True}}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"delete_single_artifact_api error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
