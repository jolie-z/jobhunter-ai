import asyncio
import json
import logging
import os
import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter()

# 获取项目根目录
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(CURRENT_DIR)))

# 平台 → (爬虫子目录, 持有 set_stop_flag 的控制器模块名)
_PLATFORM_STOP_MODULES = {
    "boss": ("boss_scraper", "boss_nl_controller"),
    "liepin": ("liepin_scraper", "liepin_nl_controller"),
    "51job": ("51job_scraper", "51job_nl_controller"),
    "xiaohongshu": ("xiaohongshu_scraper", "xhs_drission_scraper"),
    "zhilian": ("zhilian_scraper", "zhilian_nl_controller"),
}


def stop_platform(platform: str) -> bool:
    """对指定平台爬虫置急刹 flag（优雅终止当轮抓取）。

    必须沿用 sys.path hack 动态 import：与全链路派发走的是 sys.modules 里
    同一个模块对象，flag 才互通；改成包式 import 会出现两份模块对象。
    单平台 import 失败只记日志返回 False，不让终止请求 500。
    """
    import importlib
    import sys

    spec = _PLATFORM_STOP_MODULES.get(platform)
    if not spec:
        logger.warning(f"[StopPlatform] 未知平台: {platform}")
        return False
    subdir, mod_name = spec
    try:
        mod_dir = os.path.join(PROJECT_ROOT, subdir)
        if mod_dir not in sys.path:
            sys.path.insert(0, mod_dir)
        mod = importlib.import_module(mod_name)
        if not hasattr(mod, "set_stop_flag"):
            logger.warning(f"[StopPlatform] {platform} 控制器缺少 set_stop_flag")
            return False
        mod.set_stop_flag(True)
        return True
    except Exception as e:
        logger.error(f"[StopPlatform] {platform} 置急刹 flag 失败: {e}", exc_info=True)
        return False


# 运行中爬虫 asyncio task 登记（平台 → task 集合），供可观测/未来精准取消
running_platform_tasks: dict = {}


def _track_platform_task(platform: str, task) -> None:
    running_platform_tasks.setdefault(platform, set()).add(task)
    task.add_done_callback(lambda t: running_platform_tasks.get(platform, set()).discard(t))

class SpiderRunRequest(BaseModel):
    platform: str = Field(..., description="平台名称：boss, liepin, 51job, xiaohongshu, zhilian")
    keyword: str = Field(..., description="搜索关键词")
    city: str = Field(default="不限", description="目标城市")
    salary: str = Field(default="不限", description="薪资范围")
    start_page: int = Field(default=1, ge=1, description="起始页码（最小为1）")
    target_jobs: int = Field(default=30, ge=1, le=50, description="目标获取职位数（单次任务上限50）")
    sort_by: str | None = Field(default="general", description="排序依据 (小红书)")

@router.get("/status")
async def get_crawlers_status():
    """检查各平台爬虫的可用状态（使用 to_thread 避免同步网络探测阻塞主事件循环）"""
    from app.session.manager import session_manager

    statuses = await asyncio.to_thread(session_manager.check_all)

    # 兼容旧前端：保留 platform → bool 的顶层字段
    result = {}
    for platform, s in statuses.items():
        available = s.state.value in ("healthy", "degraded")
        result[platform] = available
        # 新格式详情（前端可渐进升级读取）
        result[f"{platform}_detail"] = {
            "state": s.state.value,
            "message": s.message,
            "last_checked": s.last_checked.isoformat() if s.last_checked else None,
            "last_healthy": s.last_healthy.isoformat() if s.last_healthy else None,
            "port": s.port,
            "profile_path": s.profile_path,
            "browser_type": s.browser_type,
        }

    # 兼容旧字段
    result["51job_cookie_backed_up"] = result.get("51job", False)
    return result


@router.post("/session/recheck")
async def recheck_session(platform: str | None = None):
    """强制重新检查会话状态（绕过缓存，线程池安全执行）"""
    from app.session.manager import session_manager

    if platform:
        status = await asyncio.to_thread(session_manager.check_one, platform, force=True)
        return {platform: status.model_dump(mode="json")}
    statuses = await asyncio.to_thread(session_manager.check_all, force=True)
    return {p: s.model_dump(mode="json") for p, s in statuses.items()}

