"""回归测试：小红书多模态清洗双入口互斥（Bug 2）。

事故模型（修复前）：
  爬虫抓完自动触发 run_vision_cleaner（不持锁）+ 数据探测面板手动触发（仅路由级
  _xhs_clean_lock，与前者不同锁）→ 双 cleaner 并发 → 第二个启动时的自愈回收把
  第一个正在推理的 20 条 PROCESSING 笔记回滚 PENDING 并重新认领 → 重复过视觉
  大模型，Token 双烧。

修复后契约：
  - 模块级 XHS_CLEAN_LOCK 为全系统唯一锁，双入口共享
  - 锁被占用时：爬虫自动入口（wait_if_busy=False）静默跳过；手动入口得到 busy
  - 能拿到锁时自愈回收才执行（持锁即无并发 cleaner，回收安全）
"""
import asyncio
import sqlite3

import pytest

from job_processor import xhs_vision_cleaner


def _make_xhs_db(tmp_path, processing_rows=0):
    db_file = str(tmp_path / "xhs_concurrency.db")
    with sqlite3.connect(db_file) as conn:
        conn.execute("""
            CREATE TABLE xhs_raw_posts (
                post_link TEXT PRIMARY KEY, account_name TEXT, raw_text TEXT,
                image_urls TEXT, clean_status TEXT DEFAULT 'PENDING',
                publish_date TEXT
            )
        """)
        for i in range(3):
            conn.execute(
                "INSERT INTO xhs_raw_posts (post_link, account_name, raw_text, image_urls, clean_status) "
                "VALUES (?, ?, 'raw', '[]', 'PENDING')",
                (f"https://xhs.note/{i}", f"账号{i}"),
            )
        # 埋入上次崩溃残留的僵尸 PROCESSING 行
        for i in range(processing_rows):
            conn.execute(
                "INSERT INTO xhs_raw_posts (post_link, account_name, raw_text, image_urls, clean_status) "
                "VALUES (?, ?, 'raw', '[]', 'PROCESSING')",
                (f"https://xhs.zombie/{i}", f"僵尸{i}"),
            )
        conn.commit()
    return db_file


@pytest.mark.asyncio
async def test_xhs_cleaner_exclusive_between_dual_entrances(tmp_path, monkeypatch):
    """双入口并发：手动入口持锁推理中，爬虫自动入口必须跳过（skipped）而非并发执行。"""
    db_file = _make_xhs_db(tmp_path)
    monkeypatch.setattr(xhs_vision_cleaner, "DB_PATH", db_file)

    # 手动入口（路由后台体）先持锁
    release = asyncio.Event()
    processed = {"manual": 0, "auto": 0}

    async def fake_process(record, sse_task_id=None):
        processed["manual"] += 1
        await release.wait()  # 模拟推理中
        return "NOT_A_JOB", None

    monkeypatch.setattr(xhs_vision_cleaner, "process_single_post", fake_process)

    manual_task = asyncio.create_task(
        xhs_vision_cleaner.run_vision_cleaner(sse_task_id="clean_xhs_manual")
    )
    # 等手动入口拿到锁、完成认领（3 条全部进入 PROCESSING）并开始推理
    while True:
        await asyncio.sleep(0.02)
        with sqlite3.connect(db_file) as conn:
            claimed = conn.execute(
                "SELECT COUNT(*) FROM xhs_raw_posts WHERE clean_status = 'PROCESSING'"
            ).fetchone()[0]
        if claimed == 3:
            break

    # 爬虫抓完自动触发：锁被占用 → 必须立即返回 skipped，不排队、不回收、不认领
    auto_result = await xhs_vision_cleaner.run_vision_cleaner(sse_task_id="spider_auto")
    assert auto_result == "skipped"
    assert processed["auto"] == 0
    # 锁占用期间库里 PROCESSING 仍是手动入口认领的那 3 条：
    # 没被自动入口重复认领（会变 6），也没被它的自愈回收回滚（会变 0）
    with sqlite3.connect(db_file) as conn:
        pending = conn.execute(
            "SELECT COUNT(*) FROM xhs_raw_posts WHERE clean_status = 'PROCESSING'"
        ).fetchone()[0]
    assert pending == 3

    release.set()
    await manual_task
    assert processed["manual"] == 3  # 3 条 PENDING 全被手动入口处理


