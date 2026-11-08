import asyncio
import functools
import inspect
import logging
import os
import sys
import time
from contextlib import asynccontextmanager

# ===== 启动 import 打点（桌面打包态 shell.log 消费）=====
# 打包态用户没有终端：后端卡在 import 阶段时（2026-10-31 Windows 11 启动超时排查），
# 原日志只有 db_bootstrap/监控系统两条，无法定位卡在哪条 import 链。每条 import 前
# 打一行「+累计秒数」：最后一条命中的模块 = 正在加载（疑似卡点），其上一条 = 最后一个
# 已成功进入的模块。
_IMPORT_T0 = time.perf_counter()


def _import_mark(name: str) -> None:
    print(f"⏱️ [import] {name} +{time.perf_counter() - _IMPORT_T0:.1f}s", flush=True)


_import_mark("sentry_sdk/fastapi/starlette")
import sentry_sdk  # noqa: E402
from fastapi import FastAPI, HTTPException, Request  # noqa: E402
from fastapi.middleware.gzip import GZipMiddleware  # noqa: E402
from fastapi.routing import APIRoute  # noqa: E402
from starlette.middleware.cors import CORSMiddleware  # noqa: E402

# 🌟 强制注入 NO_PROXY，让 Python requests/urllib/httpx 自动绕过系统/VPN代理直连飞书及本地服务
_default_no_proxy = "localhost,127.0.0.1,open.feishu.cn,*.feishu.cn,feishu.cn"
os.environ["NO_PROXY"] = f"{_default_no_proxy},{os.environ.get('NO_PROXY', '')}".strip(",")
os.environ["no_proxy"] = os.environ["NO_PROXY"]

# lifespan 后台任务强引用集合（asyncio 官方建议：create_task 结果不持引用可能被 GC 中途回收）
_LIFESPAN_BG_TASKS: set = set()

# 🌟 启动最早期把 settings.json（配置页保存的值）注入 os.environ 与 pydantic settings 单例，
# 保证下方全部路由 import 时读到的 FEISHU_*/OPENAI_* 都是页面配置的最新值
_import_mark("common.config")
from common.config import (  # noqa: E402
    sync_settings_to_runtime as _sync_settings_to_runtime,
)

_sync_settings_to_runtime()

# 🌟 主库建表引导前置到业务 import 之前（2026-10-28 沙箱首启排查）：ai_evaluator 等业务
# 模块在 import 期就读主库（模块级/初始化期实例化引擎），全新机器此时库文件还不存在，
# sqlite3.connect 建出空库即报「no such table: job_strategies」吓到用户，而 lifespan 里的
# 引导要等全部 import 结束才跑。db_bootstrap 只依赖 logging/os/sqlite3，这里先建表再放行；
# lifespan 末尾的同款调用保留作幂等双保险，引导失败不拦启动（下游惰性建表兜底）。
_import_mark("app.core.db_bootstrap")
try:
    from app.core.db_bootstrap import ensure_main_db_schema  # noqa: E402

    _early_created = ensure_main_db_schema()
    if _early_created:
        print(f"✅ [db_bootstrap] 启动早期建表引导完成，新建 {len(_early_created)} 个对象（业务 import 之前）")
except Exception as _bootstrap_err:
    print(f"⚠️ 启动早期主库建表引导失败（不拦启动，lifespan 将重试）: {_bootstrap_err}")

_import_mark("ai_agents")
from ai_agents import ai_evaluator, ai_scorer  # noqa: E402

_import_mark("app.api.main")
from app.api.main import api_router  # noqa: E402

_import_mark("app.core.config")
from app.core.config import settings  # noqa: E402

_import_mark("app.jobs.router")
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

