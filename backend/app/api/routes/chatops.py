# backend/app/api/routers/chatops.py
import asyncio
import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException
from openai import OpenAI
from pydantic import BaseModel

from app.core.config import settings
from app.core.llm_tracker import make_tracked_client

# ==========================================
# 1. 基础配置与全局状态管理
# ==========================================
router = APIRouter()

# 初始化大模型客户端（惰性构建：Key/URL 变更时自动重建，配置页保存即生效）
_client = None
_client_sig = None


def get_client():
    global _client, _client_sig
    sig = (settings.OPENAI_API_KEY, settings.OPENAI_BASE_URL)
    if _client is None or _client_sig != sig:
        _client = make_tracked_client(OpenAI(api_key=sig[0], base_url=sig[1]), caller="chatops")
        _client_sig = sig
    return _client

# 动态定位爬虫目录的基础路径
BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent

PLATFORM_CONFIG = {
    "boss":   {"per_page": 15, "script_name": "boss_collector.py",   "dir_name": "boss_scraper"},
    "51job":  {"per_page": 20, "script_name": "51job_collector.py",  "dir_name": "51job_scraper"},
    "liepin": {"per_page": 30, "script_name": "liepin_crawler.py",   "dir_name": "liepin_scraper"},
    "zhaopin":{"per_page": 30, "script_name": "zhilian_collector.py",   "dir_name": "zhilian_scraper"},
}

# 任务状态队列（ChatOps 专属）
active_processes: dict[str, asyncio.subprocess.Process] = {}
cancel_events: dict[str, asyncio.Event] = {}
task_queues: dict[str, asyncio.Queue] = {}
task_status: dict[str, dict[str, Any]] = {}


# ==========================================
# 2. 数据模型 (Pydantic Models)
# ==========================================
class ChatCommandRequest(BaseModel):
    command: str
    task_id: str | None = None
    history: list[dict[str, str]] | None = None


# ==========================================
# 3. 核心业务函数 (意图解析与调度器)
# ==========================================
async def parse_chat_intent(command: str, history: list = None) -> dict:
    if not settings.OPENAI_API_KEY:
        raise HTTPException(status_code=500, detail="AI 服务未配置，无法解析指令")

    system_prompt = """你是一个爬虫任务编排与数据库分析助手。请结合【历史对话上下文】和【当前指令】提取参数。
必须严格输出纯净 JSON，绝不能包含任何 Markdown 代码块标记（如 ```json 或 ```）。

【action 枚举说明】：
   - "scrape": 抓取、爬取岗位数据（用户说"抓一下/爬一下/搞一批 XX 岗位"等）
   - "evaluate": 触发后台数据清洗、打分、过滤任务（用户说"清洗数据"、"打分"、"过滤"时）
   - "clean": 执行 Python 结构化硬清洗
   - "push": 将清洗通过的岗位同步到飞书（无特定筛选条件时用此 action）
   - "query_db": 查询【本地 SQLite 数据库】的原始数据。返回：{"action": "query_db", "user_query": "原始提问"}
   - "query_feishu": 查询【飞书多维表格】上的实时数据。返回：{"action": "query_feishu", "user_query": "原始提问"}
   - "record_interview": 记录并粉碎面经真题（用户复盘某公司面试过程时）
   - "stop_scrape": 停止当前抓取任务。返回：{"action": "stop_scrape"}
   - "push_to_feishu": 用户明确要"推送岗位"/"同步数据"并携带筛选条件（日期/分数/数量等）时触发。必须同时提取 filters 字典。
   - "ai_evaluate": 🎯 触发所有的初步评估、深度评估、简历改写、打招呼语生成等任务。返回：{"action": "ai_evaluate", "user_query": "用户原始的完整指令"}
   - "clarify": 用户意图模糊或代词无指代时触发。返回：{"action": "clarify", "message": "追问话术（简洁友好）"}

【字段提取规则】：
1. "platforms": 数组（多平台时用，如 ["boss", "liepin", "51job"]）
2. "specific_page": 整数，明确指定"第X页"时提取
3. "pages": 整数，"抓X页"时提取
4. "target_count": 整数，未提默认 100
5. "keyword" / "city" / "salary": 字符串，salary 必须大写 K 结尾，city 默认"广州"
6. "start_page": 整数，从第X页开始，默认 1
7. "platform": 当 action="scrape" 且指定单一平台时必填
11. 当 action="scrape" 时额外提取："salary" (默认"不限"), "start_page" (默认1), "target_jobs" (默认15)
12. 当 action 为 "push_to_feishu" 时，必须提取 "filters" 字典 (包含 crawl_date, min_score, limit，未提及则省略键)。

【🚨 过滤参数继承铁律（最高优先级，违反必错）】：
- 继承上文提及的全部过滤条件。
- 若无分数门槛，filters.min_score 填 0（非 null）。
- crawl_date 需根据描述转为 YYYY-MM-DD。
"""
    messages = [{"role": "system", "content": system_prompt}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": f"用户指令：{command}"})

    try:
        response = await asyncio.to_thread(
            get_client().chat.completions.create,
            model=settings.OPENAI_MODEL,
            messages=messages,
            temperature=0.1
        )
        content = (response.choices[0].message.content or "").strip()

        # 移除可能存在的 Markdown 标记
        if content.startswith("```json"):
            content = content[7:]
        elif content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]

        return json.loads(content.strip())
    except Exception as e:
        print(f"⚠️ LLM 意图解析失败，使用默认降级参数: {e}")
        return {"action": "scrape", "platforms": ["boss"], "target_count": 100}


