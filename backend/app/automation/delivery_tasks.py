import asyncio
import logging
import sys
from datetime import date, datetime
from typing import Any

from app.automation import db as automation_db
from app.automation import upload_quota
from app.automation.db import get_autopilot_config
from app.automation.hybrid_delivery import (  # noqa: F401
    run_pipeline_for_job,
    run_scraper_with_rate_limit,
    trigger_auto_apply_job_with_guard,
)

logger = logging.getLogger(__name__)

# 本模块的局部图执行器实例缓存（支持显式注入参数化）
pipeline_app: Any | None = None


def set_pipeline_app(app: Any) -> None:
    """设置图执行器实例（供依赖注入或初始化时同步）"""
    global pipeline_app
    pipeline_app = app


def get_pipeline_app() -> Any:
    """获取图执行器实例（优先读取显式设置值，缺省动态穿透读取 scheduler.pipeline_app）"""
    global pipeline_app
    if pipeline_app is not None:
        return pipeline_app
    sched_mod = sys.modules.get("app.automation.scheduler")
    if sched_mod and hasattr(sched_mod, "pipeline_app"):
        return sched_mod.pipeline_app
    return None


def _get_active_func(name: str, default_func: Any) -> Any:
    """
    动态获取生效的函数。
    若单元测试在 app.automation.scheduler 上对该函数执行了 monkeypatch，优先读取打桩版本。
    """
    sched_mod = sys.modules.get("app.automation.scheduler")
    if sched_mod and hasattr(sched_mod, name):
        val = getattr(sched_mod, name)
        if val is not default_func and val is not None:
            return val
    return default_func


def _call_guard(guard_fn: Any, label: str, pipeline_app: Any | None = None) -> bool:
    """调用守卫函数，自动兼容只接受 1 个位置参数的打桩 lambda"""
    try:
        return bool(guard_fn(label, pipeline_app=pipeline_app))
    except TypeError:
        return bool(guard_fn(label))


async def _call_resume(resume_fn: Any, job_id: str, pipeline_app: Any | None = None) -> tuple[bool, str]:
    """调用投递恢复函数，自动兼容只接受 1 个参数的打桩协程"""
    try:
        return await resume_fn(job_id, pipeline_app=pipeline_app)
    except TypeError:
        return await resume_fn(job_id)


def _check_schedule_date_range(config: dict) -> tuple[bool, str]:
    """检查今天是否落在定时链路日期范围内（YYYY-MM-DD；空 = 该侧不限）。"""
    today = datetime.now().strftime("%Y-%m-%d")
    start = (config.get("schedule_start_date") or "").strip()
    end = (config.get("schedule_end_date") or "").strip()
    if start and today < start:
        return False, f"今日 {today} 早于定时开始日期 {start}"
    if end and today > end:
        return False, f"今日 {today} 已过定时结束日期 {end}"
    return True, ""


def _check_non_workday(config: dict) -> tuple[bool, str]:
    """检查今天是否为非工作日（周末/法定节假日），HR 不在岗则跳过本轮。

    语义是「跳过非工作日」而非「跳过周末」：调休补班的周六日算工作日照常跑，
    落在周中的法定节假日也要跳过。数据来自 chinese-calendar（按国务院年度通知维护）。
    fail-open：包数据未覆盖当年时退化为只跳周六日并告警，避免工作日静默断供。
    返回 (是否放行, 跳过原因)。
    """
    if not config.get("skip_non_workdays"):
        return True, ""
    sched_mod = sys.modules.get("app.automation.scheduler")
    date_cls = getattr(sched_mod, "date", date) if sched_mod else date
    today = date_cls.today()
    try:
        from chinese_calendar import is_workday
    except ImportError:
        logger.warning("[Autopilot] 未安装 chinese-calendar，跳过非工作日检查")
        return True, ""
    try:
        if is_workday(today):
            return True, ""
        return False, f"今日 {today} 为非工作日（周末或法定节假日），HR 不在岗"
    except NotImplementedError:
        if today.weekday() >= 5:
            return False, "今日为周末（节假日数据未覆盖当年，仅按周末跳过）"
        logger.warning("[Autopilot] chinese-calendar 数据未覆盖当年，工作日默认执行")
        return True, ""