# 各平台抓取任务并发互斥表 (platform -> task_id)：杜绝同平台多任务踩踏 stop_flag 或抢占 CDP 端口
_platform_running_tasks: dict[str, str] = {}

@router.post("/run")
async def run_crawler(request: SpiderRunRequest, background_tasks: BackgroundTasks):
    """启动爬虫引擎任务（含同平台并发互斥）"""
    platform = request.platform.lower()

    # 验证支持的平台
    if platform not in ["boss", "liepin", "51job", "xiaohongshu", "zhilian"]:
        raise HTTPException(status_code=400, detail="不支持的平台")

    # 🌟 同平台并发防重互斥锁：防止并发冲突及互相覆盖全局停止标志
    active_task = _platform_running_tasks.get(platform)
    if active_task:
        raise HTTPException(
            status_code=409,
            detail=f"平台 {platform.upper()} 当前已有抓取任务在执行中 ({active_task})，请等待其完成或先将其终止！"
        )

    task_id = f"spider_{platform}_{uuid.uuid4().hex[:8]}"
    _platform_running_tasks[platform] = task_id

    from app.tasks.state import task_queues
    task_queues[task_id] = asyncio.Queue()

    # 🌟 小红书关键词适配：裸词搜索抓回来的几乎全是生活贴，白烧多模态清洗 Token。
    # 与统一分发 run_dispatch_collect 对齐，自动补「招聘」后缀
    effective_keyword = request.keyword
    if platform == "xiaohongshu":
        from app.session.salary_mapper import adapt_keyword
        effective_keyword = adapt_keyword(request.keyword.strip(), "xiaohongshu")

    if platform == "boss":
        background_tasks.add_task(
            _run_boss_task,
            task_id, request.city, request.keyword, request.salary, request.start_page, request.target_jobs
        )
    elif platform == "liepin":
        background_tasks.add_task(
            _run_liepin_task,
            task_id, request.city, request.keyword, request.salary, request.start_page, request.target_jobs
        )
    elif platform == "51job":
        background_tasks.add_task(
            _run_51job_task,
            task_id, request.city, request.keyword, request.salary, request.start_page, request.target_jobs
        )
    elif platform == "xiaohongshu":
        background_tasks.add_task(
            _run_xhs_task,
            task_id, effective_keyword, request.target_jobs, request.sort_by
        )
    elif platform == "zhilian":
        background_tasks.add_task(
            _run_zhilian_task,
            task_id, request.city, request.keyword, request.salary, request.start_page, request.target_jobs
        )

    return {"status": "success", "task_id": task_id, "message": f"已触发 {platform} 爬虫任务"}