async def run_sequential_chatops_scheduler(task_id: str, platforms: list, target_count: int, target_pages: int, specific_page: int, keyword: str, city: str, salary: str, queue: asyncio.Queue, start_page: int = 1):
    cancel_event = asyncio.Event()
    cancel_events[task_id] = cancel_event

    try:
        mode_msg = f"第 {specific_page} 页" if specific_page is not None and specific_page > 0 else (f"{target_pages} 页" if target_pages else f"各 {target_count} 条")
        await queue.put(f'data: {{"type": "info", "message": "🚦 调度启动：识别到 {len(platforms)} 个平台，执行模式：{mode_msg}数据。"}}\n\n')

        for plat in platforms:
            platform_dir_name = PLATFORM_CONFIG.get(plat, {}).get('dir_name', 'boss_scraper')
            spider_dir = BASE_DIR / platform_dir_name

            if plat == "boss":
                await queue.put('data: {"type": "info", "message": "🔐 正在自动提取 Edge 浏览器 Cookie 刷新登录态..."}\n\n')
                await queue.put('data: {"type": "progress", "message": "  > boss login --cookie-source edge"}\n\n')

                login_process = await asyncio.create_subprocess_exec(
                    "boss", "login", "--cookie-source", "edge",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(spider_dir)
                )

                async def read_login_stream(stream, is_error=False):
                    while True:
                        line = await stream.readline()
                        if not line:
                            break
                        text = line.decode('utf-8', errors='replace').strip()
                        if text:
                            safe_text = text.replace('"', '\\"').replace('\n', ' ')
                            msg_type = "warning" if is_error else "info"
                            await queue.put(f'data: {{"type": "{msg_type}", "message": "  [Cookie刷新] {safe_text}"}}\n\n')

                await asyncio.gather(
                    read_login_stream(login_process.stdout),
                    read_login_stream(login_process.stderr, True)
                )
                await login_process.wait()
                await queue.put('data: {"type": "success", "message": "✅ 登录态刷新完毕，准备拉起采集矩阵！"}\n\n')

            if specific_page is not None and specific_page > 0:
                page = specific_page
                await queue.put(f'data: {{"type": "info", "message": "📍 精准模式：锁定抓取 {plat} 的第 {specific_page} 页"}}\n\n')
                if cancel_event.is_set():
                    raise Exception("任务已被用户手动终止")

                await queue.put(f'data: {{"type": "progress", "message": "🚀 正在拉起 {plat} 爬虫，执行指令..."}}\n\n')

                script_name = PLATFORM_CONFIG.get(plat, {}).get('script_name', 'boss_collector.py')
                display_cmd = f"python {script_name} -p {page}"
                await queue.put(f'data: {{"type": "progress", "message": "  > {display_cmd}"}}\n\n')

                script_path = str(spider_dir / script_name)
                cmd = ["python", "-u", script_path, "--platform", plat, "-p", str(page)]

                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(spider_dir)
                )
                active_processes[task_id] = process

                async def read_stream_single(stream, msg_type="info", _plat=plat, _page=page):
                    while True:
                        line = await stream.readline()
                        if not line:
                            break
                        text = line.decode('utf-8', errors='replace').strip()
                        if text:
                            safe_text = text.replace('"', '\\"').replace('\n', ' ')
                            await queue.put(f'data: {{"type": "{msg_type}", "message": "  [{_plat}-P{_page}] {safe_text}"}}\n\n')
                            await asyncio.sleep(0.01)

                await asyncio.gather(read_stream_single(process.stdout, "info"), read_stream_single(process.stderr, "warning"))
                await process.wait()

            else:
                tracker = {"inserted": 0}
                page = start_page
                max_pages = start_page + 29

                final_keyword = keyword
                final_city = city
                final_salary = salary

                display_city = final_city or "全国"
                await queue.put(f'data: {{"type": "info", "message": "🎯 收到临时指令，使用条件：[{display_city}] [{final_keyword}]"}}\\n\\n')

                await queue.put(f'data: {{"type": "info", "message": "🎯 动态模式：目标入库 {target_count} 条，从第 1 页开始，最多抓 {max_pages} 页"}}\n\n')

                while tracker["inserted"] < target_count and page <= max_pages:
                    if cancel_event.is_set():
                        raise Exception("任务已被用户手动终止")

                    await queue.put(f'data: {{"type": "progress", "message": "🚀 正在拉起 {plat} 爬虫，执行指令..."}}\n\n')

                    script_name = PLATFORM_CONFIG.get(plat, {}).get('script_name', 'boss_collector.py')
                    display_cmd = f"python {script_name} -p {page}"
                    await queue.put(f'data: {{"type": "progress", "message": "  > {display_cmd}"}}\n\n')

                    script_path = str(spider_dir / script_name)
                    cmd = ["python", "-u", script_path, "--platform", plat, "-p", str(page)]
                    if final_keyword:
                        cmd.extend(["--keyword", final_keyword])
                    if final_city:
                        cmd.extend(["--city", final_city])
                    if final_salary:
                        cmd.extend(["--salary", final_salary])

                    process = await asyncio.create_subprocess_exec(
                        *cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        cwd=str(spider_dir)
                    )
                    active_processes[task_id] = process

                    async def read_stream(stream, msg_type="info", _page=page, _tracker=tracker, _plat=plat):
                        while True:
                            line = await stream.readline()
                            if not line:
                                break
                            text = line.decode('utf-8', errors='replace').strip()
                            if text:
                                safe_text = text.replace('"', '\\"').replace('\n', ' ')
                                await queue.put(f'data: {{"type": "{msg_type}", "message": "  [{_plat}-P{_page}] {safe_text}"}}\n\n')
                                await asyncio.sleep(0.01)
                                match = re.search(r"新增入库\s*(\d+)\s*个", text)
                                if match:
                                    _tracker["inserted"] += int(match.group(1))

                    await asyncio.gather(read_stream(process.stdout, "info"), read_stream(process.stderr, "warning"))
                    await process.wait()

                    page += 1

                    if tracker["inserted"] < target_count and not cancel_event.is_set() and page <= max_pages:
                        inserted_so_far = tracker["inserted"]
                        await queue.put(f'data: {{"type": "info", "message": "📈 目标 {target_count} 个，当前已入库 {inserted_so_far} 个，自动开启第 {page} 页抓取..."}}\n\n')
                        await queue.put('data: {"type": "warning", "message": "🛡️ 防风控保护：休眠 10 分钟后继续..."}\n\n')
                        wait_seconds = 600
                        elapsed = 0
                        while elapsed < wait_seconds:
                            if cancel_event.is_set():
                                raise Exception("任务已在休眠期间手动终止")
                            remaining = wait_seconds - elapsed
                            if remaining % 60 == 0 and remaining > 0:
                                minutes = remaining // 60
                                if minutes > 1:
                                    await queue.put(f'data: {{"type": "info", "message": "⏱️ 休眠倒计时：还剩 {minutes} 分钟..."}}\n\n')
                                elif minutes == 1:
                                    await queue.put('data: {"type": "info", "message": "⏱️ 休眠倒计时：还剩 1 分钟，准备唤醒..."}\n\n')
                            if elapsed % 10 == 0:
                                await queue.put('data: {"type": "heartbeat", "message": ""}\n\n')
                            await asyncio.sleep(1)
                            elapsed += 1


        await queue.put('data: {"type": "success", "message": "✨ 所有抓取任务已安全执行完毕！"}\n\n')

    except Exception as e:
        await queue.put(f'data: {{"type": "error", "message": "🛑 {str(e)}"}}\n\n')
    finally:
        await queue.put('data: {"type": "end"}\n\n')
        if task_id in active_processes:
            del active_processes[task_id]
        if task_id in cancel_events:
            del cancel_events[task_id]


