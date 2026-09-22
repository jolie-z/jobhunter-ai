import asyncio
import functools
import inspect
import logging
import os
from contextlib import asynccontextmanager

import sentry_sdk
from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.routing import APIRoute
from starlette.middleware.cors import CORSMiddleware

# 🌟 强制注入 NO_PROXY，让 Python requests/urllib/httpx 自动绕过系统/VPN代理直连飞书及本地服务
_default_no_proxy = "localhost,127.0.0.1,open.feishu.cn,*.feishu.cn,feishu.cn"
os.environ["NO_PROXY"] = f"{_default_no_proxy},{os.environ.get('NO_PROXY', '')}".strip(",")
os.environ["no_proxy"] = os.environ["NO_PROXY"]

# 🌟 启动最早期把 settings.json（配置页保存的值）注入 os.environ 与 pydantic settings 单例，
# 保证下方全部路由 import 时读到的 FEISHU_*/OPENAI_* 都是页面配置的最新值
from common.config import (  # noqa: E402
    sync_settings_to_runtime as _sync_settings_to_runtime,
)

_sync_settings_to_runtime()

from ai_agents import ai_evaluator, ai_scorer  # noqa: E402
from app.api.main import api_router  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.jobs.router import router as jobs_router  # noqa: E402


# ==========================================
# 🌟 日志静默过滤器 (保留，用来过滤掉烦人的轮询日志)
# ==========================================
class EndpointFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if any(path in message for path in [
            "/api/tasks/status",
            "/api/strategy/config",
            "/api/v1/crawlers/status",
            "/api/v1/processor/stats",
            "/api/analytics/tokens",
            "/api/jobs",
        ]):
            return False
        return True

logging.getLogger("uvicorn.access").addFilter(EndpointFilter())

# 屏蔽开发模式下 watchfiles 的刷屏日志 (比如浏览器缓存文件的变动)
logging.getLogger("watchfiles.main").setLevel(logging.WARNING)
# 屏蔽 httpx 的刷屏日志 (比如请求飞书接口时的 INFO 日志)
logging.getLogger("httpx").setLevel(logging.WARNING)

# ==========================================
# 🌟 自动链路追踪监控系统 (白盒化增强：附带业务中文注释与目标上下文)
# ==========================================
_FUNC_DESCRIPTIONS = {
    # 初评相关 (ai_evaluator.py)
    "warmup_eval_cache": "Wave 1 初评母本前缀 1-token 点火预热",
    "evaluate_single_job": "执行单岗位 8 维度客观深度初评",
    "_call_10dim_evaluation": "大模型 8 维度初评打分与理由解析",
    "get_dynamic_weights": "读取 8 维度加权权重配置",
    "_format_rationales_text": "结构化格式化 8 维度打分依据",
    "get_auto_eval_threshold": "读取自动化门禁评级阈值",
    "load_resume": "读取云端启用状态的母本简历",

    # 深度画像相关 (ai_scorer.py)
    "warmup_deep_eval_cache": "Wave 2 深度画像母本前缀 1-token 点火预热",
    "deep_evaluate_resume": "执行岗位理想画像、能力词典与逐行审计",
    "get_user_preferences": "读取求职底线与加分偏好规则",
    "search_company_info_tavily": "Tavily 外部公司情报检索(备用)",
    "parse_resume_markdown": "Markdown 简历结构化分段解析",

    # 简历改写与打招呼 (skill_rewrite.py & skill_greeting.py)
    "warmup_rewrite_cache": "Wave 3 改写母本前缀 1-token 点火预热",
    "process_resume_rewrite": "执行基于 Skill 的专属定制简历重塑",
    "run_skill_based_rewrite": "调用大模型执行专业定制简历改写",
    "process_greeting_generation": "生成针对该岗位的高情商破冰语",
    "run_skill_based_greeting": "调用大模型生成定制破冰打招呼语",
    "truth_boundary_check": "Truth Boundary 事实边界安全阀扫描与降级",

    # 公司商业情报 (company_intel.py)
    "research_company_serper": "Serper 并发搜索公司商业背景与外部情报",
    "search_company_ai_news": "Serper 4路并发多维商业情报侦察引擎",

    # 波次流水线调度 (wave_pipeline.py)
    "run_wave_evaluation_pipeline": "三波次漏斗流水线主调度控制器",
    "send_sse_msg": "向前端推送实时微进度与Token状态",
}


