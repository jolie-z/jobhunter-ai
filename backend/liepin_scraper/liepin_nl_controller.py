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

# 🌟 Windows 防闪窗：子进程统一走防闪窗包装（参照 engine_guard，收口见 backend/subprocess_utils.py）
from subprocess_utils import popen_hidden
from engine_guard import PORT_LOCK_BUSY_EXIT_CODE

from app.core.config import settings
from app.automation.dup_skip_parse import count_duplicate_skip
# 🌟 统一 Token 埋点
from app.core.llm_tracker import make_tracked_client
# 猎聘采集放行双判据（Cookie 文件 OR Edge profile 登录实证），与预检守卫同一实现
from app.session.health_checker import liepin_collect_ready
from app.session.registry import get_liepin_cookie_file
OPENAI_API_KEY = settings.OPENAI_API_KEY
OPENAI_BASE_URL = settings.OPENAI_BASE_URL
OPENAI_MODEL = settings.OPENAI_MODEL

client = make_tracked_client(OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL), model_default=OPENAI_MODEL, caller="liepin_nl_controller")

# 🌟 全局急刹车开关：被飞书 stop_scrape 指令拉高后，底层循环会检测并优雅退出
GLOBAL_STOP_FLAG = False

# 🌟 最近一次引擎子进程崩溃原因（None=无）：run_task 崩溃快停时写入，
# 异步入口 process_liepin_scraping_request 读取后回飞书告警（0928 事故修复）
LAST_ENGINE_CRASH = None

# 🌟 最近一轮是否命中「访客态登录墙」（2026-10-31 事故根治）：采集器输出
# [LIEPIN_GUEST_BLOCKED] 契约行时置位，run_task 据此把本轮计为登录源失效
# （success=False 写台账与 result_meta），与「到底/滑块」明确区分
LAST_GUEST_BLOCKED = False

def set_stop_flag(value: bool):
    """外部（例如 FastAPI 路由）调用此函数拉起 / 释放猎聘急刹车。"""
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
            print("\n   🛑 [猎聘急刹车触发] 休眠被提前中断，跳过后续休眠。")
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

def _process_crawler_output(process, sse_task_id, loop, target_jobs, current_page, real_time_inserted, skip_state=None):
    """实时处理爬虫子进程输出，负责急刹车检测与进度推送；顺带捕获搜索总数（分母）"""
    global GLOBAL_STOP_FLAG, LAST_GUEST_BLOCKED
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

        # 重复岗位跳过计数（前置查重命中行，实况送前端横幅）
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

        # 实时进度监控: 匹配 "[抓取成功]"
        if sse_task_id and loop and "[抓取成功]" in line:
            real_time_inserted += 1
            from app.tasks.state import task_queues
            if sse_task_id in task_queues:
                msg = f'data: {{"type": "progress", "total_inserted": {real_time_inserted}, "target_jobs": {target_jobs}, "current_page": {current_page}}}\n\n'
                asyncio.run_coroutine_threadsafe(task_queues[sse_task_id].put(msg), loop)

        # 到底或被风控的标志（采集器当前只输出“未截获到包含”；旧版
        # “未捕获到 API 数据”已不存在，保留死条件只会让契约测试失真）
        if "未截获到包含" in line:
            hit_bottom = True

        # 访客态登录墙标记（2026-10-31 事故根治）：采集器在 Cookie 失效/缺失时
        # 降级游客态，深页搜索必被登录墙拦截——此时「未截获」不是到底/验证码，
        # 本轮必须按登录源失效计失败，绝不静默 0 条还报成功。
        if "LIEPIN_GUEST_BLOCKED" in line:
            LAST_GUEST_BLOCKED = True

    process.wait()
    return real_time_inserted, hit_bottom, search_total