# 🌟 应用日志接回 stdout（2026-09-25 排查教训：uvicorn 默认日志配置下 root logger
# 无 handler，应用层 logger.info/warning 全部落入 lastResort（仅 WARNING+ 且无处可去），
# backend-out.log 只剩 uvicorn access log，故障时排查全靠盲测）。
# force=True 幂等重建 root handler；uvicorn.* 自带 handler 且 propagate=False，不会双写。
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
    stream=sys.stdout,
    force=True,
)

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
    "research_company_serper": "博查/Serper/Tavily 并发搜索公司商业背景与外部情报",
    "search_company_bocha": "博查 4路并发多维商业情报侦察引擎（国内直连）",
    "search_company_ai_news": "Serper 4路并发多维商业情报侦察引擎（境外网络）",

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
    import time as _time

    _t0 = _time.perf_counter()
    _last = _t0

    def _mark(step: str) -> None:
        # 启动链路计时打点（桌面打包态 shell.log 消费）：定位慢步骤（2026-10-06 Windows
        # 真机 0.1.1 实测 lifespan 内存在 ~70s 盲区，90s 超时被误杀）。单步增量 + 累计双口径。
        nonlocal _last
        now = _time.perf_counter()
        logging.getLogger("main").info(
            f"⏱️ [启动链路] {step} 单步 +{now - _last:.1f}s / 累计 {now - _t0:.1f}s"
        )
        _last = now

    from app.automation import console_stream
    from app.automation.scheduler import init_automation_pipeline, start_scheduler
    from app.core.pdf_renderer import close_pdf_renderer, init_pdf_renderer

    # 接管 stdout/logging → 指挥页右侧实时日志流
    console_stream.install()

    try:
        await init_pdf_renderer()
    except Exception as e:
        logging.getLogger("main").warning(f"⚠️ Playwright PDF renderer init skipped: {e}")
    _mark("PDF渲染器")

    try:
        # 初始化 LangGraph 与持久化存储
        await init_automation_pipeline()
        # 僵尸 running 清账（2026-10-23 终止失效工单）：上次进程被杀时 automation_logs
        # 的 finally 终态不会执行，残留 running 会让任务历史永久「运行中」
        from app.automation.db import reconcile_stale_running_logs
        _stale = reconcile_stale_running_logs()
        if _stale:
            logging.getLogger("main").warning(f"🧹 [automation_logs] 重启清账：{_stale} 条僵尸 running 已标记 interrupted_on_restart")
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
        # 这里幂等补齐全部表/索引/触发器后再放行后续初始化（2026-09-22 新机装配排查）
        from app.core.db_bootstrap import ensure_main_db_schema
        ensure_main_db_schema()
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
    _mark("ChatAgent")

    try:
        # 飞书 WebSocket 长连接（消息事件主通道；webhook 仅作兜底）。
        # 2026-10-07 移入后台任务：Windows 真机日志实证此步骤稳定耗时 64~69s
        # （lark_oapi 重依赖冷导入被杀软实时扫描放大），阻塞 lifespan 会吃掉壳的
        # 就绪等待窗口；WS 是入站消息通道，晚几秒启动无感。
        # R4 复审 P1：冷导入是同步阻塞调用，协程内直接执行会在被调度时冻住整个
        # 事件循环——必须 asyncio.to_thread 下放工作线程；loop 引用在主线程先取好
        async def _start_feishu_ws_bg(loop: asyncio.AbstractEventLoop) -> None:
            t0 = time.monotonic()

            def _import_and_start() -> bool:
                from app.core.feishu_ws import start_feishu_ws  # 冷导入成本计入本任务
                logging.getLogger("main").info(
                    f"⏱️ [飞书WS后台] 模块导入 {time.monotonic() - t0:.1f}s"
                )
                return start_feishu_ws(loop)

            try:
                if await asyncio.to_thread(_import_and_start):
                    logging.getLogger("main").info("✅ 飞书 WebSocket 长连接已启动")
                else:
                    logging.getLogger("main").warning("⚠️ 飞书 WebSocket 长连接未启动（缺 FEISHU_APP_ID/SECRET）")
                logging.getLogger("main").info(f"⏱️ [飞书WS后台] 总计 {time.monotonic() - t0:.1f}s")
            except Exception:
                logging.getLogger("main").exception("🚨 飞书 WebSocket 长连接启动失败")

        task = asyncio.create_task(_start_feishu_ws_bg(asyncio.get_running_loop()))
        _LIFESPAN_BG_TASKS.add(task)  # 持强引用防 GC（asyncio 官方建议模式）
        task.add_done_callback(_LIFESPAN_BG_TASKS.discard)
    except Exception as e:
        logging.getLogger("main").exception(f"🚨 飞书 WebSocket 后台任务派发失败: {e}")
    _mark("飞书WebSocket")

    try:
        # 飞书战报定时调度器（日/周/月报）：进程内存态，随应用启动从 job_goals 装载时间表；
        # 不挂载 lifespan 则仅在前端「保存时间表」后存活，重启即失联
        from app.services.report_scheduler import start_report_scheduler
        start_report_scheduler()
    except Exception as e:
        logging.getLogger("main").exception(f"⚠️ 战报调度器启动失败: {e}")
    _mark("战报调度器（lifespan 完毕）")

    yield
    # 2026-10-29 修复：此处原 import 的是 scheduler 模块上并不存在的 _scheduler 符号
    # （from ... import _scheduler 直接 ImportError 被 except 吞掉），自动化调度器
    # 从未在应用退出时被 shutdown——杀进程前它一直挂着 state=running + 旧事件循环，
    # 任何后续 add_job 都会打在死循环上。改为 shutdown 模块级单例本体。
    try:
        from app.automation import scheduler as _sch_mod
        if _sch_mod.scheduler and _sch_mod.scheduler.running:
            _sch_mod.scheduler.shutdown(wait=False)
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
_import_mark("app.strategy.router")
from app.strategy.router import router as strategy_router  # noqa: E402

