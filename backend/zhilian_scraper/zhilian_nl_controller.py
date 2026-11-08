#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import signal
import os
import sys
import shutil
import json
import time
import random
import subprocess
import asyncio
import re
from openai import OpenAI

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# 🌟 Windows 防闪窗：子进程统一走防闪窗包装（参照 engine_guard，收口见 backend/subprocess_utils.py）
from subprocess_utils import popen_hidden
from engine_guard import PORT_LOCK_BUSY_EXIT_CODE

# 薪资筛选失败中止的退出码（与 zhilian_collector.SALARY_FILTER_ABORT_EXIT_CODE 保持一致：
# 不直接 import，避免控制器模块加载拖入 DrissionPage 重依赖）
ZHILIAN_SALARY_ABORT_EXIT_CODE = 2

# 🌟 全局急刹车开关：被飞书 stop_scrape 指令拉高后，底层循环会检测并优雅退出
GLOBAL_STOP_FLAG = False

def set_stop_flag(value: bool):
    """外部（例如 FastAPI 路由）调用此函数拉起 / 释放急刹车。"""
    global GLOBAL_STOP_FLAG
    GLOBAL_STOP_FLAG = bool(value)
    print(f"🌟 [set_stop_flag] GLOBAL_STOP_FLAG → {GLOBAL_STOP_FLAG}")

# 🌟 活动心跳钩子：由异步入口安装；在 stdout 无新行的长静默期间，
# 至多每 30 秒发一次 SSE 心跳，防止全链路转发协程把「静默」误判为「任务已结束」
# 而提前返回、并发二次派发（超抓事故根因修复）。
_HEARTBEAT_HOOK = None

def set_heartbeat_hook(hook):
    global _HEARTBEAT_HOOK
    _HEARTBEAT_HOOK = hook

def _ping_heartbeat():
    if _HEARTBEAT_HOOK:
        try:
            _HEARTBEAT_HOOK()
        except Exception:
            pass

from app.core.config import settings
from app.automation.dup_skip_parse import count_duplicate_skip
# 🌟 统一 Token 埋点
from app.core.llm_tracker import make_tracked_client
OPENAI_API_KEY = settings.OPENAI_API_KEY
OPENAI_BASE_URL = settings.OPENAI_BASE_URL
OPENAI_MODEL = settings.OPENAI_MODEL

client = make_tracked_client(OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL), model_default=OPENAI_MODEL, caller="zhilian_nl_controller")

INTENT_SYSTEM_PROMPT = """你是一个 智联招聘 爬虫调度助手。
请将用户的指令解析成以下严格的 JSON 格式，不要输出任何其他说明文字：
{
  "keyword": "搜索关键词",
  "city": "城市名称 (如广州/深圳等，未提及则留空)",
  "salary": "薪资描述 (如15-20K，未提及则填'不限')",
  "start_page": 起始页码 (整数，默认1),
  "target_jobs": 期望成功入库的岗位数量 (整数，如果用户说抓X页，按一页15个估算为 X*15；如果直接要求抓X个，则填X)
}"""

def parse_intent(user_input):
    """使用 LLM 解析自然语言指令"""
    print(f">> 正在解析指令: {user_input}")
    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": INTENT_SYSTEM_PROMPT},
                {"role": "user", "content": user_input}
            ],
            temperature=0,
        )
        raw = response.choices[0].message.content.strip()
        clean_json = raw.replace("```json", "").replace("```", "").strip()
        return json.loads(clean_json)
    except Exception as e:
        print(f"!! 指令解析出错: {e}")
        return None

def _build_crawler_cmd(crawler_path, keyword, city, start_page, target_jobs, salary):
    cmd = [
        sys.executable, "-u", crawler_path,
        "-p", str(start_page),
        "--keyword", keyword,
        "--target", str(target_jobs)
    ]
    if city:
        cmd.extend(["--city", city])
    if salary and salary != "不限":
        cmd.extend(["--salary", salary])
    return cmd