def _get_call_desc(func, args, kwargs) -> str:
    name = func.__name__
    desc = _FUNC_DESCRIPTIONS.get(name)
    if not desc:
        doc = (inspect.getdoc(func) or "").strip()
        desc = doc.splitlines()[0].strip() if doc else "核心业务逻辑处理"

    # 尝试从参数提取当前正在处理的目标（公司名/岗位名）
    target = ""
    for k in ("job_name", "job_title", "company", "company_name"):
        if k in kwargs and kwargs[k]:
            target = str(kwargs[k])
            break
    if not target and args:
        for a in args:
            if isinstance(a, dict):
                c = a.get("company") or a.get("company_name")
                j = a.get("job_title") or a.get("job_name")
                if c and j:
                    target = f"{c} · {j}"
                    break
                elif c or j:
                    target = str(c or j)
                    break
            elif isinstance(a, str) and 2 <= len(a) <= 40 and not a.startswith("{") and not a.startswith("#") and "\n" not in a:
                if any(kw in name for kw in ("company", "serper", "greeting", "rewrite")):
                    target = a
                    break
    if target:
        return f"{desc} | 目标: {target}"
    return desc


def track_call(func):
    if inspect.iscoroutinefunction(func):
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            try:
                file_path = inspect.getfile(func)
                rel_path = os.path.relpath(file_path, os.getcwd())
            except (TypeError, ValueError):
                rel_path = func.__module__
            desc = _get_call_desc(func, args, kwargs)
            print(f"👣 [Trace] {rel_path} -> {func.__name__} ({desc})")
            return await func(*args, **kwargs)
        return async_wrapper
    else:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                file_path = inspect.getfile(func)
                rel_path = os.path.relpath(file_path, os.getcwd())
            except (TypeError, ValueError):
                rel_path = func.__module__
            desc = _get_call_desc(func, args, kwargs)
            print(f"👣 [Trace] {rel_path} -> {func.__name__} ({desc})")
            return func(*args, **kwargs)
        return wrapper


def apply_trace_to_module(module):
    for name, obj in inspect.getmembers(module):
        # 核心：只追踪本文件自己写的函数，不追踪从外面 import 进来的库函数
        if inspect.isfunction(obj) and obj.__module__ == module.__name__:
            setattr(module, name, track_call(obj))


# 在这里挂载你需要自动打印链路的文件
apply_trace_to_module(ai_evaluator)
apply_trace_to_module(ai_scorer)

print("🚀 [监控系统] 业务逻辑链路监控已重新挂载！")
# ==========================================
# 🚀 FastAPI 实例初始化
# ==========================================
def custom_generate_unique_id(route: APIRoute) -> str:
    tag = route.tags[0] if route.tags else "default"
    return f"{tag}-{route.name}"