def run_task(keyword, city, start_page, target_jobs, salary, sse_task_id=None, loop=None,
             ledger_keyword=None, ledger_city=None, ledger_salary=None, result_meta=None):
    """🌟 动态 While 循环，实时解析猎聘终端日志。支持 GLOBAL_STOP_FLAG 中断。"""
    global GLOBAL_STOP_FLAG, LAST_ENGINE_CRASH, LAST_GUEST_BLOCKED
    LAST_ENGINE_CRASH = None
    LAST_GUEST_BLOCKED = False
    if int(target_jobs or 0) <= 0:
        # 0/负目标不是一次抓取轮次：不回报台账，避免连续空跑被误判抓尽
        return 0
    total_inserted = 0
    current_page = start_page
    last_touched = start_page
    search_total = 0
    fatal = False
    port_busy = False
    skip_state = {"n": 0}  # 本轮重复跳过累计（可变盒跨页累加）
    
    while total_inserted < target_jobs:
        # 🌟 主循环（翻页循环）首部急刹车检查
        if GLOBAL_STOP_FLAG:
            print("🛑 [猎聘急刹车触发] 收到全局中断信号，立即终止当前翻页循环！")
            break
        print(f"\n{'=' * 60}")
        print(f"🎯 进度: 已入库 {total_inserted}/{target_jobs} 个 | 正在执行: 第 {current_page} 页")
        print(f"📌 条件: 关键词={keyword} | 城市={city} | 薪资={salary}")

        cmd = _build_crawler_cmd(keyword, city, current_page, target_jobs, salary, total_inserted)

        # 🌟 核心修复：构造环境变量，将项目根目录加入 PYTHONPATH
        my_env = os.environ.copy()
        my_env["PYTHONPATH"] = PROJECT_ROOT
        my_env["PYTHONIOENCODING"] = "utf-8"

        process = popen_hidden(
            cmd, cwd=CURRENT_DIR,
            env=my_env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding='utf-8', errors='replace'
        )
        
        real_time_inserted, hit_bottom, page_search_total = _process_crawler_output(
            process, sse_task_id, loop, target_jobs, current_page, total_inserted, skip_state
        )
        # 外审 R2-P1（B2）：仅在当页正常跑完（returncode==0）后才推进 last_touched——
        # 端口忙/崩溃页并未真正抓取，提前推进会把未抓取页写进续抓游标造成漏页
        if process.returncode == 0:
            last_touched = current_page
        if page_search_total > 0:
            search_total = page_search_total

        # 🌟 本页结束后再检一次急刹车，避免继续进入 countdown_sleep
        if GLOBAL_STOP_FLAG:
            print("🛑 [猎聘急刹车触发] 当前页处理完毕，根据中断信号退出翻页循环。")
            total_inserted = real_time_inserted
            fatal = True
            break
        
        # 跨进程端口锁被另一个 JobHunter 实例持有：协调性跳过，不是环境故障。
        # 外审 R2-P1（B2）：必须置失败态——否则 0 入库按 success=True 计入
        # 「连续 0 新增」判尽阈值，存在误触发 7 天冻结的风险（对齐 zhilian/51job 语义）
        if process.returncode == PORT_LOCK_BUSY_EXIT_CODE:
            print("\n⏳ [调度器] 猎聘浏览器端口正被占用（本进程或另一个 JobHunter 实例），本轮抓取跳过（非环境故障）")
            total_inserted = real_time_inserted
            port_busy = True
            break

        # 针对猎聘特殊的 99 安全熔断拦截
        if process.returncode == 99:
            print("\n🚨 检测到子进程返回 99 错误码，触发风控熔断，停止任务！")
            total_inserted = real_time_inserted
            fatal = True
            break

        # 引擎崩溃快停（0928 事故修复）：子进程非 0/99 退出=崩溃（如浏览器拉起失败），
        # 不再当「本页 0 收获」傻睡翻页——否则崩溃-休眠死循环无页数上限
        if process.returncode not in (0, 99):
            LAST_ENGINE_CRASH = (
                f"猎聘爬虫子进程异常退出(code={process.returncode})，已中止翻页循环"
            )
            print(f"\n🚨 [猎聘] {LAST_ENGINE_CRASH}")
            print("   （浏览器类故障请另查 backend/logs/edge_liepin.log 与上方堆栈）")
            total_inserted = real_time_inserted
            fatal = True
            break

        total_inserted = real_time_inserted
        
        if hit_bottom:
            if LAST_GUEST_BLOCKED:
                print("\n>> 🚨 触发中断：猎聘以访客态运行且未截获任何岗位数据包（登录墙/验证码拦截）。")
                print("   本轮按「登录源失效」计失败：请在指挥中心会话条扫码登录猎聘（或运行 liepin_cookie_harvester.py）后重试。")
            else:
                print("\n>> ⚠️ 触发中断：猎聘未返回数据，可能是到底部或遇到滑块验证码。")
            break
            
        if total_inserted >= target_jobs:
            print(f"\n>> 🎉 目标达成！累计已入库 {total_inserted} 个岗位 (目标: {target_jobs})。")
            break
            
        current_page += 1
        countdown_sleep(random.randint(180, 300))

    print(f"\n🏁 本轮指令执行完毕！最终入库: {total_inserted}")

    # 回写「条件×平台」进度台账：使用原始条件（不是平台映射后的薪资/关键词）
    # 访客态登录墙（2026-10-31）必须计失败：否则 0 条静默收场，台账只按
    # 「连续 0 新增」兜底判尽，用户无从知道是登录源坏了。
    success = (not fatal) and not port_busy and LAST_ENGINE_CRASH is None and not GLOBAL_STOP_FLAG and not LAST_GUEST_BLOCKED
    # 失败原因（供指挥中心弹窗/飞书通知下发）：手动急刹不产生失败通知
    fail_reason = None
    if not success and not GLOBAL_STOP_FLAG:
        if port_busy:
            fail_reason = "浏览器端口被占用（另一个 JobHunter 实例在使用），本轮抓取跳过"
        elif LAST_ENGINE_CRASH:
            fail_reason = LAST_ENGINE_CRASH
        elif LAST_GUEST_BLOCKED:
            fail_reason = "登录源失效：访客态被登录墙拦截（请在全景控制台扫码登录猎聘后重试）"
        else:
            fail_reason = "本轮抓取异常中止（详见任务日志）"
    try:
        from app.session.scrape_sessions import report_condition_round
        report_condition_round(
            ledger_keyword if ledger_keyword is not None else keyword,
            ledger_city if ledger_city is not None else (city or ""),
            ledger_salary if ledger_salary is not None else salary,
            "liepin",
            total_inserted,
            search_total or None,
            # 猎聘的“未截获到包含”也可能是滑块验证码，不能当作确认到底；
            # 交给连续 0 新增阈值兜底，避免误判后冻结 7 天。
            hit_bottom=False,
            success=success,
        )
    except Exception as e:
        print(f"⚠️ 猎聘条件台账回写失败: {e}")

    if result_meta is not None:
        # 猎聘的“未截获到包含”可能是滑块验证码，不能当确认到底：
        # 台账侧已按 hit_bottom=False 走连续 0 新增兜底，页码侧也必须一致——
        # 保留真实末页、不归零，避免验证码误判触发从第 1 页全量重扫。
        # 真到底时由连续 0 新增判尽；TTL 重开时 clear_exhaustion 会把 last_page 归零，
        # 下一轮自然从第 1 页重新找新岗位。
        result_meta.update({
            "inserted": int(total_inserted or 0),
            "search_total": int(search_total or 0),
            "hit_bottom": False,
            "last_page": int(last_touched or 0),
            "success": bool(success),
            "fail_reason": fail_reason,
        })

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

