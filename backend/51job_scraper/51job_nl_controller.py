#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
自然语言驱动的 51job (前程无忧) 动态目标调度大管家

功能：
1. 目标驱动：设定目标入库数量（如50个），程序自动翻页抓取直至满足条件。
2. 实时监听：截获底层爬虫输出，实时累加进度。
3. 纯净防止乱码解析。
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

from engine_guard import PORT_LOCK_BUSY_EXIT_CODE

# 🌟 Windows 防闪窗：子进程统一走防闪窗包装（参照 engine_guard，收口见 backend/subprocess_utils.py）
from subprocess_utils import popen_hidden

# 🌟 修复并精简导入：直接从新配置中心拉取变量
from app.core.config import settings
from app.automation.dup_skip_parse import count_duplicate_skip
OPENAI_API_KEY = settings.OPENAI_API_KEY
OPENAI_BASE_URL = settings.OPENAI_BASE_URL
OPENAI_MODEL = settings.OPENAI_MODEL

client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)

# 🌟 全局急刹车开关：被飞书 stop_scrape 指令拉高后，底层循环会检测并优雅退出
GLOBAL_STOP_FLAG = False

def set_stop_flag(value: bool):
    """外部（例如 FastAPI 路由）调用此函数拉起 / 释放 51job 急刹车。"""
    global GLOBAL_STOP_FLAG
    GLOBAL_STOP_FLAG = bool(value)
    print(f"🌟 [51job set_stop_flag] GLOBAL_STOP_FLAG → {GLOBAL_STOP_FLAG}")

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

