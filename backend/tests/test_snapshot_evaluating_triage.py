import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock
from app.automation.snapshot_service import build_jobs_snapshot


@pytest.mark.asyncio
async def test_snapshot_section4_defensive_triage_stopped_pipeline(monkeypatch):
    """验证当流水线停机时，Section 4 依据本地完工证据链（评级、物料）精准分诊，杜绝盲猜 running"""
    from app.automation import run_snapshot as _rs
    from app.services import feishu_service

    # Mock runtime: 停机状态
    monkeypatch.setattr(_rs, "current_runtime", lambda: {
        "started": True,
        "running": False,
        "task_id": "pipeline_test_123",
        "start_rowid": 100,
        "record_ids": ["rec_a", "rec_c", "rec_ef", "rec_incomplete", "rec_waiting_normal"],
    })
    monkeypatch.setattr(_rs, "get_dismissed_job_ids", lambda: set())
    monkeypatch.setattr(_rs, "get_retrying_job_ids", lambda: set())

    # Mock Section 2, 2.3, 2.4, 2.5, 3 返回空，使记录全部落入 Section 4
    monkeypatch.setattr(feishu_service, "get_pending_review_jobs_from_feishu", lambda: [])
    monkeypatch.setattr(feishu_service, "get_manual_rejected_jobs_from_feishu", lambda: [])
    monkeypatch.setattr(feishu_service, "get_failed_jobs_from_feishu", lambda: [])
    monkeypatch.setattr(feishu_service, "get_scheduled_delivery_jobs_from_feishu", lambda: [])
    monkeypatch.setattr(feishu_service, "get_delivered_jobs_from_feishu", lambda limit=5, only_today=True: [])

    records = {
        "rec_a": {
            "fields": {
                "岗位名称": "AI开发工程师",
                "公司名称": "某科技公司",
                "跟进状态": "",  # 空状态
                "综合评级 (A-F)": "A",
                "AI改写JSON": '{"summary": "定制简历"}',
            }
        },
        "rec_c": {
            "fields": {
                "岗位名称": "工作流专员",
                "公司名称": "某电商公司",
                "跟进状态": "新线索",  # 新线索
                "综合评级 (A-F)": "C",
                "打招呼语": "您好，沟通一下",
            }
        },
        "rec_ef": {
            "fields": {
                "岗位名称": "无关岗位",
                "公司名称": "某公司",
                "跟进状态": "",
                "综合评级 (A-F)": "F",
            }
        },
        "rec_incomplete": {
            "fields": {
                "岗位名称": "中断岗位",
                "公司名称": "某半成品公司",
                "跟进状态": "",
                # 无评级
            }
        },
        "rec_waiting_normal": {
            "fields": {
                "岗位名称": "正常待审岗位",
                "公司名称": "某正常公司",
                "跟进状态": "简历人工复核",
                "综合评级 (A-F)": "B",
                "AI改写JSON": '{"summary": "定制简历"}',
            }
        },
    }

    monkeypatch.setattr(
        feishu_service,
        "get_job_record_from_feishu",
        lambda rid, tid: records.get(rid)
    )

    snapshot = await build_jobs_snapshot()
    jobs = {j["job_id"]: j for j in snapshot["data"]}

    # 1. rec_a: A级精投完工，停机时安全归入 waiting（待审批）
    assert "rec_a" in jobs
    assert jobs["rec_a"]["status"] == "waiting"
    assert jobs["rec_a"]["node"] == "manual_review_node"
    assert jobs["rec_a"]["last_action_desc"] == "已生成定制简历，待细审放行"

    # 2. rec_c: C级海投完工，停机时安全归入 waiting（待审批把关，零外发误投风险）
    assert "rec_c" in jobs
    assert jobs["rec_c"]["status"] == "waiting"
    assert jobs["rec_c"]["node"] == "manual_review_node"
    assert jobs["rec_c"]["last_action_desc"] == "海投话术已装配，待人工审批"

    # 3. rec_ef: F级初评淘汰，停机时准确分流至 rejected_auto
    assert "rec_ef" in jobs
    assert jobs["rec_ef"]["status"] == "rejected_auto"
    assert jobs["rec_ef"]["node"] == "clean_rule_rejected"
    assert jobs["rec_ef"]["last_action_desc"] == "初评未达门槛，已自动淘汰"

    # 4. rec_incomplete: 停机但未出评级的半成品，安全归入 error，绝不流向发射池
    assert "rec_incomplete" in jobs
    assert jobs["rec_incomplete"]["status"] == "error"
    assert jobs["rec_incomplete"]["node"] == "error"
    assert jobs["rec_incomplete"]["last_action_desc"] == "流水线已停机，评估未完成"

    # 5. rec_waiting_normal: 显式具备「简历人工复核」，正常归入 waiting
    assert "rec_waiting_normal" in jobs
    assert jobs["rec_waiting_normal"]["status"] == "waiting"
    assert jobs["rec_waiting_normal"]["node"] == "manual_review_node"


