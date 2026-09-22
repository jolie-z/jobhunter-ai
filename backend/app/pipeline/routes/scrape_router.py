import asyncio
import json as _json
import logging
import re as _re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.config import settings
from app.core.llm_client import get_openai_client
from app.pipeline import (
    add_keyword_history,
    delete_keyword_history,
    find_keyword_history,
    get_scrape_config,
    list_keyword_history,
    save_scrape_config,
)
from app.services.feishu_service import get_active_resume_from_feishu
from app.session.browser import (
    EdgeNotFoundError,
    edge_not_installed_detail,
    launch_edge,
)
from app.session.registry import resolve_platform

logger = logging.getLogger("pipeline_scrape_router")
logger.setLevel(logging.INFO)

MAX_KEYWORD_QUEUE = 10

router = APIRouter()


class KeywordItem(BaseModel):
    keyword: str
    salary: str = "不限"
    city: str = ""


class ScrapeConfigBody(BaseModel):
    keywords: list[KeywordItem] = []
    platforms: dict = {}
    default_city: str = ""
    default_salary: str = ""


class RunScrapeOnlyBody(BaseModel):
    platforms_limit: int | None = 10
    keyword: str | None = None
    city: str | None = None
    salary: str | None = None
    platforms: list[str] | None = None


class LaunchPlatformBody(BaseModel):
    platform: str


class ArchiveItem(BaseModel):
    keyword: str
    city: str = ""
    salary: str = ""


class ResetConditionBody(BaseModel):
    keyword: str
    city: str = ""
    salary: str = ""
    platform: str | None = None


@router.get("/scrape-config")
def read_scrape_config():
    data = get_scrape_config()
    return {"code": 0, "data": data}


@router.put("/scrape-config")
def write_scrape_config(body: ScrapeConfigBody):
    if len(body.keywords) > MAX_KEYWORD_QUEUE:
        raise HTTPException(
            status_code=400,
            detail=f"条件队列最多 {MAX_KEYWORD_QUEUE} 组，请先删减或归档再保存",
        )
    keywords = [k.model_dump() for k in body.keywords]
    data = save_scrape_config(
        keywords=keywords,
        platforms=body.platforms,
        default_city=body.default_city,
        default_salary=body.default_salary,
    )
    return {"code": 0, "data": data, "msg": "保存成功"}