async def trigger_auto_apply_job(pipeline_app: Any | None = None):
    """
    Cron 触发的全自动任务入口（每天早上自动跑）。
    现委托给 full_auto.run_full_auto_pipeline 编排器：
    抓取(dispatch机器) → 清洗(step1) → 飞书(step2) → 捞线索 → LangGraph 评估改写。
    定时链路固定 stop_at_review=True：全部停在待审批，投递交给
    每日「海投发射时间」(mass_deliver_time) 与「精投发射时间」(custom_deliver_time) 定时任务。
    """
    logger.info(f"⏰ [Autopilot] 触发自动化投递任务: {datetime.now()}")

    app = pipeline_app or get_pipeline_app()
    if not app:
        logger.error("❌ 自动化管线未初始化，任务中止。")
        return None

    cfg_func = _get_active_func("get_autopilot_config", get_autopilot_config)
    config = cfg_func()
    if not config.get("is_enabled"):
        logger.info("⏸️ [Autopilot] 自动化任务大盘总开关未开启，跳过执行。")
        return None

    # 日期范围闸门：今天不在 [开始日期, 结束日期] 内则跳过本轮（空 = 不限）
    date_check_fn = _get_active_func("_check_schedule_date_range", _check_schedule_date_range)
    in_range, range_reason = date_check_fn(config)
    if not in_range:
        logger.info(f"⏭️ [Autopilot] 跳过本轮定时触发：{range_reason}")
        return None

    # 非工作日闸门：周末/法定节假日 HR 不在岗，采集评估暂停（调休补班日除外）
    workday_check_fn = _get_active_func("_check_non_workday", _check_non_workday)
    allow_run, non_workday_reason = workday_check_fn(config)
    if not allow_run:
        logger.info(f"⏭️ [Autopilot] 跳过本轮定时触发：{non_workday_reason}")
        return None

    from app.automation.full_auto import run_full_auto_pipeline
    try:
        pipeline_task_id = await run_full_auto_pipeline(stop_at_review=True)
    except RuntimeError as e:
        # 定时触发撞上正在运行的链路（并发互斥）：跳过本轮，不影响手动链路
        logger.warning(f"⏭️ [Autopilot] 跳过本轮定时触发：{e}")
        return None
    logger.info(f"🚀 [Autopilot] 全自动链路已启动（停在审批模式），pipeline_task_id={pipeline_task_id}")
    return pipeline_task_id


async def _resume_job_delivery(thread_id: str, pipeline_app: Any | None = None) -> tuple[bool, str]:
    """从人工审批断点恢复指定岗位的流水线并执行投递（thread_id = 飞书记录 record_id）。

    支持双轨：
    1. 若存在 LangGraph 状态机断点 (manual_review_node)，推进图状态机执行投递；
    2. 若岗位已放行进入「待投递」队列或断点已结束，直接从飞书读取物料通过 delivery_node 执行投递。
    返回 (是否投递成功, 结果说明)。与 /resume 和 /deliver_approved 走同一双轨机制。
    """
    from langgraph.types import Command
    app = pipeline_app or get_pipeline_app()
    config = {"configurable": {"thread_id": thread_id}}
    try:
        from app.core.feishu_utils import extract_feishu_text as _txt
        from app.core.feishu_utils import extract_job_grade, is_custom_record
        from app.services.feishu_service import TABLE_ID, get_job_record_from_feishu
        rec = await asyncio.to_thread(get_job_record_from_feishu, thread_id, TABLE_ID)
        fields = rec.get("fields", {}) if rec else {}
        follow_status = _txt(fields.get("跟进状态", "")).strip() if rec else ""
        fail_log = _txt(fields.get("自动投递失败日志", "")).strip() if rec else ""
        # 🌟 精确匹配：仅当跟进状态已投递或失败日志包含明确的 [微聊受阻] 时才开启微聊补发模式，杜绝 [物料] 缺少打招呼语误判
        retry_greeting_only = bool(follow_status == "已投递" or "[微聊受阻]" in fail_log or "微聊受阻" in fail_log)

        state = await app.aget_state(config) if (app and not retry_greeting_only) else None
        if state and state.next and state.next[0] == "manual_review_node":
            async for _ in app.astream(Command(resume=True), config):
                pass
            final = await app.aget_state(config)
            vals = (final.values or {}) if final else {}
            if vals.get("status") == "已投递":
                return True, "已投递"
            return False, str(vals.get("error") or vals.get("status") or "未知结果")[:120]
        elif not rec:
            return False, "飞书记录未找到"
        else:
            # 双轨保底：直接从飞书读取岗位物料，调用 delivery_node 进行投递（若 retry_greeting_only 则只发打招呼）
            from app.automation.workflow import delivery_node
            pdf_atts = fields.get("PDF备份") or fields.get("PDF 备份") or []
            pdf_file_name = pdf_atts[0].get("name", "").replace(".pdf", "") if pdf_atts else ""
            grade = extract_job_grade(fields).upper()
            is_custom = is_custom_record(fields)
            mock_state = {
                "job_id": thread_id,
                "record_id": thread_id,
                "platform": _txt(fields.get("招聘平台", "")) or "zhilian",
                "company_name": _txt(fields.get("公司名称", "")) or "",
                "job_name": _txt(fields.get("岗位名称", "")) or "",
                "grade": grade,
                "is_custom": is_custom,
                "pdf_filename": pdf_file_name,
                "greeting": _txt(fields.get("打招呼语", "")),
                "feishu_fields": fields,
                "final_markdown": _txt(fields.get("AI改写JSON", "")) or "",
                "retry_greeting_only": retry_greeting_only,
            }
            res = await delivery_node(mock_state)
            if res.get("status") == "已投递":
                return True, "已投递"
            return False, str(res.get("error") or "未知结果")[:120]
    except Exception as e:
        return False, f"恢复/投递异常: {str(e)[:120]}"