# ==========================================
# 3.5 待迁移后台任务的真实实现（清洗/推送飞书/查库/评估）
# ==========================================
async def run_chatops_cleaner(task_id: str, queue: asyncio.Queue):
    """数据清洗：复用 job_processor.step1_rule_filter 的 Tier1 硬规则 + Tier2 AI 初筛流水线。"""
    try:
        await queue.put('data: {"type": "info", "message": "🧹 开始执行数据清洗（硬规则过滤 + AI 初筛）..."}\n\n')
        from job_processor.step1_rule_filter import _async_run_pipeline
        await _async_run_pipeline(sse_task_id=task_id)
        await queue.put('data: {"type": "success", "message": "✅ 数据清洗完毕！淘汰与通过明细已回写数据库。"}\n\n')
    except Exception as e:
        await queue.put(f'data: {{"type": "error", "message": "🛑 数据清洗失败: {str(e)}"}}\n\n')
    finally:
        await queue.put('data: {"type": "end"}\n\n')


async def run_chatops_pusher(task_id: str, queue: asyncio.Queue):
    """推送飞书：复用 job_processor.step2_sync_feishu 的同步引擎（带防重复查重）。"""
    try:
        await queue.put('data: {"type": "info", "message": "📤 开始将清洗通过的岗位同步到飞书多维表格..."}\n\n')
        from job_processor.step2_sync_feishu import sync_sqlite_to_feishu
        db_path = str(BASE_DIR / "data" / "job_hunter.db")
        # 同步阻塞函数丢入线程池，避免卡死事件循环
        await asyncio.to_thread(sync_sqlite_to_feishu, db_path, "raw_jobs", task_id)
        await queue.put('data: {"type": "success", "message": "✅ 飞书同步完毕！新岗位已推送到多维表格（自动查重）。"}\n\n')
    except Exception as e:
        await queue.put(f'data: {{"type": "error", "message": "🛑 飞书同步失败: {str(e)}"}}\n\n')
    finally:
        await queue.put('data: {"type": "end"}\n\n')


