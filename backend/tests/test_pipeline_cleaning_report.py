"""
全自动链路清洗统计、战报卡片构建与疑似重复去重透传测试。
验证清洗状态白名单（含「已同步」）、精投占比分母计算、去重拦截注记及异常告警。
"""
import ast
import inspect
import os
import sqlite3
import tempfile
from unittest.mock import AsyncMock, patch
import pytest
from datetime import datetime

from app.automation.pipeline_report import (
    collect_cleaning_stats,
    build_pipeline_report,
    send_pipeline_master_card,
)
from app.services.pipeline_card_builders import build_master_pipeline_card


@pytest.fixture
def temp_raw_db():
    """创建隔离的临时 SQLite 数据库用于测试 raw_jobs 清洗统计"""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    with sqlite3.connect(path) as conn:
        conn.execute("""
            CREATE TABLE raw_jobs (
                rowid INTEGER PRIMARY KEY AUTOINCREMENT,
                platform TEXT,
                job_title TEXT,
                company_name TEXT,
                salary TEXT,
                city TEXT,
                education_req TEXT,
                experience_req TEXT,
                jd_text TEXT,
                job_link TEXT,
                process_status TEXT,
                reject_reason TEXT,
                feishu_record_id TEXT
            )
        """)
        conn.commit()
    yield path
    if os.path.exists(path):
        os.remove(path)


def test_collect_cleaning_stats_production_incident_case(temp_raw_db):
    """
    还原生产故障场景：
    抓取 20 条，AI清洗拦截 2 条 (ai清洗淘汰)，同步至飞书 18 条 (已同步)。
    期望：
    - total = 20
    - hard_passed = 20 (无规则淘汰)
    - hard_rejected = 0
    - ai_passed = 18 (包含「已同步」状态)
    - ai_rejected = 2
    - pending_ai = 0
    - 满足恒等式 hard_passed (20) == ai_passed (18) + ai_rejected (2)
    """
    with sqlite3.connect(temp_raw_db) as conn:
        # 插入 2 条 ai清洗淘汰
        for _ in range(2):
            conn.execute(
                "INSERT INTO raw_jobs (platform, job_title, company_name, process_status, reject_reason) "
                "VALUES (?, ?, ?, ?, ?)",
                ("boss", "产品经理", "测试公司", "ai清洗淘汰", "AI排雷")
            )
        # 插入 18 条 已同步
        for i in range(18):
            conn.execute(
                "INSERT INTO raw_jobs (platform, job_title, company_name, process_status, feishu_record_id) "
                "VALUES (?, ?, ?, ?, ?)",
                ("boss", "产品经理", "测试公司", "已同步", f"rec_test_{i}")
            )
        conn.commit()

    stats = collect_cleaning_stats(temp_raw_db, start_rowid=0)

    assert stats["total"] == 20
    assert stats["hard_passed"] == 20
    assert stats["hard_rejected"] == 0
    assert stats["ai_passed"] == 18
    assert stats["ai_rejected"] == 2
    assert stats["pending_ai"] == 0
    assert stats["untracked"] == 0