def _delivery_guard_ok(label: str, pipeline_app: Any | None = None) -> bool:
    """T2/T3 发射前的公共闸门：管线未初始化 / 总开关关闭 / 日期范围外 / 非工作日 / 全链路正在跑 时放弃本轮。

    日期范围与主定时采集共用同一组起止日期：范围外不仅不抓取，也不发射。
    非工作日（周末/法定节假日）HR 不在岗收不到消息，与采集闸门共用 skip_non_workdays 开关。
    """
    app = pipeline_app or get_pipeline_app()
    if not app:
        logger.error(f"❌ [{label}] 自动化管线未初始化，跳过")
        return False
    cfg_func = _get_active_func("get_autopilot_config", get_autopilot_config)
    config = cfg_func()
    if not config.get("is_enabled"):
        return False
    date_check_fn = _get_active_func("_check_schedule_date_range", _check_schedule_date_range)
    in_range, range_reason = date_check_fn(config)
    if not in_range:
        logger.info(f"⏭️ [{label}] {range_reason}，跳过本轮发射")
        return False
    workday_check_fn = _get_active_func("_check_non_workday", _check_non_workday)
    allow_run, non_workday_reason = workday_check_fn(config)
    if not allow_run:
        logger.info(f"⏭️ [{label}] {non_workday_reason}，跳过本轮发射")
        return False
    from app.automation import pipeline_broadcast as pb
    if pb.get_current_pipeline().get("running"):
        logger.info(f"⏭️ [{label}] 全链路任务正在运行中，为避免浏览器争抢跳过本轮发射")
        return False
    return True


def _is_51job_platform(platform: Any) -> bool:
    p = str(platform or "").lower()
    return "51job" in p or "前程" in p or "job51" in p


def _prioritize_51job_mass(targets: list[dict]) -> list[dict]:
    """51job 附件上传按日限次：海投岗当日只需一次上传即可全批复用，精投逐岗耗配额。
    把 51job 精投岗稳定后移到波次末尾，确保 51job 海投岗先拿到当日那一次上传；
    其余岗位（含 51job 海投）相对顺序不变。"""
    return sorted(targets, key=lambda j: 1 if (_is_51job_platform(j.get("platform")) and j.get("is_custom")) else 0)


async def _record_51job_quota_skip(job: dict, window_label: str) -> None:
    """51job 精投因当日配额耗尽被预检跳过：登记失败台账 + 回写飞书失败日志，与引擎撞墙同款 [风控] 文案。"""
    from app.automation import run_snapshot as _rs
    err = upload_quota.QUOTA_EXHAUSTED_ERROR
    _rs.record_delivery_failure(
        job_id=job["job_id"],
        error=err,
        company=job.get("company_name", ""),
        job_name=job.get("job_name", ""),
        platform=job.get("platform", "51job"),
        job_url=job.get("job_url", ""),
        grade=job.get("grade", "D"),
    )
    try:
        from app.services.feishu_service import update_feishu_record
        await asyncio.to_thread(update_feishu_record, job["job_id"], {"自动投递失败日志": err[:120]})
    except Exception as e:
        logger.warning(f"[定时投递·{window_label}] 回写 {job.get('job_id')} 51job 配额失败日志异常: {e}")