async def run_chatops_db_querier(task_id: str, sql: str, queue: asyncio.Queue):  # noqa: ARG001  # add_task(task_id=...) 关键字传参
    """查询本地数据库：在 raw_jobs 表上执行只读查询并返回预览。"""
    import sqlite3
    try:
        db_path = str(BASE_DIR / "data" / "job_hunter.db")
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # 只允许 SELECT，防止误操作改库
        query = (sql or "").strip()
        if not query or not query.lower().startswith("select"):
            query = "SELECT job_title, company_name, city, salary, process_status FROM raw_jobs ORDER BY rowid DESC LIMIT 10"
            await queue.put('data: {"type": "warning", "message": "⚠️ 未提供合法 SQL，已使用默认查询（最近 10 条）。"}\n\n')

        rows = cursor.execute(query).fetchall()
        preview = [dict(r) for r in rows[:10]]
        for item in preview:
            item.pop("jd_text", None)
        conn.close()

        result_text = json.dumps(preview, ensure_ascii=False)
        safe_text = result_text.replace('"', '\\"')
        await queue.put(f'data: {{"type": "success", "message": "🔍 查询成功，共 {len(rows)} 条，预览前 {len(preview)} 条: {safe_text}"}}\n\n')
    except Exception as e:
        await queue.put(f'data: {{"type": "error", "message": "🛑 数据库查询失败: {str(e)}"}}\n\n')
    finally:
        await queue.put('data: {"type": "end"}\n\n')