@pytest.mark.asyncio
async def test_snapshot_section4_running_pipeline(monkeypatch):
    """验证当流水线在线运行时：仅未出评级的记录维持 running 评估中态；已出评级的记录立即进入对应分流（待审批/淘汰）"""
    from app.automation import run_snapshot as _rs
    from app.services import feishu_service

    # Mock runtime: 在线运行状态
    monkeypatch.setattr(_rs, "current_runtime", lambda: {
        "started": True,
        "running": True,
        "task_id": "pipeline_running_456",
        "start_rowid": 200,
        "record_ids": ["rec_evaluating", "rec_eval_done_a", "rec_eval_done_f"],
    })
    monkeypatch.setattr(_rs, "get_dismissed_job_ids", lambda: set())
    monkeypatch.setattr(_rs, "get_retrying_job_ids", lambda: set())

    monkeypatch.setattr(feishu_service, "get_pending_review_jobs_from_feishu", lambda: [])
    monkeypatch.setattr(feishu_service, "get_manual_rejected_jobs_from_feishu", lambda: [])
    monkeypatch.setattr(feishu_service, "get_failed_jobs_from_feishu", lambda: [])
    monkeypatch.setattr(feishu_service, "get_scheduled_delivery_jobs_from_feishu", lambda: [])
    monkeypatch.setattr(feishu_service, "get_delivered_jobs_from_feishu", lambda limit=5, only_today=True: [])

    records = {
        # 1. 正在评估中且完全未出评级：维持 running 评估中
        "rec_evaluating": {
            "fields": {
                "岗位名称": "正在评估岗位",
                "公司名称": "在途公司",
                "跟进状态": "新线索",
            }
        },
        # 2. 在线期间已出 A 级初评及定制物料：即使跟进状态为新线索/空，也分流至 waiting 待审批
        "rec_eval_done_a": {
            "fields": {
                "岗位名称": "初评已出A级岗位",
                "公司名称": "在途公司A",
                "跟进状态": "新线索",
                "综合评级 (A-F)": "A",
                "AI改写JSON": '{"summary": "已完成改写"}',
            }
        },
        # 3. 在线期间已出 F 级淘汰：即使跟进状态为新线索/空，也分流至 rejected_auto
        "rec_eval_done_f": {
            "fields": {
                "岗位名称": "初评已淘汰岗位",
                "公司名称": "在途公司F",
                "跟进状态": "新线索",
                "综合评级 (A-F)": "F",
            }
        },
    }

    monkeypatch.setattr(
        feishu_service,
        "get_job_record_from_feishu",
        lambda rid, tid: records.get(rid)
    )

    snapshot = await build_jobs_snapshot()
    jobs = {j["job_id"]: j for j in snapshot["data"]}

    # rec_evaluating: 在线且未出评级，展示为 running
    assert "rec_evaluating" in jobs
    assert jobs["rec_evaluating"]["status"] == "running"
    assert jobs["rec_evaluating"]["node"] == "evaluate_node"
    assert jobs["rec_evaluating"]["sub_status"] == "ai_eval"
    assert jobs["rec_evaluating"]["last_action_desc"] == "流水线处理中"

    # rec_eval_done_a: 在线但已出评级，展示为 waiting 待审批
    assert "rec_eval_done_a" in jobs
    assert jobs["rec_eval_done_a"]["status"] == "waiting"
    assert jobs["rec_eval_done_a"]["node"] == "manual_review_node"

    # rec_eval_done_f: 在线但已出淘汰评级，展示为 rejected_auto
    assert "rec_eval_done_f" in jobs
    assert jobs["rec_eval_done_f"]["status"] == "rejected_auto"
    assert jobs["rec_eval_done_f"]["node"] == "clean_rule_rejected"


