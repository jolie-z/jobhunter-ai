"""回归测试：清洗终止信号不被回收站放行 / step2 并发路径吞掉（Bug 1）。

事故模型（修复前）：
  1. 用户在联合清洗中途点击「终止」→ step1.GLOBAL_STOP_FLAG = True
  2. 回收站放行误杀岗位触发 _run_unreject_and_evaluate → step2 入口 set_stop_flag(False)
  3. 终止信号被吞，AI 排雷继续烧 Token

修复后契约：
  - step2.sync_sqlite_to_feishu 绝不重置急刹 flag（源码级断言 + 行为级断言）
  - 联合清洗收到终止信号后跳过 Step 2 飞书推送
"""
import asyncio
import ast
import inspect
import sqlite3

import pytest
from unittest.mock import patch, AsyncMock

from job_processor import step1_rule_filter, step2_sync_feishu
from app.api.routes import processor


def test_step2_source_never_resets_stop_flag():
    """源码级防线：step2 的可执行代码禁止调用 set_stop_flag（docstring 中的说明除外）。"""
    import ast
    tree = ast.parse(inspect.getsource(step2_sync_feishu))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            name = getattr(fn, "id", getattr(fn, "attr", None)
                           if not isinstance(fn, ast.Name) else fn.id)
            if isinstance(fn, ast.Name):
                name = fn.id
            elif isinstance(fn, ast.Attribute):
                name = fn.attr
            else:
                continue
            assert name != "set_stop_flag", "step2_sync_feishu 可执行代码中出现 set_stop_flag 调用"


@pytest.mark.asyncio
async def test_unreject_push_does_not_swallow_abort_signal(tmp_path):
    """行为级：回收站放行推送与终止信号并发时，flag 保持 True 不被清零。"""
    db_file = str(tmp_path / "unreject_race.db")
    with sqlite3.connect(db_file) as conn:
        conn.execute("""
            CREATE TABLE raw_jobs (
                job_link TEXT PRIMARY KEY, job_title TEXT, company_name TEXT, city TEXT,
                jd_text TEXT, salary TEXT, process_status TEXT, reject_reason TEXT,
                is_synced INTEGER DEFAULT 0, feishu_record_id TEXT DEFAULT ''
            )
        """)
        conn.execute(
            "INSERT INTO raw_jobs (job_link, job_title, company_name, city, process_status) "
            "VALUES ('https://zhaopin.com/job/999', '测试岗', '测试公司', '深圳', '待推送至飞书')"
        )
        conn.commit()

    # 1) 模拟用户已在其它任务中点了终止
    step1_rule_filter.set_stop_flag(True)

    # 2) 回收站放行路径触发定向推送（应持 _global_clean_lock 但不重置 flag）
    with patch.object(processor, "DB_PATH", db_file), \
         patch("app.automation.full_auto.run_single_job_pipeline_async", new_callable=AsyncMock):
        # 放行的飞书查重返回 False（不存在）以走完整推送路径；推送单条 mock 掉避免外呼
        with patch.object(step2_sync_feishu, "check_job_exists", return_value=False), \
             patch.object(step2_sync_feishu, "push_single_record_to_feishu", return_value="rec_x"), \
             patch.object(step2_sync_feishu, "get_tenant_access_token", return_value="fake_token"):
            await processor._run_unreject_and_evaluate(
                task_id="unreject_race_test",
                row_id=None,
                job_link="https://zhaopin.com/job/999",
            )

    # 3) 核心断言：终止信号依然存活（修复前会被 step2 入口的 set_stop_flag(False) 吞掉）
    assert step1_rule_filter.get_stop_flag() is True

    step1_rule_filter.set_stop_flag(False)  # 清理，避免污染其它用例


@pytest.mark.asyncio
async def test_global_pipeline_skips_step2_when_aborted():
    """联合清洗：Step 1 终止后不得调用 Step 2 推送（修复前无条件推送）。"""
    step1_rule_filter.set_stop_flag(False)

    async def fake_step1(sse_task_id=None, limit=None, **kw):
        # Step 1 结束时用户点了终止
        step1_rule_filter.set_stop_flag(True)
        return ["https://example.com/job/1"]

    with patch.object(step1_rule_filter, "_async_run_pipeline", side_effect=fake_step1), \
         patch("job_processor.step2_sync_feishu.sync_sqlite_to_feishu") as mock_sync:
        await processor._run_global_pipeline(task_id="clean_global_aborttest", limit=5)

    mock_sync.assert_not_called()
    step1_rule_filter.set_stop_flag(False)


@pytest.mark.asyncio
async def test_global_pipeline_runs_step2_when_not_aborted():
    """对照面：未终止时 Step 2 正常执行（防止修复矫枉过正）。"""
    step1_rule_filter.set_stop_flag(False)

    with patch.object(step1_rule_filter, "_async_run_pipeline", return_value=["https://example.com/job/2"]) as mock_s1, \
         patch("job_processor.step2_sync_feishu.sync_sqlite_to_feishu", return_value=[]) as mock_sync:
        await processor._run_global_pipeline(task_id="clean_global_oktest", limit=5)

    mock_s1.assert_called_once()
    mock_sync.assert_called_once()
    step1_rule_filter.set_stop_flag(False)
