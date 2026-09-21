import asyncio
import logging
import random
import sys
from datetime import datetime
from typing import Any

from app.automation.db import get_autopilot_config

logger = logging.getLogger(__name__)


def _get_active_func(name: str, default_func: Any) -> Any:
    """动态获取生效的函数（优先尊重外部 monkeypatch）。"""
    sched_mod = sys.modules.get("app.automation.scheduler")
    if sched_mod and hasattr(sched_mod, name):
        val = getattr(sched_mod, name)
        if val is not default_func and val is not None:
            return val
    return default_func


async def trigger_auto_apply_job_with_guard(pipeline_app: Any | None = None):
    """
    【推荐】带 PlatformGuard 的混合执行模式入口

    执行策略：
    - Phase 1: 爬虫阶段 - 4 平台并行（带限流）
    - Phase 2: 投递阶段 - 4 平台串行（逐个平台完成）

    优势：
    - 爬虫阶段充分利用带宽（GET 请求风险低）
    - 投递阶段严格隔离（POST 请求反爬严格）
    - 平台间有冷却时间（防止短时间高频操作）
    """
    logger.info(f"⏰ [Autopilot] 触发自动化任务（混合模式）: {datetime.now()}")

    from app.automation.delivery_tasks import get_pipeline_app
    app = pipeline_app or get_pipeline_app()
    if not app:
        logger.error("❌ 自动化管线未初始化，任务中止。")
        return

    cfg_func = _get_active_func("get_autopilot_config", get_autopilot_config)
    config = cfg_func()
    if not config.get("is_enabled"):
        logger.info("⏸️ [Autopilot] 自动化任务大盘总开关未开启，跳过执行。")
        return

    from app.automation.platform_guard import PlatformGuard
    from app.automation.platform_semaphore import (
        DeliveryTimeoutError,
        PlatformSemaphore,
    )

    # 初始化平台信号量
    platform_lock = PlatformSemaphore()

    # ========== Phase 1: 并行爬虫（所有平台同时进行）==========
    logger.info("🕒 [Phase 1] 启动全平台爬虫（并行模式）...")

    scraper_tasks = {}
    scraper_fn = _get_active_func("run_scraper_with_rate_limit", run_scraper_with_rate_limit)
    for platform in ["boss", "51job", "liepin", "zhilian"]:
        pconfig = config.get("platform_configs", {}).get(platform)
        if not pconfig or pconfig.get("limit", 0) <= 0:
            logger.info(f"⏭️ 跳过 {platform}（未启用或限制为 0）")
            continue

        # 创建平台专属爬虫任务（带限流）
        task = asyncio.create_task(scraper_fn(platform, pconfig))
        scraper_tasks[platform] = task

    # 等待所有爬虫完成
    if scraper_tasks:
        results = await asyncio.gather(*scraper_tasks.values(), return_exceptions=True)
        logger.info(f"✅ [Phase 1] 爬虫完成，共 {len(results)} 个平台成功")

    # ========== 冷却休息（给服务器一点缓冲）==========
    logger.info("⏱️ [Cool-down] 等待 60 秒...")
    await asyncio.sleep(60)

    # ========== Phase 2: 串行投递（平台一个一个来）==========
    logger.info("🕒 [Phase 2] 启动全平台投递（串行模式）...")

    # 简历与求职偏好全流程只拉一次（复刻旧版 Autopilot 的取数来源）
    from app.services.feishu_service import (
        get_active_resume_from_feishu,
        get_my_preferences,
        get_new_leads_from_feishu,
    )
    resume_text = await asyncio.to_thread(get_active_resume_from_feishu)
    preferences_text = await asyncio.to_thread(get_my_preferences)

    delivery_order = ["boss", "51job", "liepin", "zhilian"]
    pipe_job_fn = _get_active_func("run_pipeline_for_job", run_pipeline_for_job)

    for platform in delivery_order:
        try:
            # Step 2.1: 检查该平台的投递权限
            guard = PlatformGuard()

            can_deliver, reason = await guard.can_start_delivery(platform)
            if not can_deliver:
                logger.warning(f"🛑 {platform} 不符合投递条件：{reason}，跳过")
                continue

            # Step 2.2: 从飞书拉取该平台的新线索
            leads = await asyncio.to_thread(get_new_leads_from_feishu, platform)

            if not leads:
                logger.info(f"📭 {platform} 无新线索待投递")
                continue

            logger.info(f"🚀 [{platform}] 准备投递 {len(leads)} 个岗位...")

            # Step 2.3: 获取平台锁（互斥）
            async with platform_lock.acquire_with_timeout(platform, timeout_seconds=1800):

                # Step 2.4: 逐个投递（限制并发数）
                semaphore = asyncio.Semaphore(3)  # 最多 3 个岗位同时投递

                async def limited_deliver(lead, _semaphore=semaphore):
                    async with _semaphore:
                        # 复刻旧版 Autopilot 的 lead → initial_state 映射；
                        # thread_id 用 record_id，打通人工审批断点恢复全链路
                        thread_id = lead.get("record_id") or ""
                        state_config = {"configurable": {"thread_id": thread_id}}
                        initial_state = {
                            "job_id": thread_id,
                            "record_id": thread_id,
                            "platform": lead.get("platform", ""),
                            "company_name": lead.get("company", ""),
                            "job_name": lead.get("job_title", ""),
                            "jd_text": lead.get("jd_text", ""),
                            "salary": lead.get("salary", ""),
                            "city": lead.get("city", ""),
                            "experience": lead.get("experience", ""),
                            "education": lead.get("education", ""),
                            "company_scale": "",
                            "resume_text": resume_text,
                            "preferences_text": preferences_text,
                            "company_intel": "",
                            "feishu_fields": lead.get("_raw_fields", {}),
                        }
                        return await pipe_job_fn(
                            initial_state, state_config, lead.get("job_title", ""), pipeline_app=app
                        )

                deliver_tasks = [
                    asyncio.create_task(limited_deliver(lead))
                    for lead in leads
                ]

                # 等待该平台所有投递完成
                await asyncio.gather(*deliver_tasks, return_exceptions=True)

                logger.info(f"✅ [{platform}] 投递完成")

                # 更新状态
                guard.update_platform_status(platform, "end")

                # Step 2.5: 平台间冷却
                cooldown = PlatformGuard.DEFAULT_COOLDOWN_POLICY[platform]["between_platforms"]
                logger.info(f"⏱️ [{platform}] 冷却 {cooldown} 分钟...")
                await asyncio.sleep(cooldown * 60)

        except DeliveryTimeoutError as e:
            logger.warning(f"🔄 [{platform}] 超时，切换到下一平台：{str(e)}")
            continue

        except Exception as e:
            logger.error(f"🚨 [{platform}] 投递异常：{str(e)}", exc_info=True)
            logger.info("🔄 继续处理下一个平台...")
            continue

    logger.info("🎉 [Phase 2] 全平台投递结束")