if settings.SENTRY_DSN and settings.ENVIRONMENT != "local":
    sentry_sdk.init(dsn=str(settings.SENTRY_DSN), enable_tracing=True)


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001  # FastAPI lifespan 协议签名
    """FastAPI lifespan: init/close Playwright PDF renderer and Automation Scheduler."""
    from app.automation import console_stream
    from app.automation.scheduler import init_automation_pipeline, start_scheduler
    from app.core.pdf_renderer import close_pdf_renderer, init_pdf_renderer

    # 接管 stdout/logging → 指挥页右侧实时日志流
    console_stream.install()

    try:
        await init_pdf_renderer()
    except Exception as e:
        logging.getLogger("main").warning(f"⚠️ Playwright PDF renderer init skipped: {e}")

    try:
        # 初始化 LangGraph 与持久化存储
        await init_automation_pipeline()
        # 启动 Cron 调度器（实验端或调试环境若置 1 则跳过定时任务，避免多实例冲突）
        if os.getenv("DISABLE_AUTOMATION_SCHEDULER") == "1":
            logging.getLogger("main").info("⏸️ 检测到 DISABLE_AUTOMATION_SCHEDULER=1，跳过 APScheduler 自动化定时任务")
        else:
            start_scheduler()
    except Exception as e:
        logging.getLogger("main").exception(f"🚨 Automation Scheduler init failed: {e}")

    try:
        # 老 Agent（ChatAgent 回退链路）对话记忆持久化：不初始化则每次重启上下文清零
        from app.agent_router import init_agent_memory
        await init_agent_memory()
        logging.getLogger("main").info("✅ 老 Agent 对话记忆持久化已就绪")
    except Exception as e:
        logging.getLogger("main").warning(f"⚠️ 老 Agent 记忆持久化初始化失败（回退链路将退化为内存记忆）: {e}")

    try:
        # 主库统一建表引导（全新装配「用到就有」）：backend/data 被 gitignore，全新克隆无库无目录，
        # 这里幂等补齐全部表/索引/触发器后再放行后续初始化（2026-09-22 新机装配排查）。
        # 显式传 goal_service.DB_PATH：引导与 goal_service 用同一个 import 期解析的路径，
        # 杜绝「运行时再解析」与「import 期冻结」两套时机在环境变量后设时各建各库。
        from app.core.db_bootstrap import ensure_main_db_schema
        from app.services.goal_service import DB_PATH as _main_db_path
        ensure_main_db_schema(_main_db_path)
    except Exception as e:
        logging.getLogger("main").warning(f"⚠️ 主库建表引导失败（已有功能不受影响）: {e}")

    try:
        # 续抓页码 + 条件×平台进度台账（分母/分子）建表与存量迁移
        from app.session.scrape_sessions import init_scrape_sessions_table
        init_scrape_sessions_table()
    except Exception as e:
        logging.getLogger("main").warning(f"⚠️ scrape_sessions init skipped: {e}")

    try:
        # 主库 raw_jobs 关键字段二级索引幂等初始化（防御全表扫描与锁竞争）
        from app.jobs.service import ensure_raw_jobs_indices
        ensure_raw_jobs_indices()
    except Exception as e:
        logging.getLogger("main").warning(f"⚠️ raw_jobs 索引初始化失败: {e}")

    try:
        # 中断评估恢复：重启前被硬杀的聊天框评估按登记表续跑（超时/无断点则标红引导重评）
        from app.services.job_entry_chat import resume_inflight_evaluations
        asyncio.create_task(resume_inflight_evaluations())
    except Exception as e:
        logging.getLogger("main").warning(f"⚠️ 中断评估恢复任务启动失败: {e}")

    try:
        # ChatAgent（工具循环 harness）：未就绪时消息自动回退老 Agent 链路
        from app.services.chat_agent import agent as chat_agent
        await chat_agent.init_chat_agent()
        logging.getLogger("main").info("✅ ChatAgent（工具循环 harness）已就绪")
    except Exception as e:
        logging.getLogger("main").warning(f"⚠️ ChatAgent init skipped: {e}")

    try:
        # 飞书 WebSocket 长连接（消息事件主通道；webhook 仅作兜底）
        from app.core.feishu_ws import start_feishu_ws
        if start_feishu_ws(asyncio.get_running_loop()):
            logging.getLogger("main").info("✅ 飞书 WebSocket 长连接已启动")
        else:
            logging.getLogger("main").warning("⚠️ 飞书 WebSocket 长连接未启动（缺 FEISHU_APP_ID/SECRET）")
    except Exception as e:
        logging.getLogger("main").exception(f"🚨 飞书 WebSocket 长连接启动失败: {e}")

    try:
        # 飞书战报定时调度器（日/周/月报）：进程内存态，随应用启动从 job_goals 装载时间表；
        # 不挂载 lifespan 则仅在前端「保存时间表」后存活，重启即失联
        from app.services.report_scheduler import start_report_scheduler
        start_report_scheduler()
    except Exception as e:
        logging.getLogger("main").exception(f"⚠️ 战报调度器启动失败: {e}")

    yield
    try:
        from app.automation.scheduler import _scheduler
        if _scheduler and _scheduler.running:
            _scheduler.shutdown(wait=False)
    except Exception:
        pass
    try:
        from app.services.report_scheduler import stop_report_scheduler
        stop_report_scheduler()
    except Exception:
        pass
    try:
        await close_pdf_renderer()
    except Exception:
        pass