# 🌟 修改系统提示词，提取 target_jobs
INTENT_SYSTEM_PROMPT = """你是一个 51job(前程无忧) 爬虫调度助手。
请将用户的指令解析成以下严格的 JSON 格式，不要输出任何其他内容或说明文字：
{
  "keyword": "搜索关键词（字符串，必须提取）",
  "city": "城市名称（字符串，如广州/深圳等，未提及则填'全国'）",
  "salary": "薪资描述（字符串，必须仔细检查输入中是否有如 15-20k、1万-2万 的字眼并提取。仅当完全未提及薪资时才填'不限'）",
  "start_page": 起始页码（整数，必须仔细检查如'从第X页开始'，提取出数字X。默认1）,
  "target_jobs": 期望成功入库的岗位数量 (整数，如'抓取X个'则提取X)
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
    print(f"\n   💤 翻页大休眠，计划等待 {seconds} 秒（约 {seconds // 60} 分钟）...")
    for i in range(seconds, 0, -1):
        # 🌟 急刹车检查：休眠期间随时可以被飞书指令中断
        if GLOBAL_STOP_FLAG:
            print("\n   🛑 [51job 急刹车触发] 休眠被提前中断，跳过后续休眠。")
            return
        if i % 30 == 0 or i <= 5:
            print(f"   ⏳ [潜行防风控中] 还剩 {i} 秒...", end='\r', flush=True)
        _ping_heartbeat()  # 🌟 休眠期间也报平安，防转发协程误判
        time.sleep(1)
    print("\n   ✅ 休眠结束，启动下一页任务！\n")

def _build_crawler_cmd(crawler_path, current_page, keyword, city, salary, remaining=0):
    """构建爬虫子进程的启动命令；remaining>0 时下发剩余配额，collector 凑满即停"""
    cmd = [
        sys.executable, "-u", crawler_path,  # 🌟 必须加 -u 防止缓冲卡死
        "--platform", "51job",
        "-p", str(current_page),
        "--keyword", keyword,
        "--target", str(max(0, int(remaining or 0))),
    ]
    if city and city != "全国": 
        cmd.extend(["--city", city])
    if salary and salary != "不限": 
        cmd.extend(["--salary", salary])
    return cmd

def _safe_terminate(process):
    """安全终止爬虫子进程"""
    try:
        process.terminate()
    except Exception:
        pass

def _process_crawler_output(process, target_jobs, total_inserted, current_page, on_page_done, skip_state=None, on_skip=None):
    """处理爬虫子进程的输出流并返回最新状态；顺带捕获搜索总数（分母）。

    第 4 个返回值 terminated_by_controller：本函数主动 SIGTERM 了子进程（达标收工
    或用户急刹）。调用方据此区分「正常收工」与「真实环境故障」——两者都会得到
    非 0 退出码（POSIX SIGTERM = -15），只看 returncode 必然误报。

    第 5 个返回值 page_load_failed：采集器报告本页加载失败（超时/风控/DOM 变化）。
    失败页不是平台到底，调用方必须按失败轮处理（不写抓尽；非首页失败会重置为
    第 1 页重开，避免在越界页死循环）。

    底部/失败信号（2026-10-31 结构化）：
    - ``[[HIT_BOTTOM]]``     分页按钮确实不可用（真实末页）
    - ``[[PAGE_LOAD_FAILED]]`` 页面加载/解析失败（超时、风控、无数据）
    不再用“无任何岗位数据”等人类可读文案做子串匹配——该文案也出现在超时提示里，
    会把一次网络抖动误判成平台到底。
    """
    global GLOBAL_STOP_FLAG
    hit_bottom = False
    page_load_failed = False
    search_total = 0
    terminated_by_controller = False

    for line in process.stdout:
        # 🌟 内层循环（逐岗位输出流）首部急刹车检查
        if GLOBAL_STOP_FLAG:
            print("\n🛑 [51job 急刹车触发] 正在强制终止 51job_collector 子进程，退出当前页的岗位遭取流！")
            _safe_terminate(process)
            terminated_by_controller = True
            break
        print(line, end="")
        _ping_heartbeat()  # 🌟 stdout 有活动即报平安（钩子内部 30s 节流）

        # 重复岗位跳过计数（前置查重命中行，实况送前端横幅）
        dup_n = count_duplicate_skip(line)
        if dup_n and skip_state is not None:
            skip_state["n"] += dup_n
            if on_skip:
                on_skip(skip_state["n"])

        # 捕获搜索总数（分母）协议行
        if "搜索总数" in line and "个" in line:
            try:
                search_total = int(line.split("搜索总数", 1)[1].split("个", 1)[0].strip())
            except Exception:
                pass

        # 逐行捕获入库成功的标志
        if "[抓取成功]" in line:
            total_inserted += 1
            if on_page_done:
                on_page_done(total_inserted, current_page)
            # 一旦达标，直接强制掐断子进程，不再继续当前页面的多余下载
            if total_inserted >= target_jobs:
                print(f"\n>> 🎉 目标达成！累计已入库 {total_inserted} 个岗位 (目标: {target_jobs})。程序停止下钻。")
                _safe_terminate(process)
                terminated_by_controller = True
                break

        # 结构化底部/失败哨兵（唯一判定来源，勿再加人类文案子串）
        if "[[HIT_BOTTOM]]" in line:
            hit_bottom = True
        if "[[PAGE_LOAD_FAILED]]" in line:
            page_load_failed = True

    process.wait()
    return total_inserted, hit_bottom, search_total, terminated_by_controller, page_load_failed

def run_task(keyword, city, start_page, target_jobs, salary, on_page_done=None, on_skip=None,
             ledger_keyword=None, ledger_city=None, ledger_salary=None, result_meta=None):
    """51job 动态目标调度：从 start_page 起翻页，直到达到目标入库数或到底。

    返回 (total_inserted, last_touched)：last_touched 为本轮最后触碰的页码
    （该页可能因抓满目标/急停未扫完），供续抓回写，下次从该页重爬兜底。
    """
    if int(target_jobs or 0) <= 0:
        # 0/负目标不是一次抓取轮次：不回报台账，避免连续空跑被误判抓尽
        return 0, None
    crawler_path = os.path.join(CURRENT_DIR, "51job_collector.py")

    total_inserted = 0
    current_page = start_page
    last_touched = start_page - 1  # 尚未处理任何页；一页处理完才记账，急停不虚报
    search_total = 0
    hit_bottom_any = False
    page_load_failed_any = False
    stale_cursor = False
    fatal = False
    fail_reason = None  # 失败原因（供指挥中心弹窗/飞书通知下发）：手动急刹不产生失败通知
    skip_state = {"n": 0}  # 本轮重复跳过累计（可变盒跨页累加，on_skip 实况上报）
    global GLOBAL_STOP_FLAG
    
    while total_inserted < target_jobs:
        # 🌟 主循环（翻页循环）首部急刹车检查
        if GLOBAL_STOP_FLAG:
            print("🛑 [51job 急刹车触发] 收到全局中断信号，立即终止当前翻页循环！")
            break
        print(f"\n{'=' * 60}")
        print(f"🎯 进度: 已入库 {total_inserted}/{target_jobs} 个 | 正在执行: 第 {current_page} 页")
        print(f"📌 条件: 平台=51job | 职位={keyword} | 城市={city} | 薪资={salary}")

        cmd = _build_crawler_cmd(
            crawler_path, current_page, keyword, city, salary,
            remaining=target_jobs - total_inserted,
        )

        # 🌟 核心修复：构造环境变量，将项目根目录加入 PYTHONPATH
        my_env = os.environ.copy()
        my_env["PYTHONPATH"] = PROJECT_ROOT  # PROJECT_ROOT 已经是 backend 的上一级或本身，确保指向包含 app 目录的路径
        my_env["PYTHONIOENCODING"] = "utf-8"

        process = popen_hidden(
            cmd,
            cwd=CURRENT_DIR,
            env=my_env, # 🌟 注入环境变量
            stdout=subprocess.PIPE, 
            stderr=subprocess.STDOUT,
            text=True, 
            encoding='utf-8',
            errors='replace'
        )
        
        total_inserted, hit_bottom, page_search_total, terminated_by_controller, page_load_failed = _process_crawler_output(
            process, target_jobs, total_inserted, current_page, on_page_done, skip_state, on_skip
        )
        hit_bottom_any = hit_bottom_any or hit_bottom
        page_load_failed_any = page_load_failed_any or page_load_failed

        # 跨进程端口锁被另一个 JobHunter 实例持有：协调性跳过，不是环境故障。
        # 本轮没真正跑，success=False，避免连续跳过被误判成「连续 0 新增」。
        if process.returncode == PORT_LOCK_BUSY_EXIT_CODE:
            print("\n⏳ [调度器] 51job 浏览器端口正被占用（本进程或另一个 JobHunter 实例），本轮抓取跳过（非环境故障）")
            fatal = True
            fail_reason = "浏览器端口被占用（另一个 JobHunter 实例在使用），本轮跳过"
            break

        # 页面加载失败（超时/风控/DOM 变化）：不是平台到底，不写抓尽。
        # 非首页失败同时标记 stale_cursor，下一轮强制从第 1 页重开（避免在越界页
        # 死循环；代价是可能多扫已抓过的页，由判重兜底）。
        if page_load_failed:
            print("\n>> 🛑 [调度器] 本页加载失败（超时/风控），本轮按失败处理，不推进续抓游标。")
            fatal = True
            fail_reason = "页面加载失败（超时/风控或页面结构变化），本轮按失败处理"
            if current_page > 1:
                stale_cursor = True
            break

        # 🌟 环境性失败熔断（2026-10-07）：采集器非 0 退出（守卫拒绝等环境故障）时
        # 终止整轮翻页——继续派页只会逐页复现同一故障并白烧翻页休眠。
        # 2026-10-30：本函数主动 SIGTERM（达标收工 / 用户急刹）的 -15 是正常收工，
        # 用 terminated_by_controller 区分；只有非控制方终止且非 0 退出才是真故障。
        if process.returncode not in (0, None) and not terminated_by_controller:
            print(f"\n>> 🛑 [调度器] 采集器退出（退出码: {process.returncode}），本轮翻页终止。")
            fatal = True
            fail_reason = f"采集器异常退出（退出码 {process.returncode}）"
            break

        if terminated_by_controller:
            # 达标或用户急刹：保留本页已入库结果，退出翻页循环。
            # 用户急刹要标记 success=False；达标收工保持 success=True。
            last_touched = current_page
            if page_search_total > 0:
                search_total = page_search_total
            if GLOBAL_STOP_FLAG:
                fatal = True
            break

        last_touched = current_page  # 本页已处理完，记账（是否扫满未知，续抓时重爬兜底）
        if page_search_total > 0:
            search_total = page_search_total

        # 🌟 本页结束后再检一次急刹车，避免继续进入 countdown_sleep
        if GLOBAL_STOP_FLAG:
            print("🛑 [51job 急刹车触发] 当前页处理完毕，根据中断信号退出翻页循环。")
            fatal = True
            break
        
        if hit_bottom and current_page > 1 and total_inserted == 0:
            # 从非首页触发到底，且本轮 0 入库：大概率是续抓游标越界（历史污染/搜索
            # 结果缩水），不是真的抓尽。不标记 hit_bottom，游标重置为 0，下一轮从
            # 第 1 页重开；本轮保持 success=True（确实跑完了，只是没有数据）。
            print("\n>> ♻️ 从非首页触发到底且 0 入库，疑似续抓游标越界；本轮不标记抓尽，下轮从第 1 页重开。")
            stale_cursor = True
            hit_bottom_any = False
            last_touched = 0
            break

        if hit_bottom:
            print("\n>> ⚠️ 触发熔断：51job 已无更多相关数据。")
            break
            
        if total_inserted >= target_jobs:
            break
            
        current_page += 1
        countdown_sleep(random.randint(60, 180))  # 翻页休眠：随机 1~3 分钟（2026-08-11 用户要求调快，原 250~400s）

    print(f"\n🏁 本轮指令已全部执行完毕！最终入库: {total_inserted} | 最后触碰页码: {last_touched}")

    # 回写「条件×平台」进度台账：使用原始条件（不是平台映射后的薪资/关键词）
    success = (not fatal) and not GLOBAL_STOP_FLAG
    try:
        from app.session.scrape_sessions import report_condition_round
        report_condition_round(
            ledger_keyword if ledger_keyword is not None else keyword,
            ledger_city if ledger_city is not None else (city or ""),
            ledger_salary if ledger_salary is not None else salary,
            "51job",
            total_inserted,
            search_total or None,
            hit_bottom=hit_bottom_any,
            success=success,
        )
    except Exception as e:
        print(f"⚠️ 51job 条件台账回写失败: {e}")

    if result_meta is not None:
        result_meta.update({
            "inserted": int(total_inserted or 0),
            "search_total": int(search_total or 0),
            "hit_bottom": bool(hit_bottom_any),
            "last_page": 0 if (hit_bottom_any or stale_cursor or page_load_failed_any) else int(last_touched or 0),
            "stale_cursor": bool(stale_cursor),
            "page_load_failed": bool(page_load_failed_any),
            "success": bool(success),
            "fail_reason": fail_reason,
        })

    return total_inserted, last_touched

def main():
    print("=" * 60)
    print("💼 51job 动态目标调度大管家 已启动")
    print("   示例：帮我搜广州的数据分析，15-20K，抓50个，从第1页开始")
    print("=" * 60)

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
            tj = int(intent.get("target_jobs", 50))

            if not kw: continue
            
            print(f">> 确认任务: 关键词={kw}, 城市={ct}, 薪资={sl}, 起始页={sp}, 目标={tj}")
            run_task(kw, ct, sp, tj, sl)
            
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"!! 异常: {e}")

# ==================== 🤖 飞书聊天框接入：51job 抓取专属控制层 ====================

# 🌟 从新建立的飞书业务服务层导入消息推送
from app.services.feishu_service import send_feishu_message


def run_scraping_task(keyword: str, city: str, salary: str, start_page: int = 1, target_jobs: int = 50,
                      on_page_done=None, on_skip=None, ledger_keyword=None, ledger_city=None,
                      ledger_salary=None, result_meta=None) -> tuple:
    """51job 简化版抓取入口：从 start_page 起抓到目标入库数 target_jobs。

    薄包装层，与 CLI 用的 run_task 共享同一份底层执行逻辑（while 循环 + Popen），
    返回 (total_inserted, last_touched)：入库数 + 最后触碰页码（供续抓回写）。
    """
    print(f"   [run_scraping_task/51job] keyword={keyword}, city={city}, salary={salary}, start_page={start_page}, target={target_jobs}")
    total, last_touched = run_task(
        keyword, city, int(start_page), int(target_jobs), salary or "不限",
        on_page_done=on_page_done, on_skip=on_skip,
        ledger_keyword=ledger_keyword, ledger_city=ledger_city,
        ledger_salary=ledger_salary, result_meta=result_meta,
    )
    return int(total or 0), int(last_touched or 0)


async def _notify_feishu_51job(chat_id: str, message: str):
    """仅在有效 chat_id 时推送飞书，否则只打印日志，防止虚假 chat_id 触发 HTTP 400。"""
    if chat_id and chat_id not in ("", "agent_cli"):
        await asyncio.to_thread(send_feishu_message, chat_id, message, "chat_id")
    else:
        print(f"📢 [控制台模式] {message}")


async def process_51job_scraping_request(chat_id: str, city: str, keyword: str, salary: str, start_page: int = 1,
                                         target_jobs: int = 50, sse_task_id: str = None,
                                         ledger_keyword: str | None = None, ledger_city: str | None = None,
                                         ledger_salary: str | None = None, result_meta: dict | None = None):
    print(f"\n{'='*50}")
    print(f"🕵️ [DEBUG] 飞书请求已进入 51job 执行中枢！参数: 城市={city}, 岗位={keyword}, 薪资={salary}, start_page={start_page}, target_jobs={target_jobs}")

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
        target_jobs = 50

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

        # 🌟 安装活动心跳：翻页大休眠 / 逐岗位深度潜行等长静默期间至多每 30s 报一次平安，
        # 防全链路转发协程把静默误判为任务结束而并发二次派发
        _hb_state = {"last": 0.0}

        def _heartbeat_hook():
            now = time.monotonic()
            if now - _hb_state["last"] >= 30:
                _hb_state["last"] = now
                _send_sse_event({"type": "heartbeat"}, from_worker_thread=True)

        set_heartbeat_hook(_heartbeat_hook)

        await _notify_feishu_51job(
            chat_id,
            (
                f"✅ 收到指令！正在启动 [51job/前程无忧] 爬虫引擎...\n"
                f"📍 城市：{city}\n"
                f"🎯 岗位：{keyword}\n"
                f"💰 薪资：{salary}\n"
                f"📄 起始页码：第 {start_page} 页\n"
                f"📦 目标数量：{target_jobs} 个"
            )
        )

        _send_sse_event({
            "type": "progress",
            "total_inserted": 0,
            "target_jobs": target_jobs,
            "current_page": start_page,
        })

        latest_page = start_page
        last_touched = None  # 本轮最后触碰页码；异常路径保持 None → 上层兜底回写 start_page

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

        # 调用底层逻辑
        total_inserted, last_touched = await asyncio.to_thread(
            run_scraping_task,
            keyword, city, salary, start_page, target_jobs, _sse_progress,
            lambda skipped_count: _send_sse_event(
                {"type": "scrape_progress", "skipped": skipped_count},
                from_worker_thread=True,
            ),  # on_skip 回调：重复跳过实况（工作线程 → call_soon_threadsafe 调度回主循环）
            ledger_keyword=ledger_keyword,
            ledger_city=ledger_city,
            ledger_salary=ledger_salary,
            result_meta=result_meta,
        )
        print(f"🕵️ [DEBUG] 51job 抓取逻辑执行完毕，返回入库数: {total_inserted}，最后触碰页码: {last_touched}")

        # 推送最终进度 + 完成事件
        _send_sse_event({
            "type": "progress",
            "total_inserted": total_inserted,
            "target_jobs": target_jobs,
            "current_page": latest_page,
        })
        _send_sse_event({"type": "complete"})

        await _notify_feishu_51job(
            chat_id,
            f"🎉 51job 抓取任务结束！\n本次共成功将 {total_inserted} 个【{city}-{keyword}】岗位存入 SQLite 数据库！"
        )
    except Exception as e:
        print(f"⚠️ 51job 抓取异常: {e}")
        import traceback
        traceback.print_exc()
        try:
            await _notify_feishu_51job(
                chat_id,
                f"❌ 51job 抓取中断崩溃，错误日志: {e}"
            )
            _send_sse_event({"type": "error", "message": str(e)})
        except Exception:
            pass
    finally:
        set_heartbeat_hook(None)  # 🌟 卸载心跳，避免残留钩子串到下一轮/CLI 模式
        # 返回最后触碰页码供编排层续抓回写（下次从该页重爬，防末页未抓满；异常时为 None）
        return last_touched


if __name__ == "__main__":
    main()