async def run_scraper_with_rate_limit(platform: str, config: dict):
    """
    带限流的爬虫执行函数

    Args:
        platform: 平台名称
        config: 平台配置（包含 limit/keyword/city 等）
    """
    logger.info(f"🚀 [Scraper] 启动 {platform} 爬虫...")

    # 根据平台选择爬虫脚本
    script_path = ""
    if platform == "boss":
        script_path = "boss_scraper/boss_collector.py"
    elif platform == "51job":
        script_path = "51job_scraper/51job_collector.py"
    elif platform == "liepin":
        script_path = "liepin_scraper/liepin_crawler.py"
    elif platform == "zhilian":
        script_path = "zhilian_scraper/zhilian_collector.py"

    if not script_path:
        logger.warning(f"⚠️ [Scraper] 平台 {platform} 的爬虫暂未对接，跳过")
        return

    # 组装命令行参数
    limit = config.get("limit", 0)
    pages = max(1, limit // 30)

    extra_args = []
    if config.get("keyword"):
        extra_args.extend(["--keyword", config["keyword"]])
    if config.get("city") and config.get("city") != "全国":
        extra_args.extend(["--city", config["city"]])
    if config.get("salary") and config.get("salary") != "不限":
        extra_args.extend(["--salary", config["salary"]])

    try:
        for page in range(1, pages + 1):
            logger.info(f"  └─ 抓取 {platform} 第 {page}/{pages} 页...")

            cmd_args = [script_path, "--page", str(page)] + extra_args

            process = await asyncio.create_subprocess_exec(
                sys.executable, "-X", "utf8", *cmd_args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()

            if process.returncode == 0:
                logger.info(f"  ✅ {platform} 第 {page} 页抓取完成")
            else:
                logger.error(f"  ❌ {platform} 抓取异常：{stderr.decode('utf-8', errors='ignore')[:200]}")

            # 限流：每次抓取之间间隔 3-5 秒
            await asyncio.sleep(random.uniform(3, 5))

    except Exception as e:
        logger.error(f"🚨 [Scraper] 启动 {platform} 爬虫异常：{e}")


async def run_pipeline_for_job(
    initial_state: dict, config: dict, log_name: str, pipeline_app: Any | None = None
):
    """单独为某个岗位运行状态机"""
    logger.info(f"▶️ [Pipeline Start] {log_name} (Thread: {config['configurable']['thread_id']})")

    from app.automation.delivery_tasks import get_pipeline_app
    app = pipeline_app or get_pipeline_app()
    if not app:
        logger.error(f"❌ 自动化管线未初始化，无法为岗位 {log_name} 运行状态机。")
        return

    try:
        # 开启 stream，可以监听每一个节点的输出，方便通过 SSE 推送给前端
        async for event in app.astream(initial_state, config):
            for node_name, _state_update in event.items():
                logger.info(f"  └─ 节点执行完成: {node_name}")

        # 检查是否被断点拦截了
        snapshot = await app.aget_state(config)
        if snapshot.next and snapshot.next[0] == "manual_review_node":
            logger.warning("⏸️ [Pipeline Paused] 岗位已被拦截！等待老板通过 UI 确认投递。")
            logger.warning(f"   (使用 Thread ID: {config['configurable']['thread_id']} 进行恢复)")

    except Exception as e:
        logger.error(f"❌ [Pipeline Error] 岗位 {log_name} 处理异常: {str(e)}", exc_info=True)