async def scheduled_delivery_batch_task(
    window_label: str = "定时发射", pipeline_app: Any | None = None
):
    """
    统一每日定时发射任务入口：与手动批量投递（/deliver_approved）共用同一把防抖锁互斥。
    手动批量运行中时本轮直接跳过——两边各自扫描「待投递」队列会对同一岗位重复打招呼，
    串行锁只保证不并发打架，不去重，必须靠互斥杜绝双通道同时发射。
    """
    try:
        from app.automation.routes.delivery_router import _deliver_worker_lock
        if _deliver_worker_lock.locked():
            logger.info(f"⏭️ [定时投递·{window_label}] 手动批量投递正在运行，跳过本轮发射（防重复投递/重复打招呼）")
            return
        async with _deliver_worker_lock:
            await _scheduled_delivery_batch_task_impl(window_label, pipeline_app)
    except ImportError:
        await _scheduled_delivery_batch_task_impl(window_label, pipeline_app)


async def _scheduled_delivery_batch_task_impl(
    window_label: str = "定时发射", pipeline_app: Any | None = None
):
    """
    统一每日定时发射任务：自动扫描飞书「待投递」队列中的全部就绪岗位并依次安全串行发射。
    若队列为空则优雅跳过；若有就绪岗位则逐个唤起双轨发射引擎（兼顾 LangGraph 状态机断点与飞书物料直接投递）。
    """
    guard_fn = _get_active_func("_delivery_guard_ok", _delivery_guard_ok)
    if not _call_guard(guard_fn, f"定时投递·{window_label}", pipeline_app=pipeline_app):
        return

    from app.services.feishu_service import get_scheduled_delivery_jobs_from_feishu
    # 波次发射尊重岗位的「定时投递时间」：未到点的岗位留给到点后的波次（看板展示不受此过滤）
    try:
        jobs = await asyncio.to_thread(get_scheduled_delivery_jobs_from_feishu, respect_scheduled_time=True)
    except TypeError:
        # 兼容旧版 mock 或单测桩代码（未接受 respect_scheduled_time 入参）
        jobs = await asyncio.to_thread(get_scheduled_delivery_jobs_from_feishu)

    now = datetime.now().strftime("%H:%M")
    if not jobs:
        logger.info(f"📭 [定时投递·{window_label} {now}] 待投递队列为空，本轮自动跳过")
        return

    cfg_func = _get_active_func("get_autopilot_config", get_autopilot_config)
    config = cfg_func()
    allowed_platforms = set(config.get("auto_deliver_platforms", ["boss", "liepin", "51job", "zhilian"]))

    # 仅发射在允许投递平台白名单中的岗位
    targets = []
    for j in jobs:
        p_raw = (j.get("platform") or "").lower()
        p_key = "zhilian" if "智联" in p_raw or "zhilian" in p_raw else \
                "boss" if "boss" in p_raw else \
                "liepin" if "猎聘" in p_raw or "liepin" in p_raw else \
                "51job" if "51job" in p_raw or "前程无忧" in p_raw else p_raw
        if p_key in allowed_platforms:
            targets.append(j)
        else:
            logger.info(f"  ⏭️ [跳过] {j.get('job_name')} 所在平台 [{p_key}] 未在自动投递平台配置中，暂不发射")

    if not targets:
        logger.info(f"📭 [定时投递·{window_label} {now}] 待投递队列中暂无命中已启用平台 ({list(allowed_platforms)}) 的岗位")
        return

    # 51job 海投优先：精投岗后移，保证海投岗先拿到当日唯一一次「我的简历」上传
    targets = _prioritize_51job_mass(targets)

    # 🌟 海投物料保鲜：发射前统一用当前海投母本重刷挂载，杜绝换了新简历后仍外发旧通用简历
    from app.automation.materials import refresh_mass_materials_for_jobs
    refreshed = await refresh_mass_materials_for_jobs(targets, label=f"定时投递·{window_label}")
    if refreshed:
        logger.info(f"♻️ [定时投递·{window_label}] 已为 {refreshed} 个海投岗位刷新最新母本物料")

    logger.info(f"🚀 [定时投递·{window_label} {now}] 命中 {len(targets)} 个符合平台规则的就绪岗位，开始依次串行发射...")
    from app.automation import abort as abort_mod
    from app.automation import run_snapshot as _rs
    from app.automation.failure_triage import (
        is_stale_quota_failure,
        should_skip_auto_delivery,
    )
    delivery_failures = _rs.get_delivery_failures()
    ok_cnt = fail_cnt = skipped_cnt = 0
    ok_jobs: list[dict[str, Any]] = []
    failed_jobs: list[tuple[dict[str, Any], str]] = []
    app = pipeline_app or get_pipeline_app()

    resume_fn = _get_active_func("_resume_job_delivery", _resume_job_delivery)

    for j in targets:
        if abort_mod.is_aborted():
            logger.warning(f"🛑 [定时投递·{window_label}] 检测到全局终止信号 (abort)，安全中止后续岗位发射")
            break

        current_jid = str(j.get("job_id") or "")
        if not current_jid:
            continue

        # 往日 51job 配额耗尽已随日期重置：先执行跨天自愈摘除，让今日发射从干净状态恢复
        failure = delivery_failures.get(current_jid)
        if failure and is_stale_quota_failure(failure):
            logger.info(f"  ♻️ [跨天重置] {j.get('job_name')} 昨日因 51job 上传配额耗尽被拦，今日配额已重置，恢复发射")
            _rs.remove_delivery_failure(j["job_id"])
            delivery_failures.pop(current_jid, None)
            failure = None

        # L1 失败分诊守卫：
        # - 持久性故障（引擎/物料/下架等）或暂时性故障重试已达上限的岗位，波次拒绝自动拉起，留待人工审批或人工重试；
        # - 处于重试上限内的暂时性故障（如网络抖动/标签页丢失）或已获得老板人工重试审批的岗位，放行波次自动发射（享受 L2 浏览器自愈红利）。
        if current_jid in delivery_failures and not _rs.is_job_retrying(current_jid):
            skip, reason = should_skip_auto_delivery(failure) if failure else (True, "在失败台账中未获审批重试")
            if skip:
                logger.warning(f"  ⛔ [失败拦截] {j.get('job_name')} {reason}，波次拒绝自动拉起")
                skipped_cnt += 1
                continue
            else:
                logger.info(f"  🔄 [分诊放行] {j.get('job_name')} 属于可重试暂时性故障，波次尝试自动重试发射")

        # 双保险：岗位若仍暂停在审批断点且从未获得老板放行标记，说明「待投递」门牌是残留/泄露，
        # 回写「海投人工复核」并跳过本轮发射，待老板审批后由下一轮波次放行。
        graph_state = None
        if app:
            try:
                graph_state = await app.aget_state({"configurable": {"thread_id": j["job_id"]}})
            except Exception as e:
                logger.warning(f"[定时投递·{window_label}] 查询 {j.get('job_id')} 图状态异常（按已放行处理）: {e}")
        if (graph_state and getattr(graph_state, "next", None)
                and graph_state.next[0] == "manual_review_node"
                and not automation_db.has_approval_mark(j["job_id"])):
            logger.warning(f"  ⛔ [跳过] {j.get('job_name')} 仍停在审批断点且无老板放行标记，回写「海投人工复核」待审")
            skipped_cnt += 1
            try:
                from app.services.feishu_service import update_feishu_record
                await asyncio.to_thread(update_feishu_record, j["job_id"], {"跟进状态": "海投人工复核"})
            except Exception as e:
                logger.warning(f"[定时投递·{window_label}] 回写 {j.get('job_id')} 门牌失败: {e}")
            continue
        # 51job 精投配额预检：今日已撞 720721 则不唤起引擎，登记 [风控] 失败留待次日
        if _is_51job_platform(j.get("platform")) and j.get("is_custom") and upload_quota.is_exhausted_today():
            logger.warning(f"  ⛔ [51job 配额] {j.get('job_name')} ({j.get('company_name')}) 今日附件上传配额已耗尽，精投留待次日自动重试或手动投递")
            fail_cnt += 1
            failed_jobs.append((j, "51job今日附件上传配额已耗尽"))
            await _record_51job_quota_skip(j, window_label)
            continue
        logger.info(f"  → 发射: {j.get('job_name')} ({j.get('company_name')}) [{j.get('platform')}]")
        _rs.mark_job_delivering([current_jid])
        try:
            okflag, msg = await _call_resume(resume_fn, j["job_id"], pipeline_app=app)
        finally:
            _rs.unmark_job_delivering([current_jid])
        if okflag:
            ok_cnt += 1
            ok_jobs.append(j)
            logger.info(f"    ✅ {msg}")
            _rs.remove_delivery_failure(j["job_id"])
        else:
            fail_cnt += 1
            failed_jobs.append((j, msg))
            logger.error(f"    ❌ {msg}")
            _rs.record_delivery_failure(
                job_id=j["job_id"],
                error=msg,
                company=j.get("company_name", ""),
                job_name=j.get("job_name", ""),
                platform=j.get("platform", "zhilian"),
                job_url=j.get("job_url", ""),
                grade=j.get("grade", "D")
            )
            # 🌟 同步将飞书「跟进状态」写入为「投递失败」
            try:
                from app.services.feishu_service import mark_job_delivery_failed
                await asyncio.to_thread(mark_job_delivery_failed, j["job_id"], msg)
            except Exception as f_err:
                logger.warning(f"[定时投递·{window_label}] 回写飞书投递失败异常 ({j.get('job_id')}): {f_err}")
            # L2 自愈：环境类故障（僵尸标签页/页面失效等）失败瞬间自动重启平台浏览器，
            # 让下一轮波次大概率自愈成功；结果记入失败台账 heal_log 供 L3 诊断与前端展示
            try:
                from app.automation.self_heal import append_heal_log, run_self_heal
                heal = await run_self_heal(j.get("platform", ""), msg)
                append_heal_log(j["job_id"], heal)
            except Exception as heal_e:
                logger.warning(f"[定时投递·{window_label}] 自愈动作异常（不影响流程）: {heal_e}")
            # L3 诊断：连续失败达阈值的岗位自动产出 AI 诊断报告（旁路，不阻塞波次）
            diagnose_fn = _get_active_func("_auto_diagnose", _auto_diagnose)
            asyncio.create_task(diagnose_fn(j["job_id"]))
    logger.info(f"🎯 [定时投递·{window_label}] 完成：成功 {ok_cnt} · 失败 {fail_cnt}")

    # 飞书自动投递卡片同步：发送每轮投递战报卡片到聊天框
    try:
        from app.services.delivery_card_notifier import send_delivery_round_report
        await send_delivery_round_report(
            window_label=window_label,
            total_targets=len(targets),
            ok_jobs=ok_jobs,
            failed_jobs=failed_jobs,
            skipped_cnt=skipped_cnt,
        )
    except Exception as rep_e:
        logger.warning(f"[定时投递·{window_label}] 投递战报卡片发送异常（不阻断链路）: {rep_e}")

    # 整波收尾：关闭引擎侧批次内常驻浏览器，避免 Edge 后台空转占内存
    try:
        from app.automation.routes.delivery_router import _shutdown_zhilian_browser
        _shutdown_zhilian_browser()
    except Exception as e:
        logger.warning(f"[定时投递·{window_label}] 关闭常驻浏览器异常（不影响流程）: {e}")