def _parse_page_marker(line: str) -> int | None:
    """从智联采集器协议行提取批次/页码。

    只匹配采集器约定的带前缀行，避免无关 stdout（例如普通日志里的“第 N 页”）
    静默污染续抓起点。
    """
    m = re.search(r"\[(?:瀑布流滚动|极速跃迁|新鲜数据)\].*?第\s*(\d+)\s*批", line)
    if not m:
        m = re.search(r"(?:直达跳转|页面疑似卡死).*?第\s*(\d+)\s*页", line)
    if not m:
        return None
    try:
        return int(m.group(1))
    except (TypeError, ValueError):
        return None


def _handle_process_stdout(process, sse_task_id, loop, target_jobs, start_page, skip_state=None):
    """逐行解析终端输出流，实时推送进度；顺带捕获搜索总数、到底信号与最后批次号。"""
    global GLOBAL_STOP_FLAG
    real_time_inserted = 0
    search_total = 0
    hit_bottom = False
    last_page = start_page
    for line in process.stdout:
        if GLOBAL_STOP_FLAG:
            print("\n🛑 [急刹车触发] 正在强制终止子进程...")
            process.terminate()
            break
        print(line, end="")
        _ping_heartbeat()  # 🌟 stdout 有活动即报平安（钩子内部 30s 节流）

        # 重复岗位跳过计数（前置查重拦截行 + 极速跃迁整批行，实况送前端横幅）
        dup_n = count_duplicate_skip(line)
        if dup_n and skip_state is not None:
            skip_state["n"] += dup_n
            if sse_task_id and loop:
                from app.tasks.state import task_queues
                if sse_task_id in task_queues:
                    msg = f'data: {{"type": "scrape_progress", "skipped": {skip_state["n"]}}}\n\n'
                    asyncio.run_coroutine_threadsafe(task_queues[sse_task_id].put(msg), loop)

        # 捕获搜索总数（分母）协议行
        if "搜索总数" in line and "个" in line:
            try:
                search_total = int(line.split("搜索总数", 1)[1].split("个", 1)[0].strip())
            except Exception:
                pass

        if "[入库成功]" in line:
            real_time_inserted += 1
            if sse_task_id and loop:
                from app.tasks.state import task_queues
                if sse_task_id in task_queues:
                    msg = f'data: {{"type": "progress", "total_inserted": {real_time_inserted}, "target_jobs": {target_jobs}, "current_page": {start_page}}}\n\n'
                    asyncio.run_coroutine_threadsafe(task_queues[sse_task_id].put(msg), loop)

        # 瀑布流批次号（只认采集器协议行）→ 续抓真实末页
        page_marker = _parse_page_marker(line)
        if page_marker is not None:
            last_page = max(last_page, page_marker)

        # 到底信号：分页组件最后一页 / 连续多批无新增的抓尽收工
        if "到达最后一页/底部" in line or "抓尽收工" in line:
            hit_bottom = True

    process.wait()
    if process.returncode == PORT_LOCK_BUSY_EXIT_CODE:
        # 跨进程端口锁被另一个 JobHunter 实例持有：协调性跳过，不是环境故障
        print("\n⏳ [调度器] 智联浏览器端口正被占用（本进程或另一个 JobHunter 实例），本轮抓取跳过（非环境故障）")
    elif process.returncode != 0:
        print(f"\n🛑 [调度器异常熔断] 底层引擎遭遇异常退出（错误码: {process.returncode}）！")
    return real_time_inserted, search_total, hit_bottom, last_page