@router.post("/cancel/{task_id}")
async def cancel_crawler(task_id: str):
    """强制停止特定的爬虫或清洗任务（防误杀重构版）"""
    try:
        from app.tasks.state import task_queues

        # 🌟 1. 清洗任务精准分流（杜绝误判为 boss 爬虫并误杀）
        if task_id.startswith(("clean_global_", "clean_hard_", "clean_ai_", "skip_ai_", "sync_feishu_")):
            from job_processor import step1_rule_filter
            step1_rule_filter.set_stop_flag(True)
            if task_id in task_queues:
                await task_queues[task_id].put('data: {"type": "terminated", "message": "清洗任务已被手动终止"}\n\n')
            return {"status": "success", "message": f"清洗任务 {task_id} 终止信号已发送"}

        if task_id.startswith("clean_xhs_"):
            from job_processor import xhs_vision_cleaner
            xhs_vision_cleaner.set_stop_flag(True)
            if task_id in task_queues:
                await task_queues[task_id].put('data: {"type": "terminated", "message": "小红书清洗任务已被手动终止"}\n\n')
            return {"status": "success", "message": f"小红书清洗任务 {task_id} 终止信号已发送"}

        # 🌟 2. 爬虫任务平台精准匹配（严禁默认 fallback 到 boss）
        platform = None
        if "boss" in task_id:
            platform = "boss"
        elif "liepin" in task_id:
            platform = "liepin"
        elif "51job" in task_id:
            platform = "51job"
        elif "xiaohongshu" in task_id:
            platform = "xiaohongshu"
        elif "zhilian" in task_id:
            platform = "zhilian"

        if not platform:
            logger.warning(f"cancel_crawler: 无法识别 task_id 对应平台，跳过停止: {task_id}")
            if task_id in task_queues:
                await task_queues[task_id].put('data: {"type": "terminated", "message": "未知任务已被手动终止"}\n\n')
            return {"status": "success", "message": f"任务 {task_id} 状态已更新"}

        stop_platform(platform)

        # 🌟 主动解锁该平台的并发互斥锁：爬虫卡死（浏览器 hang 住、子进程不退出）时
        # 协程永不结束、finally 不执行，该平台会永久 409 直到重启后端。
        # 用户明确点击终止 = 授权释放，让下一次抓取可以立即重新发起。
        if _platform_running_tasks.get(platform) == task_id:
            _platform_running_tasks.pop(platform, None)
            logger.info(f"[Cancel] 已主动解除平台 {platform} 的并发互斥锁 (原任务: {task_id})")
        else:
            # 极端并发：终止的 task_id 与登记中的不一致（如同平台刚启动了新任务），
            # 不能误清新任务的锁
            logger.warning(f"[Cancel] 任务 {task_id} 与平台 {platform} 当前登记任务不一致，保留锁不动")

        # 强制更新前端状态
        if task_id in task_queues:
            await task_queues[task_id].put('data: {"type": "terminated", "message": "任务已被手动终止"}\n\n')

        return {"status": "success", "message": f"任务 {task_id} 的停止信号已发送"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- 爬虫异步调度包装函数 ---

async def _run_boss_task(task_id: str, city: str, keyword: str, salary: str, start_page: int, target_jobs: int):
    try:
        # 使用动态导入以避免全局依赖问题
        import sys
        boss_dir = os.path.join(PROJECT_ROOT, "boss_scraper")
        if boss_dir not in sys.path:
            sys.path.insert(0, boss_dir)
        import boss_nl_controller

        await boss_nl_controller.process_boss_scraping_request(
            chat_id="agent_cli",
            city=city,
            keyword=keyword,
            salary=salary,
            start_page=start_page,
            target_jobs=target_jobs,
            sse_task_id=task_id
        )
    except Exception as e:
        logger.error(f"❌ BOSS爬虫异常崩溃: {str(e)}")
        from app.tasks.state import task_queues
        if task_id in task_queues:
            err_msg = json.dumps({"type": "error", "message": f"BOSS爬虫异常崩溃: {str(e)}"}, ensure_ascii=False)
            await task_queues[task_id].put(f"data: {err_msg}\n\n")
    finally:
        if _platform_running_tasks.get("boss") == task_id:
            _platform_running_tasks.pop("boss", None)
        from app.tasks.state import schedule_task_cleanup, task_queues
        if task_id in task_queues:
            await task_queues[task_id].put('data: {"type": "end"}\n\n')
        schedule_task_cleanup(task_id, delay_seconds=300)

async def _run_liepin_task(task_id: str, city: str, keyword: str, salary: str, start_page: int, target_jobs: int):
    try:
        import sys
        liepin_dir = os.path.join(PROJECT_ROOT, "liepin_scraper")
        if liepin_dir not in sys.path:
            sys.path.insert(0, liepin_dir)
        import liepin_nl_controller

        await liepin_nl_controller.process_liepin_scraping_request(
            chat_id="agent_cli",
            city=city,
            keyword=keyword,
            salary=salary,
            start_page=start_page,
            target_jobs=target_jobs,
            sse_task_id=task_id
        )
    except Exception as e:
        logger.error(f"❌ 猎聘爬虫异常崩溃: {str(e)}")
        from app.tasks.state import task_queues
        if task_id in task_queues:
            err_msg = json.dumps({"type": "error", "message": f"猎聘爬虫异常崩溃: {str(e)}"}, ensure_ascii=False)
            await task_queues[task_id].put(f"data: {err_msg}\n\n")
    finally:
        if _platform_running_tasks.get("liepin") == task_id:
            _platform_running_tasks.pop("liepin", None)
        from app.tasks.state import schedule_task_cleanup, task_queues
        if task_id in task_queues:
            await task_queues[task_id].put('data: {"type": "end"}\n\n')
        schedule_task_cleanup(task_id, delay_seconds=300)

async def _run_51job_task(task_id: str, city: str, keyword: str, salary: str, start_page: int, target_jobs: int):
    try:
        import sys
        job51_dir = os.path.join(PROJECT_ROOT, "51job_scraper")
        if job51_dir not in sys.path:
            sys.path.insert(0, job51_dir)
        import importlib
        job51_nl = importlib.import_module("51job_nl_controller")

        # 返回本轮最后触碰页码（异常时为 None），供 _run_and_track 续抓回写
        return await job51_nl.process_51job_scraping_request(
            chat_id="agent_cli",
            city=city,
            keyword=keyword,
            salary=salary,
            start_page=start_page,
            target_jobs=target_jobs,
            sse_task_id=task_id
        )
    except Exception as e:
        logger.error(f"❌ 51job爬虫异常崩溃: {str(e)}")
        from app.tasks.state import task_queues
        if task_id in task_queues:
            err_msg = json.dumps({"type": "error", "message": f"51job爬虫异常崩溃: {str(e)}"}, ensure_ascii=False)
            await task_queues[task_id].put(f"data: {err_msg}\n\n")
        return None
    finally:
        if _platform_running_tasks.get("51job") == task_id:
            _platform_running_tasks.pop("51job", None)
        from app.tasks.state import schedule_task_cleanup, task_queues
        if task_id in task_queues:
            await task_queues[task_id].put('data: {"type": "end"}\n\n')
        schedule_task_cleanup(task_id, delay_seconds=300)

async def _run_xhs_task(task_id: str, keyword: str, target_jobs: int, sort_by: str = "general"):
    try:
        # 视觉前置闸门：小红书管道 = 抓图 + 视觉清洗，未配置视觉模型时整链无意义，抓前拦截
        from common.config import get_missing_vision_keys, missing_guide_text
        missing_vision = get_missing_vision_keys()
        if missing_vision:
            warn_msg = f"视觉模型未配置，小红书图文清洗不可用，已跳过本次抓取。{missing_guide_text(missing_vision, '小红书图文清洗')}后重试"
            logger.warning(f"🚧 [xhs] {warn_msg}")
            from app.tasks.state import task_queues as _tq
            await _tq[task_id].put(f"data: {json.dumps({'type': 'error', 'message': warn_msg}, ensure_ascii=False)}\n\n")
            return

        import sys
        xhs_dir = os.path.join(PROJECT_ROOT, "xiaohongshu_scraper")
        if xhs_dir not in sys.path:
            sys.path.insert(0, xhs_dir)
        import xhs_drission_scraper

        loop = asyncio.get_running_loop()
        await asyncio.to_thread(
            xhs_drission_scraper.process_xhs_scraping_request,
            keyword=keyword,
            target_jobs=target_jobs,
            sse_task_id=task_id,
            loop=loop,
            sort_by=sort_by
        )

        # 触发多模态大模型清洗管道（用户明确要求即使终止抓取也清洗已抓到的数据）
        # 🌟 统一互斥锁在 run_vision_cleaner 内部管理，此处裸调用：
        # wait_if_busy=True 表示排队等锁——手动清洗恰好在跑时，等它结束接续清洗
        # 已抓数据，绝不因并发而丢弃；且外层严禁再包 async with（非可重入锁，包了必自锁）
        import sys
        cleaner_dir = os.path.join(PROJECT_ROOT, "job_processor")
        if cleaner_dir not in sys.path:
            sys.path.insert(0, cleaner_dir)
        import xhs_vision_cleaner
        await xhs_vision_cleaner.run_vision_cleaner(sse_task_id=task_id, wait_if_busy=True)

    except Exception as e:
        logger.error(f"❌ 小红书爬虫异常崩溃: {str(e)}")
        from app.tasks.state import task_queues
        if task_id in task_queues:
            err_msg = json.dumps({"type": "error", "message": f"小红书爬虫异常崩溃: {str(e)}"}, ensure_ascii=False)
            await task_queues[task_id].put(f"data: {err_msg}\n\n")
    finally:
        if _platform_running_tasks.get("xiaohongshu") == task_id:
            _platform_running_tasks.pop("xiaohongshu", None)
        from app.tasks.state import schedule_task_cleanup, task_queues
        if task_id in task_queues:
            await task_queues[task_id].put('data: {"type": "end"}\n\n')
        schedule_task_cleanup(task_id, delay_seconds=300)

async def _run_zhilian_task(task_id: str, city: str, keyword: str, salary: str, start_page: int, target_jobs: int):
    try:
        import sys
        zhilian_dir = os.path.join(PROJECT_ROOT, "zhilian_scraper")
        if zhilian_dir not in sys.path:
            sys.path.insert(0, zhilian_dir)
        import zhilian_nl_controller

        await zhilian_nl_controller.process_zhilian_scraping_request(
            chat_id="agent_cli",
            city=city,
            keyword=keyword,
            salary=salary,
            start_page=start_page,
            target_jobs=target_jobs,
            sse_task_id=task_id
        )
    except Exception as e:
        logger.error(f"❌ 智联爬虫异常崩溃: {str(e)}")
        from app.tasks.state import task_queues
        if task_id in task_queues:
            err_msg = json.dumps({"type": "error", "message": f"智联爬虫异常崩溃: {str(e)}"}, ensure_ascii=False)
            await task_queues[task_id].put(f"data: {err_msg}\n\n")
    finally:
        if _platform_running_tasks.get("zhilian") == task_id:
            _platform_running_tasks.pop("zhilian", None)
        from app.tasks.state import schedule_task_cleanup, task_queues
        if task_id in task_queues:
            await task_queues[task_id].put('data: {"type": "end"}\n\n')
        schedule_task_cleanup(task_id, delay_seconds=300)


# ==================== 统一分发 ====================

@router.get("/salary-tiers")
async def get_salary_tiers():
    """返回标准薪资档位列表（供前端下拉框使用）"""
    from app.session.salary_mapper import STANDARD_SALARY_TIERS
    return {"tiers": STANDARD_SALARY_TIERS}


class DispatchRequest(BaseModel):
    keyword: str = Field(..., description="搜索关键词")
    city: str = Field(default="广州", description="目标城市")
    salary: str = Field(default="不限", description="标准薪资档位（下拉单选）")
    target_jobs: int = Field(default=20, description="每平台抓取数量")
    platforms: list[str] = Field(default=["boss", "liepin", "51job", "zhilian", "xiaohongshu"], description="勾选的平台列表")
    run_type: str = Field(default="now", description="执行方式: now=立即, cron=定时(暂未实现)")


@router.post("/dispatch")
async def dispatch_crawlers(request: DispatchRequest):
    """
    统一分发：一份搜索单 → 自动翻译 → 并发分发到各平台爬虫。
    支持薪资映射、关键词适配（小红书加"招聘"）、同条件续抓页码。
    """
    valid_platforms = ["boss", "liepin", "51job", "zhilian", "xiaohongshu"]
    selected = [p for p in request.platforms if p in valid_platforms]
    if not selected:
        raise HTTPException(status_code=400, detail="未选择有效平台")

    # 🌟 统一分发并发互斥检查：防止所选平台已有任务在执行，导致 CDP 端口或 stop_flag 踩踏
    conflicts = [p for p in selected if p in _platform_running_tasks]
    if conflicts:
        raise HTTPException(
            status_code=409,
            detail=f"以下平台当前已有抓取任务在执行中，请等待完成或先终止：{', '.join([p.upper() for p in conflicts])}"
        )

    dispatch_id = f"dispatch_{uuid.uuid4().hex[:8]}"

    sub_tasks = await run_dispatch_collect(
        keyword=request.keyword,
        city=request.city,
        salary=request.salary,
        target_jobs=request.target_jobs,
        platforms=selected,
        master_task_id=None,
    )

    return {
        "status": "success",
        "dispatch_id": dispatch_id,
        "message": f"已分发到 {len(sub_tasks)} 个平台",
        "sub_tasks": sub_tasks,
    }


async def run_dispatch_collect(keyword: str, city: str, salary: str, target_jobs: int,
                               platforms: list, master_task_id: str = None,
                               platform_targets: dict = None,
                               platform_search: dict = None) -> list:
    """
    可复用的统一分发机器（供手动批量分发 + 全自动链路共同调用）。

    一份搜索单 → 薪资映射 → 关键词适配 → 续抓页码 → 并发分发到各平台爬虫。
    当传入 master_task_id 时，各平台子任务的 SSE 事件会被转发（打上 platform 标签）到主队列，
    供全链路实时看板统一展示；不传则各子任务独立持有队列（手动模式，行为与原来一致）。

    platform_targets：{平台key: 该平台独立目标数}，未指定时所有平台统一用 target_jobs。
    platform_search：{平台key: {"keyword","city","salary","target"}}，抓尽制编排下
    各平台可带各自不同的搜索条件（各平台条件进度不同步）；未指定的平台沿用共享参数。

    返回 sub_tasks 列表（含每个平台的 task_id / 翻译后参数 / 起始页）。
    """
    from app.session.salary_mapper import adapt_keyword, map_salary
    from app.session.scrape_sessions import get_last_page
    from app.tasks.state import task_queues

    sub_tasks = []
    forwarders = []

    for platform in platforms:
        # 0. 该平台独立搜索条件与目标（抓尽制编排传入 platform_search）
        ov = (platform_search or {}).get(platform) or {}
        p_keyword = (ov.get("keyword") or keyword).strip()
        p_city = (ov.get("city") if ov.get("city") is not None else city) or ""
        p_salary = (ov.get("salary") if ov.get("salary") is not None else salary) or ""
        platform_target = int(ov.get("target") or 0) or int((platform_targets or {}).get(platform) or 0) or target_jobs

        # 1. 薪资翻译
        platform_salary = map_salary(p_salary, platform)

        # 2. 关键词适配
        platform_keyword = adapt_keyword(p_keyword, platform)

        # 3. 续抓页码（同条件才续，否则从第 1 页开始）
        # 51job 的 last_page 是「最后触碰页码」（末页可能未抓满），从该页重爬兜底；
        # 其余平台仍是旧语义（回写任务起始页），暂保持 last+1 不变，待逐个修复
        last_page = get_last_page(p_keyword, p_city, p_salary, platform)
        if last_page > 0:
            start_page = last_page if platform == "51job" else last_page + 1
        else:
            start_page = 1

        # 4. 创建子任务并登记并发锁（防止批量分发与调试面板同平台任务互相踩踏）
        task_id = f"spider_{platform}_{uuid.uuid4().hex[:8]}"
        _platform_running_tasks[platform] = task_id
        task_queues[task_id] = asyncio.Queue()

        # 5. 并发分发到对应平台（asyncio.create_task 实现真并行）
        if platform == "boss":
            _task = asyncio.create_task(
                _run_and_track(_run_boss_task(task_id, p_city, platform_keyword, platform_salary, start_page, platform_target),
                               task_id, p_keyword, p_city, p_salary, platform, start_page)
            )
        elif platform == "liepin":
            _task = asyncio.create_task(
                _run_and_track(_run_liepin_task(task_id, p_city, platform_keyword, platform_salary, start_page, platform_target),
                               task_id, p_keyword, p_city, p_salary, platform, start_page)
            )
        elif platform == "51job":
            _task = asyncio.create_task(
                _run_and_track(_run_51job_task(task_id, p_city, platform_keyword, platform_salary, start_page, platform_target),
                               task_id, p_keyword, p_city, p_salary, platform, start_page)
            )
        elif platform == "zhilian":
            _task = asyncio.create_task(
                _run_and_track(_run_zhilian_task(task_id, p_city, platform_keyword, platform_salary, start_page, platform_target),
                               task_id, p_keyword, p_city, p_salary, platform, start_page)
            )
        elif platform == "xiaohongshu":
            _task = asyncio.create_task(
                _run_and_track(_run_xhs_task(task_id, platform_keyword, platform_target, "time_descending"),
                               task_id, p_keyword, p_city, p_salary, platform, start_page)
            )
        else:
            _task = None
        if _task is not None:
            _track_platform_task(platform, _task)

        # 6. 如有主队列，启动转发协程把子任务事件汇聚到全链路看板
        #    传入 sub_task：转发协程以「task 真实结束」为退出判据，长静默不再被误判为任务结束
        if master_task_id and _task is not None:
            forwarders.append(_forward_subtask_events(task_id, platform, master_task_id, sub_task=_task))

        sub_tasks.append({
            "task_id": task_id,
            "platform": platform,
            "keyword": platform_keyword,
            "city": p_city if platform != "xiaohongshu" else "",
            "salary": platform_salary,
            "start_page": start_page,
            "target_jobs": platform_target,
        })

    # 等待所有平台抓取完成（仅全自动链路需要；手动模式 master_task_id=None 时立即返回）
    if master_task_id and forwarders:
        await asyncio.gather(*forwarders, return_exceptions=True)

    return sub_tasks


# 转发协程兜底超时（秒）：仅在子任务真 hang 时避免主流程永久挂起；
# 正常结束走「子任务真实结束（task done + 队列排空）」或结束帧。
# 心跳机制上线后子任务长静默期间至多 30s 报一次平安，正常不会逼近该值。
_FORWARD_FALLBACK_TIMEOUT_S = 900.0


async def _forward_subtask_events(sub_task_id: str, platform: str, master_task_id: str,
                                  sub_task: "asyncio.Task | None" = None) -> str:
    """
    把单个平台子任务的 SSE 事件转发到全链路主队列：
    - 打上 platform 标签，便于前端区分各平台进度
    - 子任务的 end / terminated / complete 事件均为本平台结束信号，不转发到主流
      （complete 是爬虫的终结帧，若转发进主队列会被 /logs 端点误判为全链路结束而提前断流）
    - heartbeat 事件只用于给本协程保活（防长静默被误判为结束），不转发
    - progress 事件补充 stage="scraping" 字段

    退出判据（按优先级）：abort 信号 / 结束帧 / 子任务真实结束且队列排空 /
    极端 hang 的兜底超时。返回退出原因，供观测与测试断言。
    """
    import json as _json

    from app.tasks.state import task_queues

    master_queue = task_queues.get(master_task_id)
    sub_queue = task_queues.get(sub_task_id)
    if master_queue is None or sub_queue is None:
        return "no_queue"

    from app.automation import abort as abort_mod
    while True:
        # 终止指令：停止转发，链路将在安全点收尾
        if abort_mod.is_aborted():
            return "aborted"

        if sub_task is not None and sub_task.done():
            # 子任务真实结束（controller finally 必发结束帧）：排空队列残留事件后退出
            try:
                raw = sub_queue.get_nowait()
            except asyncio.QueueEmpty:
                return "task_done"
        else:
            try:
                raw = await asyncio.wait_for(sub_queue.get(), timeout=_FORWARD_FALLBACK_TIMEOUT_S)
            except asyncio.TimeoutError:
                # 极端兜底：子任务 hang 死长时间无任何事件，先退出避免主流程永久挂起，
                # 编排层清孤儿（_reap_orphan_scrapers）会接管急刹
                logger.warning(
                    f"[Forward] {platform} 子任务静默超 {_FORWARD_FALLBACK_TIMEOUT_S}s 且未结束，按兜底退出")
                return "fallback"

        try:
            payload_str = raw.replace("data: ", "", 1).strip()
            data = _json.loads(payload_str)
        except Exception:
            continue

        msg_type = data.get("type")
        if msg_type in ("end", "terminated", "complete"):
            return "complete"
        if msg_type == "heartbeat":
            # 心跳只为防误判保活，不推入主流程看板
            continue

        # 打标签 + 补阶段字段后转发到主队列
        data["platform"] = platform
        if msg_type == "progress":
            data["stage"] = "scraping"
        master_queue.put_nowait(f'data: {_json.dumps(data, ensure_ascii=False)}\n\n')


async def _run_and_track(coro, _task_id: str, keyword: str, city: str, salary: str, platform: str, start_page: int):
    """
    包装爬虫任务：运行完成后回写续抓页码。
    不再从 SSE 队列读事件（避免和前端抢事件导致进度条丢失）。

    回写值优先级：爬虫返回的真实「最后触碰页码」（目前仅 51job 返回，
    下次从该页重爬兜底，防末页未抓满）→ 兜底用任务起始页（旧行为，
    未返回真实页码的平台保持现状，待逐个修复）。
    """
    from app.session.scrape_sessions import update_last_page
    final_page = None
    try:
        final_page = await coro
    except Exception as e:
        logger.error(f"[Dispatch] {platform} 任务异常: {e}")
    finally:
        if isinstance(final_page, int) and final_page > 0:
            resume_page = final_page
        else:
            resume_page = start_page
        update_last_page(keyword, city, salary, platform, resume_page)
        logger.info(f"[Dispatch] {platform} 完成，续抓页码已更新为 {resume_page}")