async def _auto_diagnose(job_id: str):
    """失败登记后旁路触发 AI 诊断（连续失败达 DIAG_THRESHOLD 才真正执行）。"""
    try:
        from app.automation import run_snapshot as _rs
        from app.automation.diag_agent import diagnose_failure, needs_diagnosis
        failure = (_rs.get_delivery_failures() or {}).get(str(job_id))
        if failure and needs_diagnosis(failure):
            result = await diagnose_failure(job_id)
            diag = (result or {}).get("data") or {}
            logger.info(f"🔬 [DiagAgent] 岗位 {job_id} 自动诊断完成: {diag.get('category')} - {diag.get('root_cause', '')[:80]}")
    except Exception as e:
        logger.warning(f"[DiagAgent] 自动诊断异常（不影响流程）: {e}")


async def mass_delivery_task(pipeline_app: Any | None = None):
    """上午发射时段 (波次一) 每日定时任务：自动扫描「待投递」队列并依次串行投递。"""
    batch_fn = _get_active_func("scheduled_delivery_batch_task", scheduled_delivery_batch_task)
    await batch_fn("上午波次", pipeline_app=pipeline_app)


async def custom_delivery_task(pipeline_app: Any | None = None):
    """下午发射时段 (波次二) 每日定时任务：自动扫描「待投递」队列并依次串行投递。"""
    batch_fn = _get_active_func("scheduled_delivery_batch_task", scheduled_delivery_batch_task)
    await batch_fn("下午波次", pipeline_app=pipeline_app)
