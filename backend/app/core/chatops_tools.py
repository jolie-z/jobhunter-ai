"""
ChatOps 工具集 — 飞书机器人可调用的全部能力

设计原则：
- 同类操作合并为一个 tool + action 参数（控制总数 ≤ 16）
- 异步操作通过 run_coroutine_threadsafe 调度到主事件循环
- 每个 tool 返回纯文本结果，由 Agent 组织最终回复
"""

import asyncio
import json
import os
import sqlite3
import sys

from langchain_core.tools import tool

# 路径
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.dirname(CURRENT_DIR)
PROJECT_ROOT = os.path.dirname(APP_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

DB_PATH = os.path.join(PROJECT_ROOT, "data", "job_hunter.db")

# 由 agent_router.process_chatops_query 在每次消息处理时设置
_main_loop: asyncio.AbstractEventLoop | None = None
_current_chat_id: str | None = None
_pending_pipeline_task_id: str | None = None


def set_runtime_context(loop: asyncio.AbstractEventLoop, chat_id: str):
    """由 agent_router 调用，设置当前运行时上下文。"""
    global _main_loop, _current_chat_id
    _main_loop = loop
    _current_chat_id = chat_id


# ==========================================
# 辅助：异步调度
# ==========================================
def _run_async(coro, timeout: int = 60):
    """在主事件循环上执行协程并等待结果。"""
    if _main_loop is None:
        raise RuntimeError("主事件循环未初始化")
    future = asyncio.run_coroutine_threadsafe(coro, _main_loop)
    return future.result(timeout=timeout)


# ==========================================
# 1. run_full_pipeline — 全链路
# ==========================================
@tool
def run_full_pipeline(keyword: str = "", city: str = "", salary: str = "", target_jobs: int = 0, platforms: str = "") -> str:
    """启动全链路自动化流水线（抓取→清洗→飞书同步→AI评估→简历改写→自动投递）。所有参数可选，不传则使用自动驾驶配置。"""
    global _pending_pipeline_task_id

    async def _trigger():
        from app.automation.full_auto import run_full_auto_pipeline
        return await run_full_auto_pipeline(
            keyword=keyword or None, city=city or None, salary=salary or None,
            target_jobs=target_jobs if target_jobs > 0 else None,
            platforms=[p.strip() for p in platforms.split(",") if p.strip()] if platforms else None
        )

    try:
        task_id = _run_async(_trigger(), timeout=30)
        _pending_pipeline_task_id = task_id
        params = []
        if keyword:
            params.append(f"关键词={keyword}")
        if city:
            params.append(f"城市={city}")
        if salary:
            params.append(f"薪资={salary}")
        if target_jobs:
            params.append(f"目标={target_jobs}个")
        if platforms:
            params.append(f"平台={platforms}")
        desc = "、".join(params) if params else "使用自动驾驶默认配置"
        return f"✅ 全链路流水线已启动！\n📋 参数: {desc}\n🆔 任务ID: {task_id}\n\n流水线将依次执行: 抓取→清洗→飞书同步→AI评估→简历改写→投递。各阶段完成后会自动汇报进度。"
    except Exception as e:
        return f"❌ 全链路启动失败: {str(e)}"


# ==========================================
# 2. run_scraping — 多平台抓取
# ==========================================
@tool
def run_scraping(keyword: str, city: str = "全国", salary: str = "不限", target_jobs: int = 30, platforms: str = "boss,liepin,51job,zhilian") -> str:
    """仅执行岗位抓取阶段（不触发后续评估和投递）。支持指定平台（逗号分隔：boss,liepin,51job,zhilian,xhs）。"""
    import uuid as _uuid

    master_task_id = f"scrape_{_uuid.uuid4().hex[:8]}"

    async def _scrape():
        from app.api.routes.crawlers import run_dispatch_collect
        pf = [p.strip() for p in platforms.split(",") if p.strip()]
        return await run_dispatch_collect(
            keyword=keyword, city=city, salary=salary,
            target_jobs=target_jobs, platforms=pf, master_task_id=master_task_id
        )

    try:
        sub_tasks = _run_async(_scrape(), timeout=60)
        task_desc = "\n".join([f"  · {t['platform']}: {t['keyword']} | {t['city']} | 目标{t['target_jobs']}个" for t in sub_tasks])
        platform_display = ",".join({t['platform'] for t in sub_tasks})

        # 启动后台完成监控
        from app.core.chatops_monitors import start_scraping_monitor
        start_scraping_monitor(master_task_id, [t['task_id'] for t in sub_tasks], keyword, city, target_jobs, platform_display, _main_loop, _current_chat_id)

        return f"✅ 抓取任务已分发！\n📋 关键词={keyword} | 城市={city} | 薪资={salary}\n🖥️ 平台任务:\n{task_desc}\n\n各平台爬虫正在后台并发执行，完成后会自动汇报结果。"
    except Exception as e:
        return f"❌ 抓取分发失败: {str(e)}"


# ==========================================
# 3. run_cleaning — 数据清洗
# ==========================================
@tool
def run_cleaning() -> str:
    """执行数据清洗与规则过滤（step1），将原始岗位数据中的垃圾/不合规条目过滤掉。"""
    async def _clean():
        from job_processor.step1_rule_filter import _async_run_pipeline
        return await _async_run_pipeline()

    try:
        result = _run_async(_clean(), timeout=120)
        return f"✅ 数据清洗完毕！\n📊 结果: {result}"
    except Exception as e:
        return f"❌ 数据清洗失败: {str(e)}"


# ==========================================
# 4. approve_delivery — 审批
# ==========================================
@tool
def approve_delivery(thread_ids: str = "", action: str = "approve") -> str:
    """审批放行或拒绝待投递的岗位。thread_ids 为逗号分隔的线程ID列表。action 可选 approve/reject。"""
    async def _resume():
        from langgraph.types import Command

        from app.automation.scheduler import pipeline_app

        if not thread_ids:
            return "⚠️ 请提供需要审批的 thread_ids（逗号分隔）。可以先用 check_progress 查看待审批列表。"

        tids = [t.strip() for t in thread_ids.split(",") if t.strip()]
        action_value = action.lower() in ("approve", "yes", "放行", "通过")
        results = []

        for tid in tids:
            config = {"configurable": {"thread_id": tid}}
            try:
                snapshot = await pipeline_app.aget_state(config)
                if not snapshot or not snapshot.next:
                    results.append(f"  · {tid}: 无活跃断点，跳过")
                    continue
                async for _ in pipeline_app.astream(Command(resume=action_value), config):
                    pass
                results.append(f"  · {tid}: {'✅ 已放行投递' if action_value else '🚫 已拒绝'}")
            except Exception as e:
                results.append(f"  · {tid}: ❌ {str(e)}")

        return "\n".join(results)

    try:
        return _run_async(_resume(), timeout=60)
    except Exception as e:
        return f"❌ 审批操作失败: {str(e)}"


# ==========================================
# 5. check_progress — 进度查询
# ==========================================
@tool
def check_progress(task_id: str = "") -> str:
    """查询当前任务进度。传入任务ID可查看特定任务；不传则列出所有活跃任务。"""
    async def _check():
        from app.tasks.state import task_queues

        if task_id and task_id in task_queues:
            queue = task_queues[task_id]
            messages = []
            while not queue.empty():
                try:
                    messages.append(queue.get_nowait())
                except Exception:
                    break
            return f"📡 任务 {task_id} 最近进度:\n" + "\n".join(messages[-10:]) if messages else f"📡 任务 {task_id} 暂无新进度。"

        active = list(task_queues.keys())
        if not active:
            return "📭 当前没有活跃任务。"
        result = f"📋 当前活跃任务: {len(active)} 个\n" + "\n".join([f"  · {t}" for t in active[:20]])
        return result

    try:
        return _run_async(_check(), timeout=15)
    except Exception as e:
        return f"❌ 进度查询失败: {str(e)}"


# ==========================================
# 6. search_job_database — 数据库查询
# ==========================================
@tool
def search_job_database(target_table: str = "raw_jobs", sql_where_clause: str = "", limit: int = 10) -> str:
    """查询本地数据库中的岗位数据。target_table 可选: raw_jobs, feishu_jobs。"""
    if target_table not in ("raw_jobs", "feishu_jobs"):
        return "❌ target_table 必须是 raw_jobs 或 feishu_jobs。"

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        count_sql = f"SELECT COUNT(*) as total FROM {target_table}"
        if sql_where_clause:
            count_sql += f" WHERE {sql_where_clause}"
        total = cursor.execute(count_sql).fetchone()["total"]
        if total == 0:
            return "🔍 查询成功，找到 0 条数据。"

        query = f"SELECT * FROM {target_table}"
        if sql_where_clause:
            query += f" WHERE {sql_where_clause}"
        query += f" LIMIT {limit}"
        rows = cursor.fetchall()
        preview = [dict(r) for r in rows]
        for item in preview:
            item.pop("jd_text", None)

        return f"✅ 查询成功！共 {total} 条，本次返回 {len(rows)} 条。\n数据预览：{json.dumps(preview[:3], ensure_ascii=False)}"
    except Exception as e:
        return f"❌ SQL 执行失败: {str(e)}"
    finally:
        conn.close()


# ==========================================
# 7. update_feishu_records — 飞书记录更新
# ==========================================
@tool
def update_feishu_records(record_ids: str = "", update_fields: str = "") -> str:
    """批量更新飞书多维表格记录。record_ids 为逗号分隔的记录ID，update_fields 为 JSON 格式字段字典。"""
    import time

    from app.services.feishu_service import update_feishu_record

    if not record_ids or not update_fields:
        return "❌ 缺少 record_ids 或 update_fields"

    rids = [r.strip() for r in record_ids.split(",") if r.strip()]
    try:
        fields = json.loads(update_fields) if isinstance(update_fields, str) else update_fields
    except json.JSONDecodeError:
        return "❌ update_fields 必须是合法 JSON"

    success, fail = 0, 0
    for rid in rids:
        try:
            if update_feishu_record(rid, fields):
                success += 1
            else:
                fail += 1
        except Exception:
            fail += 1
        time.sleep(0.3)

    return f"✅ 批量更新完毕！成功: {success}, 失败: {fail}"


# ==========================================
# 8. manage_goals — 求职目标管理
# ==========================================
@tool
def manage_goals(action: str = "get", daily_deliver: int = 0, daily_scrape: int = 0, target_offer: int = 0) -> str:
    """管理求职目标。action 可选: get(查看进度), start(设定目标), update(更新目标), finish(结束求职)。"""
    try:
        if action == "get":
            from app.services.goal_service import get_current_goals
            goals = get_current_goals()
            if not goals:
                return "📭 尚未设定求职目标。说「设定目标」开始。"
            return f"📊 当前求职目标:\n{json.dumps(goals, ensure_ascii=False, indent=2)}"

        elif action == "start":
            from app.services.goal_service import start_goals
            params = {}
            if daily_deliver:
                params["daily_deliver_target"] = daily_deliver
            if daily_scrape:
                params["daily_scrape_target"] = daily_scrape
            if target_offer:
                params["target_offer"] = target_offer
            result = start_goals(params)
            return f"🎯 求职目标已设定！\n{json.dumps(result, ensure_ascii=False)}"

        elif action == "update":
            from app.services.goal_service import update_goals
            params = {}
            if daily_deliver:
                params["daily_deliver_target"] = daily_deliver
            if daily_scrape:
                params["daily_scrape_target"] = daily_scrape
            if target_offer:
                params["target_offer"] = target_offer
            result = update_goals(params)
            return f"✅ 目标已更新！\n{json.dumps(result, ensure_ascii=False)}"

        elif action == "finish":
            from app.services.goal_service import finish_goals
            result = finish_goals()
            return f"🎉 恭喜！求职目标已标记为完成！\n{json.dumps(result, ensure_ascii=False)}"

        else:
            return "❌ action 必须是 get/start/update/finish 之一。"
    except Exception as e:
        return f"❌ 目标管理失败: {str(e)}"


# ==========================================
# 9. send_report — 战报推送
# ==========================================
@tool
def send_report(period: str = "daily") -> str:
    """生成并发送战报到飞书群。period 可选: daily(日报), weekly(周报), monthly(月报), final(终报)。"""
    async def _send():
        if period == "daily":
            from app.services.report_feishu import send_daily_report
            await send_daily_report()
            return "✅ 日报已生成并发送到飞书群！"
        elif period == "weekly":
            from app.services.report_feishu import send_weekly_report
            await send_weekly_report()
            return "✅ 周报已生成并发送到飞书群！"
        elif period == "monthly":
            from app.services.report_feishu import send_monthly_report
            await send_monthly_report()
            return "✅ 月报已生成并发送到飞书群！"
        elif period == "final":
            from app.services.report_feishu import send_final_report
            await send_final_report()
            return "✅ 终报已生成并发送到飞书群！"
        else:
            return "❌ period 必须是 daily/weekly/monthly/final 之一。"

    try:
        return _run_async(_send(), timeout=60)
    except Exception as e:
        return f"❌ 战报生成失败: {str(e)}"


# ==========================================
# 10. get_dashboard — 数据看板
# ==========================================
@tool
def get_dashboard(view: str = "overview") -> str:
    """查看求职数据看板。view 可选: overview(总览), funnel(漏斗), platform(平台对比), trend(趋势)。"""
    async def _get():
        from app.api.routes.analytics_dashboard import (
            get_funnel,
            get_overview,
            get_platform_stats,
            get_trend,
        )
        if view == "overview":
            return await get_overview()
        elif view == "funnel":
            return await get_funnel()
        elif view == "platform":
            return await get_platform_stats()
        elif view == "trend":
            return await get_trend()
        else:
            return None

    try:
        if view not in ("overview", "funnel", "platform", "trend"):
            return "❌ view 必须是 overview/funnel/platform/trend 之一。"
        data = _run_async(_get(), timeout=30)
        if data is None:
            return "📭 暂无数据。"
        return f"📊 数据看板 ({view}):\n{json.dumps(data, ensure_ascii=False, indent=2)}"
    except Exception as e:
        return f"❌ 看板查询失败: {str(e)}"


# ==========================================
# 11. check_login_status — 平台登录态
# ==========================================
@tool
def check_login_status(platform: str = "") -> str:
    """检查各平台浏览器登录状态。platform 留空检查全部，或指定单个平台（boss,liepin,51job,zhilian）。"""
    # session_manager.check_one/check_all 是同步方法（返回 SessionStatus/dict），
    # 历史版本对它们 await 必抛 TypeError；直接同步调用即可
    try:
        from app.session.manager import session_manager
        from app.session.models import SessionState

        def _icon(state: SessionState) -> str:
            return "🟢" if state == SessionState.HEALTHY else "🔴" if state == SessionState.EXPIRED else "🟡"

        if platform:
            s = session_manager.check_one(platform, force=True)
            return f"🖥️ 平台登录状态:\n  {_icon(s.state)} {s.platform}: {s.state.value}（{s.message}）"

        statuses = session_manager.check_all(force=True)
        lines = [f"  {_icon(s.state)} {plat}: {s.state.value}" for plat, s in statuses.items()]
        return "🖥️ 平台登录状态:\n" + "\n".join(lines)
    except Exception as e:
        return f"❌ 登录状态检查失败: {str(e)}"


# ==========================================
# 12. batch_task — 批量AI任务
# ==========================================
@tool
def batch_task(task_type: str = "evaluate", job_ids: str = "") -> str:
    """批量执行AI任务。task_type 可选: evaluate(评估), rewrite(改写), deep_evaluate(深度评估), deliver(投递)。job_ids 为逗号分隔的岗位ID，留空则处理所有待处理岗位。"""
    valid_types = ("evaluate", "rewrite", "deep_evaluate", "deliver")
    if task_type not in valid_types:
        return f"❌ task_type 必须是 {'/'.join(valid_types)} 之一。"

    async def _run():
        import asyncio as _aio
        import uuid

        from app.tasks.service import run_batch_ai_task
        from app.tasks.state import task_queues, task_status

        tid = f"batch_{task_type}_{uuid.uuid4().hex[:6]}"
        queue: _aio.Queue = _aio.Queue()
        task_queues[tid] = queue

        ids = [j.strip() for j in job_ids.split(",") if j.strip()] if job_ids else None
        # 引擎会读写 task_status[tid]，必须先注册（此前缺失导致引擎 KeyError 静默死亡）
        task_status[tid] = {"status": "pending", "task_type": task_type, "total": len(ids) if ids else 0}
        # 后台执行，不阻塞
        _aio.ensure_future(run_batch_ai_task(tid, task_type, ids, queue))
        return tid

    try:
        tid = _run_async(_run(), timeout=10)
        type_names = {"evaluate": "AI评估", "rewrite": "简历改写", "deep_evaluate": "深度评估", "deliver": "自动投递"}
        return f"✅ 批量{type_names.get(task_type, task_type)}任务已启动！\n🆔 任务ID: {tid}\n\n任务在后台执行中，完成后数据会自动更新到飞书表格。"
    except Exception as e:
        return f"❌ 批量任务启动失败: {str(e)}"


# ==========================================
# 13. import_job — 岗位录入
# ==========================================
@tool
def import_job(text: str = "") -> str:
    """快速录入岗位到飞书表格。粘贴招聘信息的文本内容即可，AI 会自动解析字段并建档。注意：岗位截图老板在聊天框直接发图即可自动识别录入，无需调用本工具。"""
    if not text:
        return "❌ 请提供需要录入的岗位文本内容。"

    async def _import():
        from app.jobs.service import (
            format_job_import_summary,
            import_job_from_text_service,
        )
        data = await import_job_from_text_service(text)
        return format_job_import_summary(data)

    try:
        return _run_async(_import(), timeout=120)
    except Exception as e:
        from app.jobs.service import DuplicateJobError, InvalidJobFieldsError
        if isinstance(e, DuplicateJobError):
            dup = e.existing or {}
            c = dup.get("公司名称", "")
            j = dup.get("岗位名称", "")
            s = dup.get("跟进状态", "未知")
            r = dup.get("review_url", "")
            msg = f"⚠️ 录入已拦截：该岗位与飞书已有记录疑似重复（{c} - {j}，当前状态：{s}）。"
            if r:
                msg += f"\n👉 查看已有记录：{r}"
            return msg
        if isinstance(e, InvalidJobFieldsError):
            missing_str = "、".join(e.missing)
            return f"⚠️ 录入已拦截：文本未能提取到必要的核心字段（{missing_str}），为避免脏数据未予建档，请补充完整 JD 内容后重试。"
        return f"❌ 岗位录入失败: {str(e)}"


# ==========================================
# 14. interview_prep — 面试准备
# ==========================================
@tool
def interview_prep(action: str = "handbook", job_id: str = "") -> str:
    """面试准备工具。action 可选: handbook(生成面试锦囊), init(初始化面试训练营)。需要提供 job_id。"""
    if not job_id:
        return "❌ 请提供 job_id（岗位记录ID）。"

    try:
        if action == "handbook":
            async def _gen():
                from app.interview.service import generate_handbook_action
                return await generate_handbook_action(job_id)

            result = _run_async(_gen(), timeout=120)
            return f"✅ 面试锦囊已生成！\n{result}"

        elif action == "init":
            async def _init():
                from app.copilot.router import init_interviewer_action
                return await init_interviewer_action(job_id)

            result = _run_async(_init(), timeout=120)
            return f"✅ 面试训练营已初始化！\n{result}"

        else:
            return "❌ action 必须是 handbook 或 init。"
    except Exception as e:
        return f"❌ 面试准备失败: {str(e)}"


# ==========================================
# 15. resume_ops — 简历操作
# ==========================================
@tool
def resume_ops(action: str = "diagnosis", job_id: str = "") -> str:
    """简历相关操作。action 可选: diagnosis(全局诊断), rewrite(改写), greeting(生成打招呼语), ats_check(ATS预检)。"""
    try:
        if action == "diagnosis":
            async def _diag():
                from app.strategy.router import global_diagnosis_service
                return await global_diagnosis_service()
            result = _run_async(_diag(), timeout=60)
            return f"📋 简历诊断结果:\n{result}"

        elif action == "greeting":
            if not job_id:
                return "❌ 生成打招呼语需要提供 job_id。"
            async def _greet():
                from app.strategy.router import generate_greeting_and_save_service
                return await generate_greeting_and_save_service(job_id)
            result = _run_async(_greet(), timeout=60)
            return f"💬 打招呼语已生成:\n{result}"

        elif action == "rewrite":
            if not job_id:
                return "❌ 简历改写需要提供 job_id。"
            async def _rw():
                from app.strategy.router import skill_rewrite_and_save_service
                return await skill_rewrite_and_save_service(job_id)
            result = _run_async(_rw(), timeout=120)
            return f"✍️ 简历改写完成:\n{result}"

        elif action == "ats_check":
            if not job_id:
                return "❌ ATS预检需要提供 job_id。"
            async def _ats():
                from app.strategy.router import ats_align_service
                return await ats_align_service(job_id)
            result = _run_async(_ats(), timeout=60)
            return f"🎯 ATS预检结果:\n{result}"

        else:
            return "❌ action 必须是 diagnosis/rewrite/greeting/ats_check 之一。"
    except Exception as e:
        return f"❌ 简历操作失败: {str(e)}"


# ==========================================
# 16. manage_strategy — 策略配置
# ==========================================
@tool
def manage_strategy(action: str = "get", cron_time: str = "", is_enabled: str = "") -> str:
    """管理自动化策略配置。action 可选: get(查看当前策略), set_cron(修改定时任务时间), get_preferences(查看求职偏好)。"""
    try:
        if action == "get":
            from app.automation.db import get_autopilot_config
            config = get_autopilot_config()
            return f"⚙️ 当前自动化配置:\n{json.dumps(config, ensure_ascii=False, indent=2)}"

        elif action == "set_cron":
            if not cron_time:
                return "❌ 请提供 cron_time（如 '08:00'）。"
            from app.automation.scheduler import update_scheduler_cron
            enabled = is_enabled.lower() in ("true", "1", "yes", "是") if is_enabled else True
            update_scheduler_cron(cron_time, enabled)
            return f"✅ 定时任务已更新为每日 {cron_time}，{'已启用' if enabled else '已禁用'}。"

        elif action == "get_preferences":
            from app.services.feishu_service import get_my_preferences
            prefs = get_my_preferences()
            if not prefs:
                return "📭 尚未配置求职偏好。"
            return f"📋 求职偏好:\n{json.dumps(prefs, ensure_ascii=False, indent=2)}"

        else:
            return "❌ action 必须是 get/set_cron/get_preferences 之一。"
    except Exception as e:
        return f"❌ 策略管理失败: {str(e)}"


# ==========================================
# 工具注册列表
# ==========================================
ALL_TOOLS = [
    run_full_pipeline,
    run_scraping,
    run_cleaning,
    approve_delivery,
    check_progress,
    search_job_database,
    update_feishu_records,
    manage_goals,
    send_report,
    get_dashboard,
    check_login_status,
    batch_task,
    import_job,
    interview_prep,
    resume_ops,
    manage_strategy,
]