async def run_chatops_evaluator(task_id: str, target_count: int, platforms: list, queue: asyncio.Queue):  # noqa: ARG001  # add_task(platforms=...) 关键字传参
    """AI 评估：从飞书拉取「新线索」待评估岗位，复用批量 AI 任务引擎执行初步评估。"""
    try:
        await queue.put('data: {"type": "info", "message": "🧠 正在从飞书拉取待评估岗位（新线索）..."}\n\n')
        from app.services.feishu_service import get_new_leads_from_feishu
        # 同步阻塞的飞书查询丢入线程池
        leads = await asyncio.to_thread(get_new_leads_from_feishu)
        if not leads:
            await queue.put('data: {"type": "warning", "message": "📭 当前没有待评估的新线索岗位，任务结束。"}\n\n')
            return

        # 截取目标数量，并构造 run_batch_ai_task 需要的带平台前缀的 job_id
        leads = leads[:target_count] if target_count else leads
        job_ids = [f"{lead.get('platform', '')}-{lead.get('record_id', '')}" for lead in leads]
        await queue.put(f'data: {{"type": "info", "message": "📥 捞到 {len(job_ids)} 条待评估岗位，启动 AI 批量评估..."}}\n\n')

        from app.tasks.service import run_batch_ai_task
        from app.tasks.service import task_status as batch_task_status
        # run_batch_ai_task 内部会读写 task_status[task_id]，需先在其模块的 status 字典里注册
        batch_task_status[task_id] = {"status": "pending", "task_type": "evaluate", "total": len(job_ids)}
        await run_batch_ai_task(task_id, "evaluate", job_ids, queue)
        await queue.put('data: {"type": "success", "message": "✅ AI 评估任务执行完毕，评分与状态已回写飞书。"}\n\n')
    except Exception as e:
        await queue.put(f'data: {{"type": "error", "message": "🛑 AI 评估失败: {str(e)}"}}\n\n')
    finally:
        await queue.put('data: {"type": "end"}\n\n')


