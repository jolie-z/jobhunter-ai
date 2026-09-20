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

# 🌟 全局急刹车开关：被飞书 stop_scrape 指令拉高后，底层循环会检测并优雅退出
GLOBAL_STOP_FLAG = False

def set_stop_flag(value: bool):
    """外部（例如 FastAPI 路由）调用此函数拉起 / 释放急刹车。"""
    global GLOBAL_STOP_FLAG
    GLOBAL_STOP_FLAG = bool(value)
    print(f"🌟 [set_stop_flag] GLOBAL_STOP_FLAG → {GLOBAL_STOP_FLAG}")

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

# 🌟 修复并精简导入：直接从新配置中心拉取变量
from app.core.config import settings
OPENAI_API_KEY = settings.OPENAI_API_KEY
OPENAI_BASE_URL = settings.OPENAI_BASE_URL
OPENAI_MODEL = settings.OPENAI_MODEL

# 初始化 OpenAI 客户端
client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)

# 🌟 核心修改 1：修改系统提示词，提取“目标数量”而不是固定页数
INTENT_SYSTEM_PROMPT = """你是一个 BOSS直聘 爬虫调度助手。
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

def countdown_sleep(seconds):
    """带简单倒计时的休眠，防止频繁翻页触发风控。支持 Ctrl+C 强制中断。"""
    global GLOBAL_STOP_FLAG
    print(f"-- 翻页大休眠: 计划等待 {seconds} 秒...")
    try:
        for i in range(seconds, 0, -1):
            if GLOBAL_STOP_FLAG:
                print("\n🛑 [急刹车触发] 休眠被提前中断，跳过后续休眠。")
                return
            if i % 30 == 0 or i <= 5:
                print(f"   [等待中] 还剩 {i} 秒...", end='\r', flush=True)
            _ping_heartbeat()  # 🌟 休眠期间也报平安，防转发协程误判
            time.sleep(1)
        print("\n-- 休眠结束，开始下一页任务。")
    except KeyboardInterrupt:
        print("\n🛑 [紧急中断] 收到 Ctrl+C，已强制取消休眠！")
        raise  # 抛出给外层循环，直接结束整个任务

def _safe_terminate(process):
    """安全地终止子进程"""
    try:
        process.terminate()
        process.wait(timeout=5)
    except Exception:
        pass

def _build_crawler_cmd(crawler_path, keyword, city, current_page, remaining_target, salary):
    """构造爬虫子进程命令行参数"""
    cmd = [
        sys.executable, "-u", crawler_path,
        "--platform", "boss",
        "-p", str(current_page),
        "--keyword", keyword
    ]
    if city:
        cmd.extend(["--city", city])
    if salary and salary != "不限":
        cmd.extend(["--salary", salary])
    cmd.extend(["--target", str(remaining_target)])
    return cmd

def _process_crawler_output(process, total_inserted, current_page, on_page_done):
    """逐行解析终端输出流，实时处理推送与急刹车信号；顺带捕获搜索总数（分母）"""
    global GLOBAL_STOP_FLAG
    page_inserted = 0
    jobs_scraped_this_page = 0
    hit_bottom = False
    search_total = 0
    
    try:
        for line in process.stdout:
            if GLOBAL_STOP_FLAG:
                print("\n🛑 [急刹车触发] 正在强制终止子进程...")
                _safe_terminate(process)
                break
            print(line, end="")
            _ping_heartbeat()  # 🌟 stdout 有活动即报平安（钩子内部 30s 节流）

            # 捕获搜索总数（分母）协议行
            if "搜索总数" in line and "个" in line:
                try:
                    search_total = int(line.split("搜索总数", 1)[1].split("个", 1)[0].strip())
                except Exception:
                    pass

            # 实时识别：每成功抓取一个岗位，立即触发回调推送给前端
            if "抓取成功" in line:
                jobs_scraped_this_page += 1
                if on_page_done:
                    on_page_done(total_inserted + jobs_scraped_this_page, current_page)
                    
            match = re.search(r"新增入库 (\d+) 个", line)
            if match:
                page_inserted = int(match.group(1))
                
            if "无数据返回，可能已到底部" in line:
                hit_bottom = True
                
        process.wait() # 等待本页脚本彻底结束
    except KeyboardInterrupt:
        print("\n🛑 [紧急中断] 收到 Ctrl+C，正在暴力击杀底层的抓取子进程...")
        _safe_terminate(process)
        raise # 向上抛出
        
    return page_inserted, jobs_scraped_this_page, hit_bottom, search_total

def _run_single_page(crawler_path, keyword, city, current_page, target_jobs, salary, total_inserted, on_page_done):
    """提取单页抓取与调度逻辑"""
    global GLOBAL_STOP_FLAG

    if GLOBAL_STOP_FLAG:
        print("🛑 [急刹车触发] 收到全局中断信号，立即终止当前翻页循环！")
        return total_inserted, True, 0, None
        
    print(f"\n{'='*50}")
    print(f"🎯 当前进度: 已入库 {total_inserted}/{target_jobs} 个 | 正在执行: 第 {current_page} 页")
    print(f"📌 条件: 关键词={keyword} | 城市={city} | 薪资={salary}")
    
    remaining_target = target_jobs - total_inserted
    cmd = _build_crawler_cmd(crawler_path, keyword, city, current_page, remaining_target, salary)
        
    my_env = os.environ.copy()
    my_env["PYTHONPATH"] = PROJECT_ROOT
    my_env["PYTHONIOENCODING"] = "utf-8"

    process = subprocess.Popen(
        cmd, cwd=CURRENT_DIR,
        env=my_env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, 
        text=True, encoding='utf-8', errors='replace'
    )
    
    page_inserted, jobs_scraped, hit_bottom, page_search_total = _process_crawler_output(
        process, total_inserted, current_page, on_page_done
    )
        
    if process.returncode != 0 and process.returncode is not None:
        err_msg = f"底层爬虫遭遇异常拦截中断（退出码: {process.returncode}）"
        print(f"\n🛑 [调度器异常熔断] {err_msg}，已自动切断翻页任务！")
        total_inserted += max(page_inserted, jobs_scraped)
        if on_page_done:
            on_page_done(total_inserted, current_page)
        return total_inserted, True, page_search_total, err_msg
        
    if GLOBAL_STOP_FLAG:
        print("🛑 [急刹车触发] 当前页处理完毕，根据中断信号退出翻页循环。")
        total_inserted += max(page_inserted, jobs_scraped)
        if on_page_done:
            on_page_done(total_inserted, current_page)
        return total_inserted, True, page_search_total, None
    
    total_inserted += page_inserted
    if on_page_done:
        on_page_done(total_inserted, current_page)
    
    if hit_bottom:
        print(f"\n>> ⚠️ 触发熔断：Boss直聘已无更多【{keyword}】相关数据。")
        return total_inserted, True, page_search_total, None
        
    if total_inserted >= target_jobs:
        print(f"\n>> 🎉 目标达成！累计已成功入库 {total_inserted} 个岗位 (目标: {target_jobs})。程序停止下钻。")
        return total_inserted, True, page_search_total, None
        
    wait_time = random.randint(180, 300)
    countdown_sleep(wait_time)
    
    return total_inserted, False, page_search_total, None

def run_task(keyword, city, start_page, target_jobs, salary, on_page_done=None):
    """🌟 核心修改 2：动态 While 循环，实时解析终端日志进行累加"""
    crawler_path = os.path.join(CURRENT_DIR, "boss_collector.py")
    
    total_inserted = 0
    current_page = start_page
    search_total = 0
    fatal_error = None
    
    # 只要已入库数量小于目标，就一直抓下一页
    while total_inserted < target_jobs:
        total_inserted, should_break, page_search_total, err_msg = _run_single_page(
            crawler_path, keyword, city, current_page, target_jobs, salary, total_inserted, on_page_done
        )
        if page_search_total > 0:
            search_total = page_search_total
        if err_msg:
            fatal_error = err_msg
        if should_break:
            break
        current_page += 1

    print(f"\n>> 本轮动态抓取指令已全部执行完毕。最终入库总数：{total_inserted}")

    # 回写「条件×平台」进度台账：分子累加本轮入库；拿到搜索总数则校准分母
    try:
        from app.session.scrape_sessions import report_condition_round
        report_condition_round(keyword, city or "", salary or "", "boss",
                               total_inserted, search_total or None)
    except Exception as e:
        print(f"⚠️ BOSS 条件台账回写失败: {e}")

    # 🌟 若底层引擎异常崩溃且 0 入库，必须抛出异常由上层向前端标红告警，严禁假装“已完成”
    if fatal_error and total_inserted == 0:
        raise RuntimeError(fatal_error)

    return total_inserted

def main():
    print("------------------------------------------")
    print("BOSS直聘 动态目标调度大管家 已启动")
    print("你可以输入: '帮我抓取 广州 ai应用 15-20k，抓50个岗位，从第4页开始'")
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
                
            # 提取参数
            kw = intent.get("keyword")
            ct = intent.get("city", "")
            sl = intent.get("salary", "不限").upper()
            sp = int(intent.get("start_page", 1))
            tj = int(intent.get("target_jobs", 15)) # 默认为抓取 15 个（约等于一页）
            
            print(f">> 确认任务: 关键词={kw}, 城市={ct}, 薪资={sl}, 起始页={sp}, 目标入库数={tj}")
            
            run_task(kw, ct, sp, tj, sl)
            
        except KeyboardInterrupt:
            print("\n>> 用户中断，程序退出。")
            break
        except Exception as e:
            print(f"!! 运行异常: {e}")

# ==================== 🤖 飞书聊天框接入：BOSS 抓取专属控制层 ====================

# 🌟 从新建立的飞书业务服务层导入消息推送
from app.services.feishu_service import send_feishu_message


def run_scraping_task(keyword: str, city: str, salary: str, target_jobs: int = 15, start_page: int = 1, on_page_done=None) -> int:
    """简化版抓取入口：从 start_page 起抓到目标入库数 target_jobs。

    薄包装层，与 CLI 用的 run_task 共享同一份底层执行逻辑（while 循环 + Popen），
    返回 total_inserted（本次累计入库数），方便异步入口回报飞书。
    """
    print(f"   [run_scraping_task] keyword={keyword}, city={city}, salary={salary}, start_page={start_page}, target={target_jobs}")
    total = run_task(keyword, city, int(start_page), int(target_jobs), salary or "不限", on_page_done=on_page_done)
    return int(total or 0)


async def _notify_feishu(chat_id: str, message: str):
    """仅在有效 chat_id 时推送飞书，否则只打印日志，防止虚假 chat_id 触发 HTTP 400。"""
    if chat_id and chat_id not in ("", "agent_cli"):
        await asyncio.to_thread(send_feishu_message, chat_id, message, "chat_id")
    else:
        print(f"📢 [控制台模式] {message}")


async def process_boss_scraping_request(chat_id: str, city: str, keyword: str, salary: str, start_page: int = 1, target_jobs: int = 15, sse_task_id: str = None):
    # 🌟 每次启动新任务前，确保重置急刹车（避免上一轮残留的 True 干扰本轮）
    set_stop_flag(False)

    # 🌟 入口处强制转 int，防止上游 LLM 返回字符串引起 TypeError
    try:
        start_page = int(start_page)
    except (TypeError, ValueError):
        start_page = 1
    try:
        target_jobs = int(target_jobs)
    except (TypeError, ValueError):
        target_jobs = 15

    print(f"\n{'='*50}")
    print(f"🕵️ [DEBUG 1] 飞书请求已进入 BOSS 执行中枢！参数: 城市={city}, 岗位={keyword}, 薪资={salary}, start_page={start_page}, target_jobs={target_jobs}")

    try:
        event_loop = asyncio.get_running_loop()

        def _send_sse_event(payload: dict, *, from_worker_thread: bool = False):
            if not sse_task_id:
                return
            from app.tasks.state import task_queues
            q = task_queues.get(sse_task_id)
            if not q:
                return
            message = f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            if from_worker_thread:
                event_loop.call_soon_threadsafe(q.put_nowait, message)
            else:
                q.put_nowait(message)

        # 🌟 安装活动心跳：翻页大休眠等长静默期间至多每 30s 报一次平安，
        # 防全链路转发协程把静默误判为任务结束而并发二次派发
        _hb_state = {"last": 0.0}

        def _heartbeat_hook():
            now = time.monotonic()
            if now - _hb_state["last"] >= 30:
                _hb_state["last"] = now
                _send_sse_event({"type": "heartbeat"}, from_worker_thread=True)

        set_heartbeat_hook(_heartbeat_hook)

        # 1. 状态回传（开始）
        await _notify_feishu(
            chat_id,
            (
                f"✅ 收到指令！正在启动 [BOSS直聘] 爬虫引擎...\n"
                f"📍 城市：{city}\n"
                f"🎯 岗位：{keyword}\n"
                f"💰 薪资：{salary}\n"
                f"📄 起始页码：第 {start_page} 页\n"
                f"📦 目标数量：{target_jobs} 个\n\n"
                f"正在进行环境登录验证..."
            )
        )
        print("🕵️ [DEBUG 2] 启动通知已发送给飞书。准备定位执行环境...")

        # 2. 直接启动抓取引擎（DrissionPage 会自行接管环境和登录验证）
        print("🕵️ [DEBUG 5] 正在跳过旧版环境校验，直接进入基于 DrissionPage 的爬虫逻辑...")
        await _notify_feishu(chat_id, "🔐 BOSS 环境验证完毕，开始执行抓取...")

        # 6. 执行核心爬虫并捕获入库数量
        print(f"🕵️ [DEBUG 8] 正在调用底层 run_scraping_task | start_page={start_page}, target_jobs={target_jobs}")
        # run_scraping_task 是从 run_task 抽离的薄包装层，与 CLI 入口共享底层逻辑
        # 注意：底层若涉及浏览器页面，调用的是 get_browser_page()（规范化命名后的入口）

        _send_sse_event({
            "type": "progress",
            "total_inserted": 0,
            "target_jobs": target_jobs,
            "current_page": start_page,
        })

        latest_page = start_page

        # SSE 进度回调：从爬虫工作线程安全投递到主事件循环的任务队列
        def _sse_progress(total_inserted_now: int, current_page: int):
            nonlocal latest_page
            latest_page = current_page
            _send_sse_event(
                {
                    "type": "progress",
                    "total_inserted": total_inserted_now,
                    "target_jobs": target_jobs,
                    "current_page": current_page,
                },
                from_worker_thread=True,
            )

        total_inserted = await asyncio.to_thread(
            run_scraping_task,
            keyword,         # keyword
            city,            # city
            salary,          # salary
            target_jobs,     # target_jobs (动态)
            start_page,      # start_page (动态)
            _sse_progress,   # on_page_done 回调
        )

        print(f"🕵️ [DEBUG 9] 抓取逻辑执行完毕，返回入库数: {total_inserted}")

        # 推送最终进度 + 完成事件
        _send_sse_event({
            "type": "progress",
            "total_inserted": total_inserted,
            "target_jobs": target_jobs,
            "current_page": latest_page,
        })
        _send_sse_event({"type": "complete"})

        # 7. 状态回传（结束）
        await _notify_feishu(
            chat_id,
            f"🎉 抓取任务圆满结束！\n本次共成功将 {total_inserted} 个【{city}-{keyword}】的岗位存入 SQLite 数据库！"
        )
        print(f"🕵️ [DEBUG 10] 成功日志已回传飞书。流程彻底结束。\n{'='*50}\n")

    except Exception as e:
        print(f"🕵️ [DEBUG ERROR] ❌ 发生未捕获的 Python 代码级崩溃: {e}")
        import traceback
        traceback.print_exc()
        try:
            _send_sse_event({"type": "error", "message": str(e)})
        except Exception:
            pass
        try:
            await _notify_feishu(chat_id, f"❌ 抓取过程中断崩溃，错误日志: {e}")
        except Exception:
            pass
    finally:
        set_heartbeat_hook(None)  # 🌟 卸载心跳，避免残留钩子串到下一轮/CLI 模式


if __name__ == "__main__":
    main()