@pytest.mark.asyncio
async def test_graph_runner_manual_review_breakpoint_persists_feishu(monkeypatch):
    """验证当 LangGraph 遇到 manual_review_node 断点挂起时，正确调用 update_feishu_record 持久化跟进状态"""
    from app.automation import graph_runner
    from app.services import feishu_service

    feishu_calls = []

    def mock_update(rid, updates, tid=None):
        feishu_calls.append((rid, updates))
        return True

    monkeypatch.setattr(feishu_service, "update_feishu_record", mock_update)

    # 构造到达 manual_review_node 断点的 snapshot
    mock_snapshot = MagicMock()
    mock_snapshot.next = ("manual_review_node",)
    mock_snapshot.values = {
        "grade": "B",
        "final_markdown": "# 定制简历",
        "feishu_fields": {"AI改写JSON": "{}"},
    }

    async def empty_async_gen(*args, **kwargs):
        if False:
            yield {}

    mock_pipeline_app = MagicMock()
    mock_pipeline_app.astream = empty_async_gen
    mock_pipeline_app.aget_state = AsyncMock(return_value=mock_snapshot)

    from app.automation import scheduler
    monkeypatch.setattr(scheduler, "pipeline_app", mock_pipeline_app)

    # 运行 _run_single_job_graph
    initial_state = {
        "job_id": "rec_test_bp_123",
        "job_name": "Python专家",
        "company_name": "测试企业",
        "platform": "boss",
        "pipeline_task_id": "test_task_001",
        "stop_at_review": False,
    }
    state_config = {"configurable": {"thread_id": "rec_test_bp_123"}}

    res = await graph_runner._run_single_job_graph(
        initial_state,
        state_config,
        "test_task_001",
    )

    assert res["outcome"] == "waiting"
    # 断言 update_feishu_record 被调用且正确回写「简历人工复核」
    assert len(feishu_calls) == 1
    assert feishu_calls[0] == ("rec_test_bp_123", {"跟进状态": "简历人工复核"})


@pytest.mark.asyncio
async def test_graph_runner_manual_review_breakpoint_timeout_protection(monkeypatch):
    """验证断点回写飞书若网络挂起，5s 超时保护生效，绝不阻塞函数返回"""
    import time
    from app.automation import graph_runner
    from app.services import feishu_service

    def hanging_update(rid, updates, tid=None):
        time.sleep(5.5)  # 模拟网络死锁，稍长于 5.0s 超时阈值
        return True

    monkeypatch.setattr(feishu_service, "update_feishu_record", hanging_update)

    mock_snapshot = MagicMock()
    mock_snapshot.next = ("manual_review_node",)
    mock_snapshot.values = {
        "grade": "C",
        "final_markdown": "",
        "feishu_fields": {},
    }

    async def empty_async_gen(*args, **kwargs):
        if False:
            yield {}

    mock_pipeline_app = MagicMock()
    mock_pipeline_app.astream = empty_async_gen
    mock_pipeline_app.aget_state = AsyncMock(return_value=mock_snapshot)

    from app.automation import scheduler
    monkeypatch.setattr(scheduler, "pipeline_app", mock_pipeline_app)

    initial_state = {
        "job_id": "rec_test_timeout_456",
        "job_name": "海投运维",
        "company_name": "测试海投",
        "platform": "51job",
        "pipeline_task_id": "test_task_002",
        "stop_at_review": False,
    }
    state_config = {"configurable": {"thread_id": "rec_test_timeout_456"}}

    start_time = asyncio.get_event_loop().time()
    res = await graph_runner._run_single_job_graph(
        initial_state,
        state_config,
        "test_task_002",
    )
    elapsed = asyncio.get_event_loop().time() - start_time

    # 验证在 5s 超时后正常捕获 warning 退出，且总耗时约 5s（绝不阻塞 10s）
    assert res["outcome"] == "waiting"
    assert 4.5 <= elapsed < 7.0

@pytest.mark.asyncio
async def test_snapshot_section4_clean_reject_gate_branch(monkeypatch):
    """Q19：跟进状态=清洗淘汰/ai清洗淘汰 且无有效评级时归 rejected_auto，不再误判 error 半成品

    分支位于 E/F 评级推断之后且要求无评级：生产波次流水线对 F 级同时写「清洗淘汰」
    门牌+F 评级，仍走 E/F 分支（行为锁定见下方共存用例）；「门牌+A-D 评级」怪异数据
    维持 has_rating→waiting 旧行为（锁定见第三个用例）。本用例兜人工置门牌/评级缺失。
    """
    jobs = await _section4_solo_snapshot(monkeypatch, {
        "rec_clean": {"fields": {"岗位名称": "规则淘汰岗", "公司名称": "某公司", "跟进状态": "清洗淘汰"}},
        "rec_ai_clean": {"fields": {"岗位名称": "AI淘汰岗", "公司名称": "某公司", "跟进状态": "ai清洗淘汰"}},
        "rec_ai_clean_space": {"fields": {"岗位名称": "AI淘汰岗(带空格变体)", "公司名称": "某公司", "跟进状态": "ai 清洗淘汰"}},
    })

    for rid in ("rec_clean", "rec_ai_clean", "rec_ai_clean_space"):
        assert rid in jobs, f"{rid} 未出现在快照"
        assert jobs[rid]["status"] == "rejected_auto", f"{rid}: {jobs[rid]['status']}"
        assert jobs[rid]["node"] == "clean_rule_rejected"
        assert jobs[rid]["sub_status"] == "rejected_auto"
    assert jobs["rec_clean"]["last_action_desc"] == "触发规则清洗淘汰"
    assert jobs["rec_ai_clean"]["last_action_desc"] == "触发AI排雷规则淘汰"
    assert jobs["rec_ai_clean_space"]["last_action_desc"] == "触发AI排雷规则淘汰"


