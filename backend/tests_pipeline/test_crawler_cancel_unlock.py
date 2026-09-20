"""回归测试：/cancel 终止后平台并发锁即时解除（Bug 4）+ 小红书关键词适配（中1）。

事故模型（修复前）：
  浏览器/子进程 hang 死 → 爬虫协程永不结束 → _platform_running_tasks 只在
  finally 里清除（永不执行）→ 该平台所有后续 /run 全部 409，只能重启后端解锁。

修复后契约：
  - /cancel 对爬虫任务：置 stop flag 后主动 pop 该平台的锁登记（仅当登记的
    task_id 与被终止的一致，防止误清并发新任务的锁）
  - /run 小红书：关键词自动补「招聘」后缀（对齐统一分发 adapt_keyword 行为）
"""
from unittest.mock import patch, AsyncMock

from fastapi.testclient import TestClient

from app.main import app
from app.api.routes import crawlers

client = TestClient(app)


def _setup_running(platform: str, task_id: str):
    crawlers._platform_running_tasks[platform] = task_id


def test_cancel_spider_unlocks_platform():
    """终止爬虫任务后，该平台的并发互斥登记被主动清除，后续可立即重新发起。"""
    _setup_running("boss", "spider_boss_deadbeef")
    try:
        with patch.object(crawlers, "stop_platform", return_value=True) as mock_stop:
            res = client.post("/api/v1/crawlers/cancel/spider_boss_deadbeef")
        assert res.status_code == 200
        mock_stop.assert_called_once_with("boss")
        # 核心断言：锁登记已解除
        assert "boss" not in crawlers._platform_running_tasks
    finally:
        crawlers._platform_running_tasks.pop("boss", None)


def test_cancel_does_not_release_newer_task_lock():
    """防误伤：终止旧 task_id 时，同平台新登记任务的锁不得被清掉。"""
    _setup_running("liepin", "spider_liepin_new1234")
    try:
        with patch.object(crawlers, "stop_platform", return_value=True):
            # 终止的是旧的（不在登记表中的）任务号
            res = client.post("/api/v1/crawlers/cancel/spider_liepin_old5678")
        assert res.status_code == 200
        # 新任务的锁保留
        assert crawlers._platform_running_tasks.get("liepin") == "spider_liepin_new1234"
    finally:
        crawlers._platform_running_tasks.pop("liepin", None)


def test_cancel_clean_task_does_not_touch_platform_locks():
    """清洗任务（clean_* 前缀）走 step1 分流，不应触碰平台爬虫锁。"""
    _setup_running("boss", "spider_boss_alive99")
    try:
        with patch("job_processor.step1_rule_filter.set_stop_flag") as mock_flag:
            res = client.post("/api/v1/crawlers/cancel/clean_global_aabbccdd")
        assert res.status_code == 200
        mock_flag.assert_called_once_with(True)
        # 爬虫平台锁原封不动
        assert crawlers._platform_running_tasks.get("boss") == "spider_boss_alive99"
    finally:
        crawlers._platform_running_tasks.pop("boss", None)


def test_run_xiaohongshu_appends_recruit_suffix():
    """小红书 /run：裸关键词自动补「招聘」后缀（防抓回全是生活贴）。"""
    from app.session.salary_mapper import adapt_keyword

    # 先验证 adapt_keyword 单元行为
    assert adapt_keyword("数据分析师", "xiaohongshu") == "数据分析师招聘"
    assert adapt_keyword("数据分析师招聘", "xiaohongshu") == "数据分析师招聘"  # 不重复加

    # 再验证 /run 路由接线：传给 _run_xhs_task 的关键词已适配
    captured = {}

    async def fake_xhs_task(task_id, keyword, target_jobs, sort_by):
        captured["keyword"] = keyword

    with patch.object(crawlers, "_run_xhs_task", side_effect=fake_xhs_task):
        with patch("app.tasks.state.task_queues") as fake_queues:
            fake_queues.__setitem__ = lambda *a, **k: None
            res = client.post("/api/v1/crawlers/run", json={
                "platform": "xiaohongshu",
                "keyword": "数据分析师",
                "target_jobs": 10,
                "sort_by": "general",
            })
    assert res.status_code == 200
    assert captured.get("keyword") == "数据分析师招聘"


def test_run_boss_keyword_not_mutated():
    """对照面：非小红书平台关键词原样透传。"""
    captured = {}

    async def fake_boss_task(task_id, city, keyword, salary, start_page, target_jobs):
        captured["keyword"] = keyword

    with patch.object(crawlers, "_run_boss_task", side_effect=fake_boss_task):
        with patch("app.tasks.state.task_queues") as fake_queues:
            fake_queues.__setitem__ = lambda *a, **k: None
            res = client.post("/api/v1/crawlers/run", json={
                "platform": "boss",
                "keyword": "产品经理",
                "city": "北京",
                "target_jobs": 10,
            })
    assert res.status_code == 200
    assert captured.get("keyword") == "产品经理"