def test_collect_cleaning_stats_mixed_statuses(temp_raw_db):
    """
    测试混合多状态生命周期：
    - 1 条 清洗淘汰
    - 2 条 ai清洗淘汰
    - 3 条 待AI初筛
    - 4 条 已同步
    - 2 条 待推送至飞书
    - 1 条 已推送飞书
    - 总计: 13 条
    期望：
    - total = 13
    - hard_rejected = 1
    - hard_passed = 12
    - ai_rejected = 2
    - pending_ai = 3
    - ai_passed = 7 (4+2+1)
    - 严格恒等式: 12 == 7 + 2 + 3
    """
    with sqlite3.connect(temp_raw_db) as conn:
        conn.execute("INSERT INTO raw_jobs (process_status) VALUES ('清洗淘汰')")
        for _ in range(2):
            conn.execute("INSERT INTO raw_jobs (process_status) VALUES ('ai清洗淘汰')")
        for _ in range(3):
            conn.execute("INSERT INTO raw_jobs (process_status) VALUES ('待AI初筛')")
        for _ in range(4):
            conn.execute("INSERT INTO raw_jobs (process_status) VALUES ('已同步')")
        for _ in range(2):
            conn.execute("INSERT INTO raw_jobs (process_status) VALUES ('待推送至飞书')")
        conn.execute("INSERT INTO raw_jobs (process_status) VALUES ('已推送飞书')")
        conn.commit()

    stats = collect_cleaning_stats(temp_raw_db, start_rowid=0)

    assert stats["total"] == 13
    assert stats["hard_rejected"] == 1
    assert stats["hard_passed"] == 12
    assert stats["ai_rejected"] == 2
    assert stats["pending_ai"] == 3
    assert stats["ai_passed"] == 7
    assert stats["hard_passed"] == stats["ai_passed"] + stats["ai_rejected"] + stats["pending_ai"]
    assert stats["untracked"] == 0


def test_collect_cleaning_stats_failure_fallback():
    """
    测试数据库损坏或无法访问时的容错兜底：
    collect_cleaning_stats 必须返回空字典 {}，使上层 send_pipeline_master_card 的 fallback 兜底生效。
    """
    stats = collect_cleaning_stats("/non_existent_db_path/123.db", start_rowid=0)
    assert stats == {}


def test_build_master_pipeline_card_with_dedup_and_clean():
    """
    验证卡片构建逻辑：
    1. 抓取 20 条，硬清洗通过 20 条，AI清洗通过 18 条，拦截 2 条；
    2. 疑似重复拦截 1 条 (dedup_count=1)；
    3. 评估完成 17 条：A级 4 条，B级 2 条，C级 5 条，D/F级 6 条；
    4. 精投占比分子 = 4+2 = 6；分母 = 17；精投率 = 6/17 ≈ 35.3% -> 35%；
    5. 初评模块必须展示「疑似重复：1 条」，且不应该展示「⚠️ 评估异常中断」。
    """
    card = build_master_pipeline_card(
        task_time="2026-09-17 10:00",
        duration_mins=28,
        total_scraped=20,
        hard_passed=20,
        hard_rejected=0,
        ai_passed=18,
        ai_rejected=2,
        precision_cnt=6,
        channel_counts={"BOSS直聘": 20},
        grade_counts={"A": 4, "B": 2, "C": 5, "D/F": 6},
        mass_review_cnt=5,
        other_review_cnt=6,
        dedup_count=1,
    )

    card_str = str(card)

    # 验证关键指标准确渲染
    assert "硬清洗通过" in card_str
    assert "AI清洗通过" in card_str
    assert "**20 条**" in card_str
    assert "**18 条**" in card_str
    # 验证精投占比正确（35%，非除零 fallback 50%）
    assert "精投占比 35%" in card_str
    # 验证初评结果完成 17 条
    assert "共 17 条进入评估" in card_str
    # 验证去重拦截注记
    assert "疑似重复" in card_str and "1" in card_str
    # 验证无异常中断标记
    assert "⚠️ 评估异常中断" not in card_str


def test_build_master_pipeline_card_anomaly_detection():
    """
    测试异常中断感知：
    AI通过 18 条，去重 1 条，但实际评估只有 10 条（缺少 7 条）；
    卡片必须高亮提示「⚠️ 评估异常中断：7 条」。
    """
    card = build_master_pipeline_card(
        task_time="2026-09-17 10:00",
        duration_mins=28,
        total_scraped=20,
        hard_passed=20,
        hard_rejected=0,
        ai_passed=18,
        ai_rejected=2,
        precision_cnt=4,
        channel_counts={"BOSS直聘": 20},
        grade_counts={"A": 4, "B": 2, "C": 2, "D/F": 2},  # 评估总数 10 条
        mass_review_cnt=2,
        other_review_cnt=2,
        dedup_count=1,
    )

    card_str = str(card)
    assert "⚠️ 评估异常中断" in card_str
    assert "7" in card_str