app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    generate_unique_id_function=custom_generate_unique_id,
    lifespan=lifespan,
)

if settings.all_cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.all_cors_origins,
        allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+)(:\d+)?$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# 🌟 性能提速：大 JSON（岗位列表等）gzip 压缩后再传输，体积约降至 1/10
app.add_middleware(GZipMiddleware, minimum_size=1024)

# ==========================================
# 🌟 路由挂载区 (必须在 app 实例化之后)
# ==========================================
app.include_router(api_router, prefix=settings.API_V1_STR)

# 挂载我们新开辟的 Jobs 工作台路由
app.include_router(jobs_router)

# 挂载策略大盘路由（内部已带 /api/strategy 前缀）
from app.strategy.router import router as strategy_router  # noqa: E402

app.include_router(strategy_router)

from app.copilot.router import router as copilot_router  # noqa: E402

app.include_router(copilot_router)

from app.questions.router import compat_router as questions_compat_router  # noqa: E402
from app.questions.router import router as questions_router  # noqa: E402

app.include_router(questions_router, prefix="/api/questions", tags=["Questions Bank"])
app.include_router(questions_compat_router, tags=["Questions Bank"])

from app.tasks.router import router as tasks_router  # noqa: E402

app.include_router(tasks_router, prefix="/api/tasks", tags=["Tasks"])

from app.settings.router import router as settings_router  # noqa: E402

app.include_router(settings_router, prefix="/api/settings", tags=["Settings"])

from app.interview.router import http_router as interview_http_router  # noqa: E402
from app.interview.router import router as interview_router  # noqa: E402

app.include_router(interview_router, prefix="/ws/interview", tags=["Interview WebSocket"])
app.include_router(interview_http_router, tags=["Interview HTTP"])

from app.api.routes import (  # noqa: E402
    auth,
    chatops,
    crawlers,
    frontend,
    processor,
    webhook,
)

app.include_router(chatops.router, prefix="/api/chatops", tags=["ChatOps"])
app.include_router(webhook.router, prefix="/api", tags=["feishu_webhook"])
app.include_router(frontend.router, prefix="/api", tags=["frontend_ui"])
app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(crawlers.router, prefix="/api/v1/crawlers", tags=["crawlers"])
app.include_router(processor.router, prefix="/api/v1/processor", tags=["processor"])

from app.automation.router import router as automation_router  # noqa: E402

app.include_router(automation_router, prefix="/api/automation", tags=["Automation Workflow"])

from app.pipeline.router import router as pipeline_router  # noqa: E402

app.include_router(pipeline_router)

from app.api.routes.analytics import router as analytics_router  # noqa: E402

app.include_router(analytics_router, prefix="/api/analytics", tags=["Analytics"])

# ── 数据分析看板 V2 + 求职目标 ──
from app.api.routes.analytics_dashboard import (  # noqa: E402
    router as analytics_v2_router,
)

app.include_router(analytics_v2_router, prefix="/api/v2/analytics", tags=["analytics-v2"])

from app.api.routes.goals import router as goals_router  # noqa: E402

app.include_router(goals_router, prefix="/api/v2/goals", tags=["goals"])

# ── 动态 Skill 技能管理路由 ──
from app.api.routes.skills import router as dynamic_skills_router  # noqa: E402

app.include_router(dynamic_skills_router, prefix="/api", tags=["动态技能管理"])


