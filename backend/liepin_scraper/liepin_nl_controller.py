#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
自然语言驱动的 猎聘大管家 (动态目标调度版)

功能：
1. 目标驱动：基于 target_jobs 设定入库目标，自动跨页抓取。
2. 实时日志监听与正则匹配入库量。
3. 针对猎聘的特性保留了 99 返回码安全熔断机制。
"""

import os
import sys
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

from app.core.config import settings
# 🌟 统一 Token 埋点
from app.core.llm_tracker import make_tracked_client
OPENAI_API_KEY = settings.OPENAI_API_KEY
OPENAI_BASE_URL = settings.OPENAI_BASE_URL
OPENAI_MODEL = settings.OPENAI_MODEL

client = make_tracked_client(OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL), model_default=OPENAI_MODEL, caller="liepin_nl_controller")

# 🌟 全局急刹车开关：被飞书 stop_scrape 指令拉高后，底层循环会检测并优雅退出
GLOBAL_STOP_FLAG = False

def set_stop_flag(value: bool):
    """外部（例如 FastAPI 路由）调用此函数拉起 / 释放猞聘急刹车。"""
    global GLOBAL_STOP_FLAG
    GLOBAL_STOP_FLAG = bool(value)
    print(f"🌟 [liepin set_stop_flag] GLOBAL_STOP_FLAG → {GLOBAL_STOP_FLAG}")

# 🌟 活动心跳钩子：由异步入口安装；在翻页大休眠 / stdout 无新行的长静默期间，
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

INTENT_SYSTEM_PROMPT = """你是一个猎聘爬虫调度助手。
请将用户的指令解析成以下严格的 JSON 格式，不要输出任何其他内容或说明：
{
  "keyword": "搜索关键词（字符串）",
  "city": "城市名称（字符串，如全国/北京/上海等，未提及则填全国）",
  "salary": "薪资描述（字符串，如不限/20-30K，未提及则填不限）",
  "start_page": 起始页码（整数，默认1）,
  "target_jobs": 期望成功入库的岗位数量 (整数，如果用户说抓X页，按一页40个估算为 X*40；如果直接要求抓X个，则填X)
}"""

def parse_intent(user_input):
    print(f">> 🧠 正在解析指令：{user_input}")
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
        print(f">> ❌ 指令解析失败: {e}")
        return None

def countdown_sleep(seconds):
    """翻页大休眠。支持 GLOBAL_STOP_FLAG 提前中断。"""
    global GLOBAL_STOP_FLAG
    print(f"\n   💤 翻页大休眠，计划休眠 {seconds} 秒...")
    for i in range(seconds, 0, -1):
        # 🌟 急刹车检查：休眠期间随时可以被飞书指令中断
        if GLOBAL_STOP_FLAG:
            print("\n   🛑 [猞聘急刹车触发] 休眠被提前中断，跳过后续休眠。")
            return
        if i % 30 == 0 or i <= 5:
            print(f"   ⏳ [防风控潜行中] 还剩 {i} 秒...", end='\r', flush=True)
        _ping_heartbeat()  # 🌟 休眠期间也报平安，防转发协程误判
        time.sleep(1)
    print("\n   ✅ 休眠结束，继续下一页抓取！\n")

def _build_crawler_cmd(keyword, city, start_page, target_jobs, salary, total_inserted):
    """构建调用子进程的命令行参数"""
    crawler_path = os.path.join(CURRENT_DIR, "liepin_crawler.py")
    cmd = [
        sys.executable, "-u", crawler_path, # 🌟 -u 参数保持实时输出
        "-p", str(start_page),
        "--keyword", keyword,
        "--target", str(target_jobs - total_inserted)
    ]
    if city: cmd.extend(["--city", city])
    if salary and salary != "不限": cmd.extend(["--salary", salary])
    return cmd

def _process_crawler_output(process, sse_task_id, loop, target_jobs, current_page, real_time_inserted):
    """实时处理爬虫子进程输出，负责急刹车检测与进度推送；顺带捕获搜索总数（分母）"""
    global GLOBAL_STOP_FLAG
    hit_bottom = False
    search_total = 0

    for line in process.stdout:
        # 🌟 内层循环（逐岗位输出流）首部急刹车检查
        if GLOBAL_STOP_FLAG:
            print("\n🛑 [聘急刹车触发] 正在强制终止 liepin_crawler 子进程，退出当前页的岗位遭取流！")
            try:
                process.terminate()
            except Exception:
                pass
            break
        print(line, end="")
        _ping_heartbeat()  # 🌟 stdout 有活动即报平安（钩子内部 30s 节流）

        # 捕获搜索总数（分母）协议行
        if "搜索总数" in line and "个" in line:
            try:
                search_total = int(line.split("搜索总数", 1)[1].split("个", 1)[0].strip())
            except Exception:
                pass

        # 实时进度监控: 匹配 "[抓取成功]"
        if sse_task_id and loop and "[抓取成功]" in line:
            real_time_inserted += 1
            from app.tasks.state import task_queues
            if sse_task_id in task_queues:
                msg = f'data: {{"type": "progress", "total_inserted": {real_time_inserted}, "target_jobs": {target_jobs}, "current_page": {current_page}}}\n\n'
                asyncio.run_coroutine_threadsafe(task_queues[sse_task_id].put(msg), loop)

        # 到底或被风控的标志
        if "未截获到包含" in line or "未捕获到 API 数据" in line:
            hit_bottom = True

    process.wait()
    return real_time_inserted, hit_bottom, search_total

def run_task(keyword, city, start_page, target_jobs, salary, sse_task_id=None, loop=None):
    """🌟 动态 While 循环，实时解析猎聘终端日志。支持 GLOBAL_STOP_FLAG 中断。"""
    total_inserted = 0
    current_page = start_page
    search_total = 0
    global GLOBAL_STOP_FLAG
    
    while total_inserted < target_jobs:
        # 🌟 主循环（翻页循环）首部急刹车检查
        if GLOBAL_STOP_FLAG:
            print("🛑 [猞聘急刹车触发] 收到全局中断信号，立即终止当前翻页循环！")
            break
        print(f"\n{'=' * 60}")
        print(f"🎯 进度: 已入库 {total_inserted}/{target_jobs} 个 | 正在执行: 第 {current_page} 页")
        print(f"📌 条件: 关键词={keyword} | 城市={city} | 薪资={salary}")

        cmd = _build_crawler_cmd(keyword, city, current_page, target_jobs, salary, total_inserted)

        # 🌟 核心修复：构造环境变量，将项目根目录加入 PYTHONPATH
        my_env = os.environ.copy()
        my_env["PYTHONPATH"] = PROJECT_ROOT
        my_env["PYTHONIOENCODING"] = "utf-8"

        process = subprocess.Popen(
            cmd, cwd=CURRENT_DIR,
            env=my_env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding='utf-8', errors='replace'
        )
        
        real_time_inserted, hit_bottom, page_search_total = _process_crawler_output(
            process, sse_task_id, loop, target_jobs, current_page, total_inserted
        )
        if page_search_total > 0:
            search_total = page_search_total

        # 🌟 本页结束后再检一次急刹车，避免继续进入 countdown_sleep
        if GLOBAL_STOP_FLAG:
            print("🛑 [猞聘急刹车触发] 当前页处理完毕，根据中断信号退出翻页循环。")
            total_inserted = real_time_inserted
            break
        
        # 针对猞聘特殊的 99 安全熔断拦截
        if process.returncode == 99:
            print("\n🚨 检测到子进程返回 99 错误码，触发风控熔断，停止任务！")
            total_inserted = real_time_inserted
            break
            
        total_inserted = real_time_inserted
        
        if hit_bottom:
            print("\n>> ⚠️ 触发中断：猞聘未返回数据，可能是到底部或遇到滑块验证码。")
            break
            
        if total_inserted >= target_jobs:
            print(f"\n>> 🎉 目标达成！累计已入库 {total_inserted} 个岗位 (目标: {target_jobs})。")
            break
            
        current_page += 1
        countdown_sleep(random.randint(180, 300))

    print(f"\n🏁 本轮指令执行完毕！最终入库: {total_inserted}")

    # 回写「条件×平台」进度台账：分子累加本轮入库；拿到搜索总数则校准分母
    try:
        from app.session.scrape_sessions import report_condition_round
        report_condition_round(keyword, city or "", salary or "", "liepin",
                               total_inserted, search_total or None)
    except Exception as e:
        print(f"⚠️ 猎聘条件台账回写失败: {e}")

    return total_inserted

def main():
    print("=" * 60)
    print("🤖 猎聘 动态目标大管家 已就绪！")
    print("   示例：帮我抓取上海的生物信息，薪资20-30K，抓40个从第3页开始")
    print("=" * 60)

    COOKIE_FILE = os.path.join(CURRENT_DIR, 'liepin_cookies.json')
    if os.path.exists(COOKIE_FILE):
        print("✅ 已检测到 Cookie 文件 (liepin_cookies.json)。")
    else:
        print("⚠️ 警告：未检测到 Cookie 文件！请确保能自动扫码登录。")

    while True:
        try:
            user_input = input("\n请输入抓取指令 (输入 q 退出): ").strip()
            if not user_input: continue
            if user_input.lower() == 'q': break
            
            intent = parse_intent(user_input)
            if not intent: continue
            
            kw = intent.get("keyword", "").strip()
            ct = intent.get("city", "全国").strip()
            sl = intent.get("salary", "不限").strip().upper()
            sp = int(intent.get("start_page", 1))
            tj = int(intent.get("target_jobs", 40))

            if not kw: continue
            
            print(f">> 确认任务: 关键词={kw}, 城市={ct}, 薪资={sl}, 起始页={sp}, 目标={tj}")
            run_task(kw, ct, sp, tj, sl)
            
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"!! 异常: {e}")

# ==================== 🤖 飞书聊天框接入：猞聘抓取专属控制层 ====================

from app.services.feishu_service import send_feishu_message

def run_scraping_task(keyword: str, city: str, salary: str, start_page: int = 1, target_jobs: int = 40, sse_task_id: str = None, loop=None) -> int:
    """猞聘简化版抓取入口：从 start_page 起抓到目标入库数 target_jobs。

    薄包装层，与 CLI 用的 run_task 共享同一份底层执行逻辑（while 循环 + Popen），
    返回 total_inserted（本次累计入库数），方便异步入口回报飞书。
    """
    print(f"   [run_scraping_task/liepin] keyword={keyword}, city={city}, salary={salary}, start_page={start_page}, target={target_jobs}")
    total = run_task(keyword, city, int(start_page), int(target_jobs), salary or "不限", sse_task_id, loop)
    return int(total or 0)


async def _notify_feishu_liepin(chat_id: str, message: str):
    """仅在有效 chat_id 时推送飞书，否则只打印日志，防止虚假 chat_id 触发 HTTP 400。"""
    if chat_id and chat_id not in ("", "agent_cli"):
        await asyncio.to_thread(send_feishu_message, chat_id, message, "chat_id")
    else:
        print(f"📢 [控制台模式] {message}")


async def process_liepin_scraping_request(chat_id: str, city: str, keyword: str, salary: str, start_page: int = 1, target_jobs: int = 40, sse_task_id: str = None):
    print(f"\n{'='*50}")
    print(f"🕵️ [DEBUG] 飞书请求已进入猞聘执行中枢！参数: 城市={city}, 岗位={keyword}, 薪资={salary}, start_page={start_page}, target_jobs={target_jobs}")

    # 🌟 重置急刹车（避免上一轮残留的 True 干扰本轮）
    set_stop_flag(False)

    # 入口处强制转 int，防止上游 LLM 返回字符串引起 TypeError
    try:
        start_page = int(start_page)
    except (TypeError, ValueError):
        start_page = 1
    try:
        target_jobs = int(target_jobs)
    except (TypeError, ValueError):
        target_jobs = 40

    try:
        await _notify_feishu_liepin(
            chat_id,
            (
                f"✅ 收到指令！正在启动 [猎聘] 爬虫引擎...\n"
                f"📍 城市：{city}\n"
                f"🎯 岗位：{keyword}\n"
                f"💰 薪资：{salary}\n"
                f"📄 起始页码：第 {start_page} 页\n"
                f"📦 目标数量：{target_jobs} 个"
            )
        )

        # 发送开始消息到 SSE 队列
        if sse_task_id:
            from app.tasks.state import task_queues
            if sse_task_id in task_queues:
                msg = 'data: {"type": "start", "message": "✅ 收到指令！正在启动 [猎聘] 爬虫引擎..."}\n\n'
                await task_queues[sse_task_id].put(msg)

        # 猞聘特有：检查 Cookie 文件是否已存在
        cookie_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'liepin_cookies.json')
        if not os.path.exists(cookie_file):
            print(f"⚠️ 猞聘 Cookie 文件不存在: {cookie_file}")
            await _notify_feishu_liepin(
                chat_id,
                "❌ 缺少猎聘 Cookie，请先在本地终端运行 `liepin_cookie_harvester.py` 扫码登录！"
            )
            return

        # 调用底层逻辑
        loop = asyncio.get_running_loop()

        # 🌟 安装活动心跳：翻页大休眠等长静默期间至多每 30s 报一次平安，
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
        total_inserted = await asyncio.to_thread(
            run_scraping_task,
            keyword, city, salary, start_page, target_jobs, sse_task_id, loop
        )
        print(f"🕵️ [DEBUG] 猞聘抓取逻辑执行完毕，返回入库数: {total_inserted}")

        await _notify_feishu_liepin(
            chat_id,
            f"🎉 猎聘抓取任务结束！\n本次共成功将 {total_inserted} 个【{city}-{keyword}】岗位存入 SQLite 数据库！"
        )
        if sse_task_id:
            from app.tasks.state import task_queues
            if sse_task_id in task_queues:
                msg = f'data: {{"type": "complete", "message": "🎉 猎聘抓取任务结束！本次共成功存入 {total_inserted} 个岗位"}}\n\n'
                await task_queues[sse_task_id].put(msg)
    except Exception as e:
        print(f"⚠️ 猞聘抓取异常: {e}")
        import traceback
        traceback.print_exc()
        try:
            await _notify_feishu_liepin(
                chat_id,
                f"❌ 猎聘抓取中断崩溃，错误日志: {e}"
            )
        except Exception:
            pass
    finally:
        set_heartbeat_hook(None)  # 🌟 卸载心跳，避免残留钩子串到下一轮/CLI 模式


if __name__ == "__main__":
    main()