@router.post("/run-scrape-only")
async def trigger_scrape_stage_only(body: RunScrapeOnlyBody | None = None):
    """单独执行「平台抓取」阶段（用于在抓取设置面板单独试跑，跳过后续清洗/评估/投递）"""
    from app.automation.full_auto import run_scrape_stage_only

    req = body or RunScrapeOnlyBody()
    try:
        task_id = await run_scrape_stage_only(
            platforms_limit=req.platforms_limit,
            keyword=req.keyword,
            city=req.city,
            salary=req.salary,
            platforms=req.platforms,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {
        "code": 0,
        "msg": "平台抓取模块已启动",
        "data": {"task_id": task_id},
    }


@router.get("/platform-sessions")
async def get_platform_sessions_endpoint():
    """获取 5 平台（Boss, 智联, 51job, 猎聘, 小红书）的实时会话健康状态与端口监听状态"""
    logger.info("🔍 [PLATFORM_SESSIONS] 收到会话状态全量检测请求")
    from app.session.browser import get_all_platform_sessions

    sessions = await asyncio.to_thread(get_all_platform_sessions)
    logger.info(
        f"✅ [PLATFORM_SESSIONS] 会话状态检测完成，共 {len(sessions)} 个平台: {[s.get('platform', '') + ':' + s.get('state', '') for s in sessions]}"
    )
    return {"code": 0, "data": sessions}


@router.post("/platform-sessions/launch")
def launch_platform_session_endpoint(body: LaunchPlatformBody):
    """唤起指定平台的 Edge 浏览器进行扫码/登录"""
    logger.info(f"🚀 [PLATFORM_SESSIONS] 收到唤起浏览器请求: platform={body.platform}")

    config = resolve_platform(body.platform)
    if not config:
        logger.warning(f"❌ [PLATFORM_SESSIONS] 未找到平台配置: {body.platform}")
        raise HTTPException(status_code=404, detail=f"未找到平台配置: {body.platform}")
    try:
        res = launch_edge(config)
        logger.info(f"✅ [PLATFORM_SESSIONS] 成功唤起 {config.display_name} 浏览器: {res}")
    except EdgeNotFoundError:
        # 结构化错误：前端据 code=edge_not_installed 弹「下载 Edge」引导弹窗
        logger.warning(f"❌ [PLATFORM_SESSIONS] 本机未安装 Edge，platform={body.platform}")
        raise HTTPException(status_code=400, detail=edge_not_installed_detail())
    except FileNotFoundError as e:
        # Edge 之外的文件缺失（如 profile 目录/可执行权限异常），保留专属提示不并入泛化分支
        logger.error(f"❌ [PLATFORM_SESSIONS] 唤起浏览器文件缺失: {e}")
        raise HTTPException(status_code=400, detail=f"未找到 Edge 可执行文件或 profile 目录: {e}")
    except Exception as e:
        logger.error(f"❌ [PLATFORM_SESSIONS] 唤起浏览器失败: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=f"唤起浏览器失败: {e}")
    return {"code": 0, "data": res, "msg": f"已唤起 {config.display_name} 浏览器"}


@router.post("/platform-sessions/close-all")
def close_all_platform_sessions_endpoint():
    """安全关闭所有已拉起的爬虫 Edge 浏览器，释放内存"""
    logger.info("🛑 [PLATFORM_SESSIONS] 收到安全关闭所有爬虫浏览器请求")
    from app.session.browser import close_all_edges

    count = close_all_edges()
    logger.info(f"✅ [PLATFORM_SESSIONS] 成功关闭 {count} 个浏览器进程")
    return {"code": 0, "data": {"closed_count": count}, "msg": f"已关闭 {count} 个浏览器进程"}


@router.get("/keyword-history")
def read_keyword_history(limit: int = 200):
    """历史记录列表（时间倒序）；limit 收敛到 1~500，防负值在 SQLite 中变成无限返回"""
    return {"code": 0, "data": list_keyword_history(max(1, min(500, limit)))}


@router.get("/keyword-history/check")
def check_keyword_history(keyword: str):
    """添加前重复检测：返回该关键词的历史记录（无则空列表）"""
    return {"code": 0, "data": find_keyword_history(keyword)}


@router.post("/keyword-history/archive")
def archive_keyword(body: ArchiveItem):
    """手动归档：把队列里的条件移入历史记录（source=archive）"""
    if not body.keyword.strip():
        raise HTTPException(status_code=400, detail="关键词不能为空")
    new_id = add_keyword_history(
        keyword=body.keyword,
        city=body.city,
        salary=body.salary,
        jobs_added=0,
        source="archive",
    )
    return {"code": 0, "data": {"id": new_id}, "msg": "已归档"}


@router.delete("/keyword-history/{history_id}")
def remove_keyword_history(history_id: int):
    ok = delete_keyword_history(history_id)
    if not ok:
        raise HTTPException(status_code=404, detail="记录不存在")
    return {"code": 0, "msg": "已删除"}


@router.get("/salary-mapping")
def get_salary_mapping_info():
    """获取标准薪资档位及 4 平台（Boss/智联/51job/猎聘）原生筛选映射表"""
    from app.session.salary_mapper import SALARY_MAPPING, STANDARD_SALARY_TIERS

    return {
        "code": 0,
        "data": {
            "tiers": STANDARD_SALARY_TIERS,
            "mapping": SALARY_MAPPING,
        },
    }


@router.get("/condition-progress")
def get_all_condition_progress():
    """获取所有「条件×平台」的抓取累积台账与预测总数"""
    from app.session.scrape_sessions import list_condition_progress

    rows = list_condition_progress()
    return {"code": 0, "data": rows}


@router.post("/condition-progress/reset")
def reset_condition_progress_endpoint(body: ResetConditionBody):
    """重置指定条件在某平台或全平台的续抓记录与进度"""
    from app.session.scrape_sessions import reset_session

    platforms = [body.platform] if body.platform else ["boss", "liepin", "51job", "zhilian", "xiaohongshu"]
    for p in platforms:
        reset_session(body.keyword.strip(), body.city.strip(), body.salary.strip(), p)
    return {"code": 0, "msg": f"条件「{body.keyword}」抓取进度已重置"}


@router.post("/suggest-keywords")
async def suggest_keywords():
    """根据「启用简历 + A级岗位画像」AI 推荐抓取关键词（岗位名称方向），去重现有队列"""
    resume_text = await asyncio.to_thread(get_active_resume_from_feishu)
    if not resume_text:
        raise HTTPException(status_code=400, detail="读不到启用简历，请先确认简历库")

    try:
        from app.strategy.service import get_global_jd_report

        jd_report = await get_global_jd_report() or ""
    except Exception:
        jd_report = ""

    existing = [k.get("keyword", "") for k in (get_scrape_config().get("keywords") or [])]

    client = get_openai_client()
    if client is None:
        raise HTTPException(status_code=400, detail="LLM 未配置，请先在设置中配置模型 API Key")
    prompt = f"""你是招聘爬虫的关键词顾问。请根据「简历」推导应该抓取哪些岗位名称的职位，
可参考「A级岗位画像」里市场对候选人的定位。
要求：
- 输出 10 个搜索关键词，每个 4-12 字，是岗位名称方向（如「AI应用工程师」「大模型开发工程师」）
- 覆盖核心方向与相邻方向，避免过于宽泛（如「工程师」）或过于狭窄
- 不要与现有队列重复：{ _json.dumps(existing, ensure_ascii=False) }
- 只输出 JSON 数组，如 ["AI应用工程师", ...]

简历：
{resume_text[:6000]}

A级岗位画像：
{jd_report[:3000]}"""
    r = await asyncio.to_thread(
        client.chat.completions.create,
        model=settings.OPENAI_MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=2000,
    )
    raw = (r.choices[0].message.content or "").strip()
    if not raw:
        raise HTTPException(status_code=502, detail="模型返回空内容，请重试或更换模型")
    raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        keywords = _json.loads(raw)
        if isinstance(keywords, dict):
            keywords = keywords.get("keywords", [])
    except Exception:
        keywords = _re.findall(r'"([^"]{2,20})"', raw)
    keywords = [str(k).strip() for k in keywords if str(k).strip()]
    if not keywords:
        raise HTTPException(status_code=502, detail="关键词解析失败，请重试")
    return {"code": 0, "data": keywords}