# ── 飞书战报：手动发送 + 预览 + 群聊列表 + 调度器刷新 ──
@app.post("/api/v2/report/send")
async def manual_send_report(report_type: str = "daily"):
    """手动触发发送报告。report_type: daily|weekly|monthly|final|test"""
    try:
        from app.services.report_feishu import (
            send_daily_report,
            send_final_report,
            send_monthly_report,
            send_test_report,
            send_weekly_report,
        )
        handlers = {
            "daily": send_daily_report, "weekly": send_weekly_report,
            "monthly": send_monthly_report, "final": send_final_report,
            "test": send_test_report,
        }
        handler = handlers.get(report_type)
        if not handler:
            return {"code": 1, "msg": f"未知报告类型: {report_type}", "data": None}
        success = await handler()
        return {"code": 0 if success else 1, "msg": "发送成功" if success else "发送失败（可能未配置飞书接收ID）", "data": {"report_type": report_type, "sent": success}}
    except Exception as e:
        return {"code": 1, "msg": f"发送失败: {str(e)}", "data": None}


@app.post("/api/v2/report/refresh-scheduler")
async def api_refresh_scheduler():
    """目标更新后重新加载调度配置。"""
    try:
        from app.services.report_scheduler import refresh_scheduler
        refresh_scheduler()
    except Exception:
        pass
    return {"code": 0, "msg": "调度器已刷新"}


@app.get("/api/v2/report/preview")
async def preview_report(report_type: str = "daily"):
    """预览报告内容和卡片 JSON。"""
    try:
        from app.services.report_feishu import (
            build_daily_card,
            build_monthly_card,
            build_weekly_card,
        )
        from app.services.report_service import (
            generate_daily_report,
            generate_monthly_report,
            generate_weekly_report,
        )
        handlers = {"daily": (generate_daily_report, build_daily_card), "weekly": (generate_weekly_report, build_weekly_card), "monthly": (generate_monthly_report, build_monthly_card)}
        gen, build = handlers.get(report_type, (None, None))
        if not gen:
            return {"code": 1, "msg": f"未知报告类型: {report_type}", "data": None}
        report_data = gen()
        card_json = build(report_data)
        return {"code": 0, "data": {"report": report_data, "card": card_json}}
    except Exception as e:
        return {"code": 1, "msg": f"预览失败: {str(e)}", "data": None}


@app.get("/api/chatops/tools")
async def list_chatops_tools():
    """飞书聊天指令话术速查数据源 — 以后端 CHAT_TOOLS/TOOL_META 为唯一真源，
    前端「指令话术」弹窗动态拉取本接口，避免前后端工具清单漂移。"""
    try:
        from app.services.chat_agent.tools import TOOL_META
        categories: dict[str, list] = {}
        order: list = []
        for name, meta in TOOL_META.items():
            cat = meta.get("category", "其他")
            if cat not in categories:
                categories[cat] = []
                order.append(cat)
            categories[cat].append({
                "tool": name,
                "desc": meta.get("desc", ""),
                "phrases": meta.get("phrases", []),
            })
        return {
            "code": 0,
            "data": {
                "total_tools": len(TOOL_META),
                "categories": [{"category": c, "commands": categories[c]} for c in order],
            },
        }
    except Exception as e:
        return {"code": 1, "msg": f"工具清单加载失败: {e}", "data": None}


@app.get("/api/v2/feishu/chats")
async def list_feishu_chats():
    """列出机器人已加入的飞书群聊。"""
    try:
        from app.core.feishu_client import feishu_client
        token = await feishu_client.get_tenant_access_token()
        if not token:
            return {"code": 1, "msg": "飞书认证失败", "data": None}
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.get("https://open.feishu.cn/open-apis/im/v1/chats", params={"page_size": 50}, headers={"Authorization": f"Bearer {token}"}, timeout=15)
            data = resp.json()
        if data.get("code") != 0:
            return {"code": 1, "msg": f"飞书 API 错误: {data.get('msg', '')}", "data": None}
        chats = [{"chat_id": item.get("chat_id", ""), "name": item.get("name", "未命名群")} for item in data.get("data", {}).get("items", [])]
        return {"code": 0, "data": {"chats": chats}}
    except Exception as e:
        return {"code": 1, "msg": f"获取群聊列表失败: {str(e)}", "data": None}

# 挂载简历编辑器路由
from app.api.resume_editor import router as resume_editor_router  # noqa: E402

app.include_router(resume_editor_router)