app.include_router(strategy_router)

_import_mark("app.copilot.router")
from app.copilot.router import router as copilot_router  # noqa: E402

app.include_router(copilot_router)

_import_mark("app.questions.router")
from app.questions.router import compat_router as questions_compat_router  # noqa: E402
from app.questions.router import router as questions_router  # noqa: E402

app.include_router(questions_router, prefix="/api/questions", tags=["Questions Bank"])
app.include_router(questions_compat_router, tags=["Questions Bank"])

_import_mark("app.tasks.router")
from app.tasks.router import router as tasks_router  # noqa: E402

app.include_router(tasks_router, prefix="/api/tasks", tags=["Tasks"])

_import_mark("app.settings.router")
from app.settings.router import router as settings_router  # noqa: E402

app.include_router(settings_router, prefix="/api/settings", tags=["Settings"])

_import_mark("app.interview.router")
from app.interview.router import http_router as interview_http_router  # noqa: E402
from app.interview.router import router as interview_router  # noqa: E402

app.include_router(interview_router, prefix="/ws/interview", tags=["Interview WebSocket"])
app.include_router(interview_http_router, tags=["Interview HTTP"])

# 匿名功能计数拉取端点（0.4.7）：桌面壳定时读取本进程计数，随匿名心跳批量出站。
# 仅限 127.0.0.1 访问（局域网/远程一律 404）——计数不落盘不出机器，经壳并入心跳后才离开本机。
@app.get("/api/v1/usage/local-counters", include_in_schema=False)
async def usage_local_counters(request: Request):
    client = request.client
    if not client or client.host not in ("127.0.0.1", "::1", "localhost"):
        raise HTTPException(status_code=404, detail="Not Found")
    from app.core import usage_counters
    return {"counters": usage_counters.snapshot()}


# 分组 import 拆成逐模块：启动卡住时日志能精确到是哪个路由
# （webhook → agent_router → db_nl_controller 是启动链上最重的一条）
_import_mark("app.api.routes.auth")
from app.api.routes import auth  # noqa: E402

_import_mark("app.api.routes.chatops")
from app.api.routes import chatops  # noqa: E402

_import_mark("app.api.routes.crawlers")
from app.api.routes import crawlers  # noqa: E402

_import_mark("app.api.routes.frontend")
from app.api.routes import frontend  # noqa: E402

_import_mark("app.api.routes.processor")
from app.api.routes import processor  # noqa: E402

_import_mark("app.api.routes.webhook")
from app.api.routes import webhook  # noqa: E402

app.include_router(chatops.router, prefix="/api/chatops", tags=["ChatOps"])
app.include_router(webhook.router, prefix="/api", tags=["feishu_webhook"])
app.include_router(frontend.router, prefix="/api", tags=["frontend_ui"])
app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(crawlers.router, prefix="/api/v1/crawlers", tags=["crawlers"])
app.include_router(processor.router, prefix="/api/v1/processor", tags=["processor"])

_import_mark("app.automation.router")
from app.automation.router import router as automation_router  # noqa: E402

app.include_router(automation_router, prefix="/api/automation", tags=["Automation Workflow"])

_import_mark("app.pipeline.router")
from app.pipeline.router import router as pipeline_router  # noqa: E402

app.include_router(pipeline_router)

_import_mark("app.api.routes.analytics")
from app.api.routes.analytics import router as analytics_router  # noqa: E402

app.include_router(analytics_router, prefix="/api/analytics", tags=["Analytics"])

# ── 数据分析看板 V2 + 求职目标 ──
_import_mark("app.api.routes.analytics_dashboard")
from app.api.routes.analytics_dashboard import (  # noqa: E402
    router as analytics_v2_router,
)

app.include_router(analytics_v2_router, prefix="/api/v2/analytics", tags=["analytics-v2"])

_import_mark("app.api.routes.goals")
from app.api.routes.goals import router as goals_router  # noqa: E402

app.include_router(goals_router, prefix="/api/v2/goals", tags=["goals"])

# ── 动态 Skill 技能管理路由 ──
_import_mark("app.api.routes.skills")
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
_import_mark("app.api.resume_editor")
from app.api.resume_editor import router as resume_editor_router  # noqa: E402

app.include_router(resume_editor_router)