# ==================== 🤖 飞书聊天框接入：猎聘抓取专属控制层 ====================

from app.services.feishu_service import send_feishu_message

def run_scraping_task(keyword: str, city: str, salary: str, start_page: int = 1, target_jobs: int = 40,
                      sse_task_id: str = None, loop=None, ledger_keyword=None, ledger_city=None,
                      ledger_salary=None, result_meta=None) -> int:
    """猎聘简化版抓取入口：从 start_page 起抓到目标入库数 target_jobs。

    薄包装层，与 CLI 用的 run_task 共享同一份底层执行逻辑（while 循环 + Popen），
    返回 total_inserted（本次累计入库数），方便异步入口回报飞书。
    """
    print(f"   [run_scraping_task/liepin] keyword={keyword}, city={city}, salary={salary}, start_page={start_page}, target={target_jobs}")
    total = run_task(
        keyword, city, int(start_page), int(target_jobs), salary or "不限", sse_task_id, loop,
        ledger_keyword=ledger_keyword, ledger_city=ledger_city,
        ledger_salary=ledger_salary, result_meta=result_meta,
    )
    return int(total or 0)


async def _notify_feishu_liepin(chat_id: str, message: str):
    """仅在有效 chat_id 时推送飞书，否则只打印日志，防止虚假 chat_id 触发 HTTP 400。"""
    if chat_id and chat_id not in ("", "agent_cli"):
        await asyncio.to_thread(send_feishu_message, chat_id, message, "chat_id")
    else:
        print(f"📢 [控制台模式] {message}")