def test_build_pipeline_report_text():
    """
    测试纯文本战报生成中包含疑似重复拦截统计。
    """
    started_at = datetime(2026, 9, 17, 10, 0, 0)
    scrape_counts = {"BOSS直聘": 20}
    cleaning = {
        "total": 20,
        "hard_passed": 20,
        "hard_rejected": 0,
        "ai_passed": 18,
        "ai_rejected": 2,
    }
    job_results = [
        {"decision": "APPROVE", "match_grade": "A", "grade": "A", "company_name": "A司", "job_name": "PM"}
        for _ in range(17)
    ]

    text = build_pipeline_report(
        started_at=started_at,
        scrape_counts=scrape_counts,
        disabled_platforms=[],
        platform_cn={},
        cleaning=cleaning,
        synced_count=18,
        job_results=job_results,
        aborted=False,
        dedup_count=1,
    )

    assert "疑似重复：拦截 1 条" in text
    assert "处理 20 条 → 通过 18 条" in text
    assert "硬规则拦截 0 · AI拦截 2" in text


@pytest.mark.asyncio
async def test_send_pipeline_master_card_dedup_passthrough():
    """
    测试 send_pipeline_master_card 端到端透传 dedup_count。
    Mock 发送底层，验证构造出的卡片 content 中精准包含去重数据。
    """
    started_at = datetime(2026, 9, 17, 10, 0, 0)
    scrape_counts = {"BOSS直聘": 20}
    cleaning = {
        "total": 20,
        "hard_passed": 20,
        "hard_rejected": 0,
        "ai_passed": 18,
        "ai_rejected": 2,
    }
    job_results = [
        {"decision": "APPROVE", "match_grade": "A", "grade": "A", "company_name": "A司", "job_name": "PM"}
        for _ in range(17)
    ]

    with patch("app.services.report_feishu._get_receive_id", return_value="oc_test_chat_id"), \
         patch("app.core.feishu_messaging.send_feishu_card", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = True

        ok = await send_pipeline_master_card(
            started_at=started_at,
            scrape_counts=scrape_counts,
            cleaning=cleaning,
            job_results=job_results,
            dedup_count=3,
        )

        assert ok is True
        mock_send.assert_called_once()
        sent_card = mock_send.call_args[1]["card_content"]
        sent_card_str = str(sent_card)
        assert "疑似重复" in sent_card_str
        assert "3" in sent_card_str


def test_orchestrator_send_task_report_ast_verification():
    """
    静态 AST 源码级断言：
    验证 pipeline_orchestrator.py 内部定义的 _send_task_report 函数：
    1. 必须接受 dedup_count 参数（默认值为 0）；
    2. 函数体内调用 build_pipeline_report 时显式传入 dedup_count=dedup_count；
    3. 函数体内调用 send_pipeline_master_card 时显式传入 dedup_count=dedup_count。
    """
    import app.automation.pipeline_orchestrator as orch_mod
    src = inspect.getsource(orch_mod)
    tree = ast.parse(src)

    found_func = False
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_send_task_report":
            found_func = True
            # 验证参数签名
            arg_names = [a.arg for a in node.args.args]
            assert "job_results" in arg_names
            assert "dedup_count" in arg_names

            # 验证函数体内部透传了 dedup_count
            calls = [n for n in ast.walk(node) if isinstance(n, ast.Call)]
            call_func_names = []
            for c in calls:
                if isinstance(c.func, ast.Attribute):
                    call_func_names.append(c.func.attr)
                    kw_names = [k.arg for k in c.keywords if k.arg]
                    if c.func.attr in ("build_pipeline_report", "send_pipeline_master_card"):
                        assert "dedup_count" in kw_names, f"{c.func.attr} 缺少 dedup_count 关键字参数"

            assert "build_pipeline_report" in call_func_names
            assert "send_pipeline_master_card" in call_func_names

    assert found_func is True, "未在 pipeline_orchestrator.py 中找到 _send_task_report 函数定义！"