# ==========================================
# 4. API 路由入口
# ==========================================
@router.post("/command")
async def handle_chat_command(payload: ChatCommandRequest, background_tasks: BackgroundTasks) -> dict[str, Any]:
    command_text = payload.command.strip()

    if command_text in ["终止", "停止", "结束", "stop", "退出"]:
        for t_id, event in cancel_events.items():
            event.set()
            if t_id in active_processes:
                try:
                    active_processes[t_id].terminate()
                except Exception:
                    pass
        return {"status": "success", "message": "已收到指令，正在强制停止所有后台进程..."}

    intent = await parse_chat_intent(command_text, payload.history)
    action = intent.get("action", "scrape")

    # 🌟 修复：LLM 解析出 stop_scrape 意图时（如"终止当前抓取任务"），同样执行停止逻辑，
    # 避免掉进 else 分支误启动爬虫
    if action == "stop_scrape":
        for t_id, event in cancel_events.items():
            event.set()
            if t_id in active_processes:
                try:
                    active_processes[t_id].terminate()
                except Exception:
                    pass
        return {"status": "success", "message": "已收到指令，正在强制停止所有后台进程..."}

    # 🌟 关键修复：LLM 对单平台指令返回 "platform"（单数），多平台返回 "platforms"（复数），
    # 这里统一归一化为 platforms 列表，避免单平台指令被错误地 fallback 到 boss
    platforms = intent.get("platforms")
    if not platforms:
        single_platform = intent.get("platform")
        platforms = [single_platform] if single_platform else ["boss"]
    # 归一化平台名（zhaopin/智联 统一为调度器可识别的 key）
    platform_alias = {"智联": "zhaopin", "zhilian": "zhaopin", "前程无忧": "51job", "猎聘": "liepin"}
    platforms = [platform_alias.get(p, p) for p in platforms]

    target_count = intent.get("target_count") or intent.get("target_jobs") or 100
    target_pages = intent.get("pages", 0)
    specific_page = intent.get("specific_page", 0)
    keyword = intent.get("keyword") or ""
    city = intent.get("city") or ""
    salary = intent.get("salary") or ""
    start_page = int(intent.get("start_page") or 1)

    task_id = payload.task_id if payload.task_id else f"chatops_{uuid.uuid4().hex[:8]}"
    task_queues[task_id] = asyncio.Queue()

    task_type = "chat_cleaner" if action == "clean" else ("chat_evaluator" if action == "evaluate" else "chat_scraper")
    task_status[task_id] = {
        "status": "pending",
        "task_type": task_type,
        "created_at": datetime.now().isoformat()
    }

    if action == "clean":
        background_tasks.add_task(run_chatops_cleaner, task_id=task_id, queue=task_queues[task_id])
    elif action in ("push", "push_to_feishu"):
        # 推送飞书：无论是否带筛选条件，都复用同步引擎（内部自带防重复查重）
        background_tasks.add_task(run_chatops_pusher, task_id=task_id, queue=task_queues[task_id])
    elif action in ("query", "query_db"):
        # LLM 返回的是 user_query（原始提问）而非结构化 sql，这里作为提示传入
        background_tasks.add_task(run_chatops_db_querier, task_id=task_id, sql=intent.get("sql", ""), queue=task_queues[task_id])
    elif action in ("evaluate", "ai_evaluate"):
        background_tasks.add_task(run_chatops_evaluator, task_id=task_id, target_count=target_count, platforms=platforms, queue=task_queues[task_id])
    elif action in ("query_feishu", "record_interview"):
        # 🌟 这两个 action 的后台任务尚未迁移实现，直接返回提示，
        # 避免掉进 else 分支误启动爬虫
        return {
            "status": "not_implemented",
            "message": f"指令已识别为 [{action}]，但该功能的后台任务尚在迁移中，暂时无法执行。",
            "task_id": task_id
        }
    elif action == "clarify":
        # 意图模糊，返回 LLM 生成的追问话术
        return {
            "status": "clarify",
            "message": intent.get("message", "抱歉，我没有理解你的指令，可以再说得具体一点吗？"),
            "task_id": task_id
        }
    else:
        background_tasks.add_task(
            run_sequential_chatops_scheduler,
            task_id=task_id,
            platforms=platforms,
            target_count=target_count,
            target_pages=target_pages,
            specific_page=specific_page,
            keyword=keyword,
            city=city,
            salary=salary,
            start_page=start_page,
            queue=task_queues[task_id]
        )

    return {
        "status": "started",
        "task_id": task_id,
        "planned_platforms": platforms,
        "target_per_platform": target_count
    }