async def process_liepin_scraping_request(chat_id: str, city: str, keyword: str, salary: str, start_page: int = 1,
                                          target_jobs: int = 40, sse_task_id: str = None,
                                          ledger_keyword: str | None = None, ledger_city: str | None = None,
                                          ledger_salary: str | None = None, result_meta: dict | None = None):
    global LAST_ENGINE_CRASH
    print(f"\n{'='*50}")
    print(f"🕵️ [DEBUG] 飞书请求已进入猎聘执行中枢！参数: 城市={city}, 岗位={keyword}, 薪资={salary}, start_page={start_page}, target_jobs={target_jobs}")

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

        # 猎聘特有：采集放行双判据（2026-09-27；2026-10-31 文件侧从「存在」升级为
        # 「有效」）——Cookie 文件凭证未过期，或 Edge profile 登录实证有效。会话条
        # 「唤起浏览器」与采集引擎（DrissionPage 9226）共用同一 profile，用户在指挥
        # 中心登录后即使无文件/文件过期也可开工；引擎确认 profile 登录后会把 cookie
        # 自愈回写文件（liepin_crawler._self_heal_cookie_file），两条通道收敛。
        # 外审 R2-P1（B2）：与采集器/会话层收敛到 get_liepin_cookie_file() 单一口径——
        # 硬编码脚本目录路径在 JOBHUNTER_DATA_DIR 隔离布局下查错位置，冷浏览器时
        # 门禁会因查不到文件误判登录失效而阻断抓取
        cookie_file = get_liepin_cookie_file()
        if not await asyncio.to_thread(liepin_collect_ready, cookie_file):
            err_msg = (
                "❌ 猎聘 Cookie 缺失/已失效且未检出浏览器登录态：请在全景控制台「唤起浏览器」登录猎聘，"
                "或在后端终端运行 `liepin_cookie_harvester.py` 扫码登录！"
            )
            print(f"⚠️ 猎聘 Cookie 文件缺失或已失效，且浏览器未检出登录态: {cookie_file}")
            # 1. 优先标记 result_meta（阻止外层调度器按正常收尾处理，供 _run_and_track 触发弹窗和保留游标）
            if result_meta is not None:
                result_meta.update({
                    "success": False,
                    "fail_reason": "猎聘登录态失效（Cookie缺失或已过期且浏览器未登录）",
                    "inserted": 0,
                    "search_total": 0,
                    "last_page": start_page,
                    "hit_bottom": False,
                })
            # 2. 优先推送 SSE 错误事件（前端 live-task-terminal 消费 type: error 翻红并主动关闭连接，终态防刷绿）
            if sse_task_id:
                from app.tasks.state import task_queues
                if sse_task_id in task_queues:
                    payload = json.dumps({"type": "error", "message": err_msg}, ensure_ascii=False)
                    await task_queues[sse_task_id].put(f"data: {payload}\n\n")
            # 3. 异步外部通知兜底，避免飞书网络抖动阻塞前端错误传播
            try:
                await _notify_feishu_liepin(chat_id, err_msg)
            except Exception as e:
                print(f"⚠️ 猎聘门禁失败飞书通知发送失败(已忽略): {e}")
            return
        if not os.path.exists(cookie_file):
            print("✅ Cookie 文件缺失，但专用浏览器登录实证有效，放行（采集启动后将自动回写文件）")

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
            keyword, city, salary, start_page, target_jobs, sse_task_id, loop,
            ledger_keyword=ledger_keyword,
            ledger_city=ledger_city,
            ledger_salary=ledger_salary,
            result_meta=result_meta,
        )

        # 引擎崩溃告警（0928 事故修复）：run_task 快停后此处回飞书真实原因，不发庆功报文
        if LAST_ENGINE_CRASH:
            crash_reason = LAST_ENGINE_CRASH
            LAST_ENGINE_CRASH = None  # 读取即清，防跨请求/并发残留（code-review R1-P1）
            print(f"🕵️ [DEBUG] 猎聘抓取异常中止: {crash_reason}")
            await _notify_feishu_liepin(
                chat_id,
                f"❌ 猎聘抓取中止：{crash_reason}。\n"
                f"请检查后端日志排查；浏览器类故障另见 backend/logs/edge_liepin.log。"
            )
            if sse_task_id:
                from app.tasks.state import task_queues
                if sse_task_id in task_queues:
                    payload = json.dumps(
                        {"type": "complete", "message": f"❌ 猎聘抓取中止：{crash_reason}"},
                        ensure_ascii=False,
                    )
                    await task_queues[sse_task_id].put(f'data: {payload}\n\n')
            return

        print(f"🕵️ [DEBUG] 猎聘抓取逻辑执行完毕，返回入库数: {total_inserted}")

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
        print(f"⚠️ 猎聘抓取异常: {e}")
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