def run_task(keyword, city, start_page, target_jobs, salary, sse_task_id=None, loop=None,
             ledger_keyword=None, ledger_city=None, ledger_salary=None, result_meta=None):
    if int(target_jobs or 0) <= 0:
        # 0/负目标不是一次抓取轮次：不回报台账，避免连续空跑被误判抓尽
        return 0
    crawler_path = os.path.join(CURRENT_DIR, "zhilian_collector.py")

    global GLOBAL_STOP_FLAG
    skip_state = {"n": 0}  # 本轮重复跳过累计（可变盒跨批累加）
    
    if GLOBAL_STOP_FLAG:
        print("🛑 [急刹车触发] 收到全局中断信号，取消执行！")
        if result_meta is not None:
            result_meta.update({
                "inserted": 0, "search_total": 0, "hit_bottom": False,
                "last_page": int(start_page or 1), "success": False,
            })
        return 0

    print(f"\n{'='*50}")
    print(f"🎯 正在执行瀑布流抓取，目标: {target_jobs} 个 | 初始页: 第 {start_page} 页")
    print(f"📌 条件: 关键词={keyword} | 城市={city} | 薪资={salary}")
    
    cmd = _build_crawler_cmd(crawler_path, keyword, city, start_page, target_jobs, salary)
        
    my_env = os.environ.copy()
    my_env["PYTHONPATH"] = PROJECT_ROOT
    my_env["PYTHONIOENCODING"] = "utf-8"

    process = popen_hidden(
        cmd, cwd=CURRENT_DIR,
        env=my_env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, 
        text=True, encoding='utf-8', errors='replace'
    )
    
    try: 
        real_time_inserted, search_total, hit_bottom, last_page = _handle_process_stdout(
            process, sse_task_id, loop, target_jobs, start_page, skip_state
        )
    except KeyboardInterrupt:
        print("\n🛑 [紧急中断] 收到 Ctrl+C，正在暴力击杀底层的抓取子进程...")
        process.terminate()
        process.wait()
        raise

    print(f"\n>> 本轮动态抓取指令已全部执行完毕。最终入库总数：{real_time_inserted}")

    # 回写「条件×平台」进度台账：使用原始条件（不是平台映射后的薪资/关键词）
    success = process.returncode == 0 and not GLOBAL_STOP_FLAG
    # 失败原因（供指挥中心弹窗/飞书通知下发）：手动急刹不产生失败通知
    fail_reason = None
    if not success and not GLOBAL_STOP_FLAG:
        if process.returncode == ZHILIAN_SALARY_ABORT_EXIT_CODE:
            fail_reason = "薪资筛选失败中止（下拉选项未渲染，宁缺毋滥防越档岗位灌库）"
        elif process.returncode == PORT_LOCK_BUSY_EXIT_CODE:
            fail_reason = "浏览器端口被占用（另一个 JobHunter 实例在使用），本轮跳过"
        else:
            fail_reason = f"底层引擎异常退出（错误码 {process.returncode}）"
    try:
        from app.session.scrape_sessions import report_condition_round
        report_condition_round(
            ledger_keyword if ledger_keyword is not None else keyword,
            ledger_city if ledger_city is not None else (city or ""),
            ledger_salary if ledger_salary is not None else salary,
            "zhilian",
            real_time_inserted,
            search_total or None,
            hit_bottom=hit_bottom,
            success=success,
        )
    except Exception as e:
        print(f"⚠️ 智联条件台账回写失败: {e}")

    if result_meta is not None:
        result_meta.update({
            "inserted": int(real_time_inserted or 0),
            "search_total": int(search_total or 0),
            "hit_bottom": bool(hit_bottom),
            "last_page": 0 if hit_bottom else int(last_page or 0),
            "success": bool(success),
            "fail_reason": fail_reason,
        })

    return real_time_inserted

def main():
    print("------------------------------------------")
    print("智联招聘 动态目标调度大管家 已启动")
    print("你可以输入: '帮我抓取 广州 ai应用，抓50个岗位'")
    print("------------------------------------------")

    while True:
        try:
            user_input = input("\n请输入指令 (输入 q 退出): ").strip()
            if not user_input: continue
            if user_input.lower() == 'q': break
            
            intent = parse_intent(user_input)
            if not intent:
                print("!! 无法识别有效参数，请重试。")
                continue
                
            kw = intent.get("keyword")
            ct = intent.get("city", "")
            sl = intent.get("salary", "不限").upper()
            sp = int(intent.get("start_page", 1))
            tj = int(intent.get("target_jobs", 15))
            
            print(f">> 确认任务: 关键词={kw}, 城市={ct}, 薪资={sl}, 起始页={sp}, 目标入库数={tj}")
            
            run_task(kw, ct, sp, tj, sl)
            
        except KeyboardInterrupt:
            print("\n>> 用户中断，程序退出。")
            break
        except Exception as e:
            print(f"!! 运行异常: {e}")

# ==================== 🤖 飞书聊天框接入：智联招聘 专属控制层 ====================

from app.services.feishu_service import send_feishu_message