@pytest.mark.asyncio
async def test_snapshot_section4_clean_gate_with_grade_keeps_ef_branch(monkeypatch):
    """岗哨3 P1 锁定：「清洗淘汰」门牌 + F 评级共存（生产波次流水线 wave_pipeline 写入口径）
    仍走 E/F 分支，分诊与文案与历史行为完全一致。"""
    jobs = await _section4_solo_snapshot(monkeypatch, {
        "rec_clean_with_f": {
            "fields": {
                "岗位名称": "波次淘汰岗",
                "公司名称": "某公司",
                "跟进状态": "清洗淘汰",
                "综合评级 (A-F)": "F",
            },
        },
    })

    assert jobs["rec_clean_with_f"]["status"] == "rejected_auto"
    assert jobs["rec_clean_with_f"]["node"] == "clean_rule_rejected"
    assert jobs["rec_clean_with_f"]["sub_status"] == "rejected_auto"
    # 关键锁定：走的是 E/F 分支文案，而非 Q19 门牌分支文案
    assert jobs["rec_clean_with_f"]["last_action_desc"] == "初评未达门槛，已自动淘汰"


@pytest.mark.asyncio
async def test_snapshot_section4_clean_gate_with_ad_grade_keeps_waiting(monkeypatch):
    """岗哨3 round2 P1 锁定：「清洗淘汰」门牌 + A-D 评级的怪异组合维持旧行为
    has_rating → waiting（Q19 修复面精确限定在「无有效评级」）。"""
    jobs = await _section4_solo_snapshot(monkeypatch, {
        "rec_clean_with_b": {
            "fields": {
                "岗位名称": "怪异组合岗",
                "公司名称": "某公司",
                "跟进状态": "清洗淘汰",
                "综合评级 (A-F)": "B",
            },
        },
    })

    assert jobs["rec_clean_with_b"]["status"] == "waiting"
    assert jobs["rec_clean_with_b"]["node"] == "manual_review_node"
    assert jobs["rec_clean_with_b"]["sub_status"] == "waiting"


# ---------------------------------------------------------------- Q19 系共享骨架

async def _section4_solo_snapshot(monkeypatch, records):
    """Section 4 单独供数骨架：六路查询置空 + 指定 records，使记录全部落入 Section 4。"""
    from app.automation import run_snapshot as _rs
    from app.services import feishu_service

    monkeypatch.setattr(_rs, "current_runtime", lambda: {
        "started": True,
        # Q19 系用例均验停机形态（旧行为把无评级门牌误判 error 的场景）
        "running": False,
        "task_id": "pipeline_section4_solo",
        "start_rowid": 0,
        "record_ids": list(records.keys()),
    })
    monkeypatch.setattr(_rs, "get_dismissed_job_ids", lambda: set())
    monkeypatch.setattr(_rs, "get_retrying_job_ids", lambda: set())

    monkeypatch.setattr(feishu_service, "get_pending_review_jobs_from_feishu", lambda: [])
    monkeypatch.setattr(feishu_service, "get_manual_rejected_jobs_from_feishu", lambda: [])
    monkeypatch.setattr(feishu_service, "get_failed_jobs_from_feishu", lambda: [])
    monkeypatch.setattr(feishu_service, "get_scheduled_delivery_jobs_from_feishu", lambda: [])
    monkeypatch.setattr(feishu_service, "get_delivered_jobs_from_feishu", lambda limit=5, only_today=True: [])
    monkeypatch.setattr(
        feishu_service,
        "get_job_record_from_feishu",
        lambda rid, tid: records.get(rid),
    )

    snapshot = await build_jobs_snapshot()
    return {j["job_id"]: j for j in snapshot["data"]}
