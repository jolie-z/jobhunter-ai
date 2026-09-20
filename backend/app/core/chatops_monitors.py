"""
ChatOps 后台监控协程 — 抓取完成后自动回报飞书群
"""

import asyncio
import os
import sqlite3

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.path.join(PROJECT_ROOT, "data", "job_hunter.db")


async def _scraping_completion_monitor(
    master_task_id: str,
    sub_task_ids: list[str],
    keyword: str,
    city: str,
    target_jobs: int,
    platform_names: str,
    _main_loop: asyncio.AbstractEventLoop,
    chat_id: str | None,
):
    """后台协程：等待抓取子任务完成，然后汇报结果到飞书群。"""
    from app.services.feishu_service import send_feishu_message
    from app.tasks.state import task_queues

    if not chat_id:
        print("⚠️ [ScrapeMonitor] 无 chat_id，跳过回报")
        return

    print(f"📡 [ScrapeMonitor] 开始监听: {master_task_id} | 子任务: {sub_task_ids}")

    # 记录启动前总量
    try:
        conn = sqlite3.connect(DB_PATH)
        before_count = conn.execute("SELECT COUNT(*) FROM raw_jobs").fetchone()[0]
        conn.close()
    except Exception:
        before_count = 0

    # 等待完成（最多 10 分钟）
    completed: set[str] = set()
    timeout_seconds = 600
    start_time = asyncio.get_event_loop().time()

    while len(completed) < len(sub_task_ids):
        elapsed = asyncio.get_event_loop().time() - start_time
        if elapsed > timeout_seconds:
            await asyncio.to_thread(
                send_feishu_message, chat_id,
                f"⏰ 抓取任务超时（{timeout_seconds//60}分钟），已完成 {len(completed)}/{len(sub_task_ids)} 个平台。",
                "chat_id"
            )
            break

        for tid in sub_task_ids:
            if tid in completed:
                continue
            queue = task_queues.get(tid)
            if not queue:
                continue
            found_end = False
            try:
                while not queue.empty():
                    raw = queue.get_nowait()
                    if '"type": "end"' in raw or '"type":"end"' in raw or '"type": "terminated"' in raw or '"type":"terminated"' in raw:
                        found_end = True
                        break
            except Exception:
                pass
            if found_end:
                completed.add(tid)
                task_queues.pop(tid, None)
                print(f"📡 [ScrapeMonitor] 子任务完成: {tid}")

        if len(completed) < len(sub_task_ids):
            await asyncio.sleep(3)

    # 统计结果
    try:
        conn = sqlite3.connect(DB_PATH)
        total = conn.execute("SELECT COUNT(*) FROM raw_jobs").fetchone()[0]
        conn.close()
        new_count = total - before_count
    except Exception:
        total = 0
        new_count = 0

    # 汇报
    target_str = f"{target_jobs}条" if target_jobs else "不限"
    msg = (
        f"🎉 抓取任务完成！\n"
        f"📋 关键词: {keyword} | 城市: {city} | 目标数量：{target_str} | 成功数量：{new_count}条 | 🖥️ 完成平台: {platform_names}\n"
        f"数据已入库raw_jobs数据表，当前数据总量为{total}条\n"
        f"需要我帮你跑清洗→飞书同步→AI评估吗？"
    )
    await asyncio.to_thread(send_feishu_message, chat_id, msg, "chat_id")
    print(f"📡 [ScrapeMonitor] 结果已汇报: {chat_id}")


def start_scraping_monitor(
    master_task_id: str,
    sub_task_ids: list[str],
    keyword: str,
    city: str,
    target_jobs: int,
    platform_names: str,
    main_loop: asyncio.AbstractEventLoop,
    chat_id: str | None,
):
    """在主事件循环上启动抓取完成监控（非阻塞）。"""
    if main_loop is None:
        print("⚠️ [ScrapeMonitor] 主事件循环不可用，跳过监控")
        return
    asyncio.run_coroutine_threadsafe(
        _scraping_completion_monitor(master_task_id, sub_task_ids, keyword, city, target_jobs, platform_names, main_loop, chat_id),
        main_loop
    )