def run_scraping_task(keyword: str, city: str, salary: str, target_jobs: int = 15, start_page: int = 1,
                      sse_task_id: str = None, loop=None, ledger_keyword=None, ledger_city=None,
                      ledger_salary=None, result_meta=None) -> int:
    print(f"   [run_scraping_task] keyword={keyword}, city={city}, salary={salary}, start_page={start_page}, target={target_jobs}")
    total = run_task(
        keyword, city, int(start_page), int(target_jobs), salary or "不限", sse_task_id, loop,
        ledger_keyword=ledger_keyword, ledger_city=ledger_city,
        ledger_salary=ledger_salary, result_meta=result_meta,
    )
    return int(total or 0)

async def _notify_feishu(chat_id: str, message: str):
    if chat_id and chat_id not in ("", "agent_cli"):
        await asyncio.to_thread(send_feishu_message, chat_id, message, "chat_id")
    else:
        print(f"📢 [控制台模式] {message}")

async def process_zhilian_scraping_request(chat_id: str, city: str, keyword: str, salary: str, start_page: int = 1,
                                           target_jobs: int = 15, sse_task_id: str = None,
                                           ledger_keyword: str | None = None, ledger_city: str | None = None,
                                           ledger_salary: str | None = None, result_meta: dict | None = None):
    set_stop_flag(False)

    try:
        start_page = int(start_page)
    except (TypeError, ValueError):
        start_page = 1
    try:
        target_jobs = int(target_jobs)
    except (TypeError, ValueError):
        target_jobs = 15

    print(f"\n{'='*50}")
    print(f"🕵️ [DEBUG] 飞书请求已进入 智联招聘 执行中枢！参数: 城市={city}, 岗位={keyword}, 薪资={salary}, target_jobs={target_jobs}")

    try:
        await _notify_feishu(
            chat_id,
            (
                f"✅ 收到指令！正在启动 [智联招聘] 爬虫引擎...\n"
                f"📍 城市：{city}\n"
                f"🎯 岗位：{keyword}\n"
                f"💰 薪资：{salary}\n"
                f"📦 目标数量：{target_jobs} 个\n\n"
            )
        )

        loop = asyncio.get_running_loop()

        # 🌟 安装活动心跳：瀑布流抓取长静默期间至多每 30s 报一次平安，
        # 防全链路转发协程把静默误判为任务结束而并发二次派发
        _hb_state = {"last": 0.0}

        def _heartbeat_hook():
            if not sse_task_id:
                return
            now = time.monotonic()
            if now - _hb_state["last"] >= 30:
                _hb_state["last"] = now
                from app.tasks.state import task_queues
                q = task_queues.get(sse_task_id)
                if q:
                    loop.call_soon_threadsafe(q.put_nowait, 'data: {"type": "heartbeat"}\n\n')

        set_heartbeat_hook(_heartbeat_hook)
        if sse_task_id:
            from app.tasks.state import task_queues
            if sse_task_id in task_queues:
                msg = 'data: {"type": "start"}\n\n'
                await task_queues[sse_task_id].put(msg)
                
        total_inserted = await asyncio.to_thread(
            run_scraping_task,
            keyword,
            city,
            salary,
            target_jobs,
            start_page,
            sse_task_id,
            loop,
            ledger_keyword=ledger_keyword,
            ledger_city=ledger_city,
            ledger_salary=ledger_salary,
            result_meta=result_meta,
        )

        await _notify_feishu(
            chat_id,
            f"🎉 抓取任务圆满结束！\n本次共成功将 {total_inserted} 个【{city}-{keyword}】的岗位存入 SQLite 数据库！"
        )
        if sse_task_id:
            from app.tasks.state import task_queues
            if sse_task_id in task_queues:
                msg = 'data: {"type": "complete"}\n\n'
                await task_queues[sse_task_id].put(msg)
                
    except Exception as e:
        import traceback
        traceback.print_exc()
        try:
            await _notify_feishu(chat_id, f"❌ 抓取过程中断崩溃，错误日志: {e}")
        except Exception:
            pass
    finally:
        set_heartbeat_hook(None)  # 🌟 卸载心跳，避免残留钩子串到下一轮/CLI 模式

if __name__ == "__main__":
    main()