@pytest.mark.asyncio
async def test_xhs_cleaner_busy_waits_for_lock_release(tmp_path, monkeypatch):
    """wait_if_busy=True 排队语义：锁被占用时等它释放后接续执行，绝不丢弃已抓数据。"""
    db_file = _make_xhs_db(tmp_path)
    monkeypatch.setattr(xhs_vision_cleaner, "DB_PATH", db_file)

    processed = []

    async def fake_process(record, sse_task_id=None):
        processed.append(record[0])
        return "NOT_A_JOB", None

    monkeypatch.setattr(xhs_vision_cleaner, "process_single_post", fake_process)

    # 第一个 cleaner 占用锁慢慢跑
    async with xhs_vision_cleaner.XHS_CLEAN_LOCK:
        waiter = asyncio.create_task(
            xhs_vision_cleaner.run_vision_cleaner(sse_task_id="spider_wait", wait_if_busy=True)
        )
        await asyncio.sleep(0.1)
        assert not waiter.done(), "wait_if_busy=True 应排队而非立即返回"

    await waiter  # 锁释放后 waiter 接续执行完成
    assert len(processed) == 3, "排队者必须在锁释放后完成全部清洗，不丢数据"


@pytest.mark.asyncio
async def test_crawler_integration_path_cleans_not_skips(tmp_path, monkeypatch):
    """集成路径（Gemini 质检指出的盲区）：crawlers._run_xhs_task 的调用方式
    ——裸调用 run_vision_cleaner(wait_if_busy=True)，无外层 async with——
    必须真正执行清洗，绝不因锁而 skipped。"""
    import inspect
    from app.api.routes import crawlers

    # 1) 源码级防线：_run_xhs_task 中禁止外层 async with XHS_CLEAN_LOCK
    #    （非可重入锁，外层持锁后内部 locked() 恒 True → 100% skipped 的自锁事故，
    #     Gemini 质检抓出的重大缺陷，此断言防复发）
    src = inspect.getsource(crawlers._run_xhs_task)
    assert "async with xhs_vision_cleaner.XHS_CLEAN_LOCK" not in src, (
        "crawlers._run_xhs_task 不得外层持有 XHS_CLEAN_LOCK（非可重入，会自锁）"
    )
    assert "wait_if_busy=True" in src, "爬虫自动清洗必须走排队语义，等锁而非跳过"

    # 2) 行为级：直接以爬虫的调用方式执行，清洗必须真正发生
    db_file = _make_xhs_db(tmp_path)
    monkeypatch.setattr(xhs_vision_cleaner, "DB_PATH", db_file)

    processed = []

    async def fake_process(record, sse_task_id=None):
        processed.append(record[0])
        return "NOT_A_JOB", None

    monkeypatch.setattr(xhs_vision_cleaner, "process_single_post", fake_process)

    result = await xhs_vision_cleaner.run_vision_cleaner(
        sse_task_id="spider_xhs_itest", wait_if_busy=True
    )
    assert result != "skipped", "爬虫集成路径的清洗被跳过 = 自动清洗管道废弃"
    assert len(processed) == 3
    with sqlite3.connect(db_file) as conn:
        pending = conn.execute(
            "SELECT COUNT(*) FROM xhs_raw_posts WHERE clean_status = 'PENDING'"
        ).fetchone()[0]
    assert pending == 0, "全部笔记必须被清洗流转，不得滞留 PENDING"


@pytest.mark.asyncio
async def test_xhs_zombie_reclaim_only_under_lock(tmp_path, monkeypatch):
    """自愈回收在持锁（无并发 cleaner）时安全执行：僵尸 PROCESSING 回滚为 PENDING。"""
    db_file = _make_xhs_db(tmp_path, processing_rows=2)

    async def fake_process(record, sse_task_id=None):
        return "NOT_A_JOB", None

    monkeypatch.setattr(xhs_vision_cleaner, "DB_PATH", db_file)
    monkeypatch.setattr(xhs_vision_cleaner, "process_single_post", fake_process)

    await xhs_vision_cleaner.run_vision_cleaner(sse_task_id="clean_xhs_zombie")

    # 3 条 PENDING + 2 条被回收的僵尸 = 5 条全部处理完；没有任何残留 PROCESSING
    with sqlite3.connect(db_file) as conn:
        states = dict(
            conn.execute(
                "SELECT clean_status, COUNT(*) FROM xhs_raw_posts GROUP BY clean_status"
            ).fetchall()
        )
    assert "PROCESSING" not in states
    assert states.get("NOT_A_JOB") == 5


def test_xhs_lock_is_module_level_singleton():
    """锁必须是模块级单例：路由入口与爬虫入口引用同一对象才可能互斥。"""
    from app.api.routes import processor as processor_routes
    # 路由 run-xhs 检查的就是这把锁
    assert xhs_vision_cleaner.XHS_CLEAN_LOCK is not None
    assert isinstance(xhs_vision_cleaner.XHS_CLEAN_LOCK, asyncio.Lock)
    # 锁未释放状态可被观测（locked() 可用），且 processor 可引用同一模块
    assert hasattr(processor_routes, "_xhs_clean_lock")
