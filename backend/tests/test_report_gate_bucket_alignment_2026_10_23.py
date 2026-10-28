"""飞书战报分桶与安检闸门口径对齐回归锁（2026-10-23，pipeline_63487fa1 事故）。

事故复盘：主战报「海投规则审批（如大厂）」按评级 C 分桶、D/F 一律计入
「其他情况【已执行自动投递】」——D 级大厂拦截岗（挂「海投人工复核」停在审批断点）
被误报成已自动投递，且 mass_record_ids 恒等于 C 级岗位集合、放行卡为空；
桌面待审批 tab（按跟进状态「复核」拉取）却真实显示这些岗位，双端口径撕裂。

修复后单一事实源：graph_runner 在审批断点把闸门挂起类型（review_kind）与
拦截原因（gate_reason）写入 job_results；战报按 review_kind/outcome 分桶，
评级只用于「初评梯队」展示行。本文件锁死该口径：
1. D 级大厂拦截岗进海投审批桶（mass_record_ids 收编，放行卡可见）
2. C 级已投递岗不再被虚报为「海投规则审批」
3. 「已执行自动投递」= 真实 outcome==delivered
4. 「复核」门牌提前 END 的岗位与桌面待审批 tab 同口径计 waiting
5. 精投区文案如实标注「评级未在自动投递白名单，待审批」
"""
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _fake_config(**overrides):
    cfg = {
        "mass_apply_max_headcount": 5000,
        "auto_deliver_platforms": ["boss", "liepin", "51job", "zhilian"],
        "auto_deliver_grades": ["C", "D", "F"],
    }
    cfg.update(overrides)
    return cfg


def _job(rid, grade, outcome, review_kind=None, gate_reason="", company_scale="", error=""):
    j = {
        "record_id": rid,
        "job_id": rid,
        "job_name": f"岗位{rid}",
        "company_name": f"公司{rid}",
        "platform": "BOSS直聘",
        "grade": grade,
        "outcome": outcome,
        "error": error,
    }
    if review_kind is not None:
        j["review_kind"] = review_kind
    if gate_reason:
        j["gate_reason"] = gate_reason
    if company_scale:
        j["company_scale"] = company_scale
    return j


# ─────────────────────────────────────────────────────────────
# 1. 战报分桶 plumbing：以 review_kind/outcome 为事实源
# ─────────────────────────────────────────────────────────────
def test_master_card_bucketing_by_review_kind_not_grade():
    """pipeline_63487fa1 场景复现：D 级大厂拦截岗必须进海投审批桶，C 级已投递岗不得虚报待审批"""
    import asyncio
    from app.automation import pipeline_report as pr

    captured = {}

    def fake_builder(**kwargs):
        captured.update(kwargs)
        return {"elements": []}

    job_results = [
        # 安利 FP&A：D 级 + 大厂规模拦截，挂「海投人工复核」停审批断点
        _job("recFPA", "D", "waiting", review_kind="mass_review",
             gate_reason="公司规模 1000-9999人 ≥ 门槛 5000", company_scale="1000-9999人"),
        # 3 条 A/B 精投岗停审批
        _job("recAB1", "A", "waiting", review_kind="custom_review"),
        _job("recAB2", "B", "waiting", review_kind="custom_review"),
        _job("recAB3", "B", "waiting", review_kind="custom_review"),
        # 1 条 C 级 + 1 条 D 级真实投递成功
        _job("recDelivC", "C", "delivered"),
        _job("recDelivD", "D", "delivered"),
        # 1 条 C 级已过安检等发射波次
        _job("recReadyC", "C", "ready_to_deliver"),
        # 1 条评估失败（grade 空）
        _job("recEvalFail", "", "failed", error="8维解析失败"),
    ]
    with patch("app.services.pipeline_card_builders.build_master_pipeline_card", side_effect=fake_builder), \
         patch("app.core.feishu_messaging.is_valid_receive_id", return_value=True), \
         patch("app.core.feishu_messaging.send_feishu_card", return_value=True), \
         patch("app.services.report_feishu._get_receive_id", return_value="oc_test"):
        ok = asyncio.run(pr.send_pipeline_master_card(
            started_at=datetime(2026, 10, 23, 12, 47, 0),
            scrape_counts={"BOSS直聘": 8},
            cleaning={"hard_rejected": 0, "hard_passed": 8, "ai_rejected": 0, "ai_passed": 8},
            job_results=job_results,
            trigger_source="manual",
        ))

    assert ok is True
    # 海投审批桶 = 闸门拦截挂「海投人工复核」的岗位（与桌面待审批 tab 同口径）
    assert captured["mass_review_cnt"] == 1
    assert captured["mass_record_ids"] == ["recFPA"], "D 级大厂拦截岗必须进放行卡按钮值"
    # 精投桶 = 停审批的 A/B（custom_review）岗
    assert captured["ab_record_ids"] == ["recAB1", "recAB2", "recAB3"]
    assert captured["precision_cnt"] == 3
    # 「已执行自动投递」= 真实投递成功数，绝不是 D/F 评级代名词（事故里 D 级拦截岗+1 条成功被并称 2 条已投递）
    assert captured["auto_delivered_cnt"] == 2
    assert captured["ready_to_deliver_cnt"] == 1
    # 初评梯队展示行仍是纯评级分布（A1/B2/C2/D-F2），评估失败单列
    assert captured["grade_counts"] == {"A": 1, "B": 2, "C": 2, "D/F": 2}
    assert captured["eval_failed_cnt"] == 1


def test_master_card_c_grade_delivered_not_in_mass_bucket():
    """旧 bug 锁：C 级已投递岗位曾被计入 mass_review_cnt/mass_record_ids（虚报待审批）"""
    import asyncio
    from app.automation import pipeline_report as pr

    captured = {}

    def fake_builder(**kwargs):
        captured.update(kwargs)
        return {"elements": []}

    job_results = [
        _job("recC1", "C", "delivered"),
        _job("recC2", "C", "delivered"),
    ]
    with patch("app.services.pipeline_card_builders.build_master_pipeline_card", side_effect=fake_builder), \
         patch("app.core.feishu_messaging.is_valid_receive_id", return_value=True), \
         patch("app.core.feishu_messaging.send_feishu_card", return_value=True), \
         patch("app.services.report_feishu._get_receive_id", return_value="oc_test"):
        asyncio.run(pr.send_pipeline_master_card(
            started_at=datetime(2026, 10, 23, 12, 47, 0),
            scrape_counts={"BOSS直聘": 2},
            cleaning={"hard_rejected": 0, "hard_passed": 2, "ai_rejected": 0, "ai_passed": 2},
            job_results=job_results,
        ))

    assert captured["mass_review_cnt"] == 0
    assert captured["mass_record_ids"] == []
    assert captured["auto_delivered_cnt"] == 2


def test_master_card_legacy_fallback_without_review_kind():
    """review_kind 缺失（防御兼容）：waiting 岗按 A/B→精投、其余→海投兜底分桶"""
    import asyncio
    from app.automation import pipeline_report as pr

    captured = {}

    def fake_builder(**kwargs):
        captured.update(kwargs)
        return {"elements": []}

    job_results = [
        _job("recB1", "B", "waiting"),   # 无 review_kind
        _job("recD1", "D", "waiting"),   # 无 review_kind
    ]
    with patch("app.services.pipeline_card_builders.build_master_pipeline_card", side_effect=fake_builder), \
         patch("app.core.feishu_messaging.is_valid_receive_id", return_value=True), \
         patch("app.core.feishu_messaging.send_feishu_card", return_value=True), \
         patch("app.services.report_feishu._get_receive_id", return_value="oc_test"):
        asyncio.run(pr.send_pipeline_master_card(
            started_at=datetime(2026, 10, 23, 12, 47, 0),
            scrape_counts={"BOSS直聘": 2},
            cleaning={"hard_rejected": 0, "hard_passed": 2, "ai_rejected": 0, "ai_passed": 2},
            job_results=job_results,
        ))

    assert captured["ab_record_ids"] == ["recB1"]
    assert captured["mass_record_ids"] == ["recD1"]


# ─────────────────────────────────────────────────────────────
# 2. 主卡文案：真实口径渲染
# ─────────────────────────────────────────────────────────────
def test_master_card_flow_section_wording():
    from app.services.pipeline_card_builders import build_master_pipeline_card

    card = build_master_pipeline_card(
        task_time="2026-10-23 12:56:00",
        mass_review_cnt=1,
        auto_delivered_cnt=1,
        ready_to_deliver_cnt=0,
        precision_cnt=3,
        ab_record_ids=["recAB1", "recAB2", "recAB3"],
        grade_counts={"A": 1, "B": 2, "C": 1, "D/F": 2},
    )
    content = str(card["elements"])
    # 海投安检与投递块：待审批数=闸门拦截数，已投递数=真实投递数
    assert "海投安检与投递 (待审批 1 条 · 已投递 1 条)" in content
    assert "【已在待审批tab等待审批放行】" in content
    assert "【已执行自动投递】" in content
    assert "等待定时发射" not in content  # ready=0 时不渲染发射波次行
    # 精投区：A/B 全部停审批时如实标注白名单语义
    assert "评级 A/B 不在自动投递白名单" in content


def test_master_card_flow_section_with_ready_line():
    from app.services.pipeline_card_builders import build_master_pipeline_card

    card = build_master_pipeline_card(
        task_time="2026-10-23 12:56:00",
        mass_review_cnt=0,
        auto_delivered_cnt=0,
        ready_to_deliver_cnt=4,
        grade_counts={"C": 4},
    )
    content = str(card["elements"])
    assert "【等待定时发射自动投出】" in content
    assert "已过安检待发射波次的岗位有" in content and "<font color='grey'>**4**</font>" in content


def test_master_card_precision_note_honest_when_partially_delivered():
    """精投区文案：有 A/B 已投递/流转时不得宣称「全部挂起等待审批」"""
    from app.services.pipeline_card_builders import build_master_pipeline_card

    card = build_master_pipeline_card(
        task_time="2026-10-23 12:56:00",
        precision_cnt=3,
        ab_record_ids=["recAB1", "recAB2"],  # 仅 2 条停审批
        grade_counts={"A": 1, "B": 2},
    )
    content = str(card["elements"])
    assert "2 条已生成定制简历，评级未在自动投递白名单，挂起待审批" in content
    assert "其余 1 条已进入投递/其他流转" in content


def test_master_card_precision_note_zero_ab_jobs():
    """精投区边界：本轮无 A/B 岗时不得渲染「共 0 条 … 全部挂起」的语义冲突文案（R1 P2 采纳）"""
    from app.services.pipeline_card_builders import build_master_pipeline_card

    card = build_master_pipeline_card(
        task_time="2026-10-23 12:56:00",
        precision_cnt=0,
        ab_record_ids=[],
        grade_counts={"C": 2, "D/F": 1},
    )
    content = str(card["elements"])
    assert "本轮无 A/B 级精投岗位挂起" in content
    assert "全部已生成定制简历" not in content


# ─────────────────────────────────────────────────────────────
# 3. graph_runner：审批断点结果携带 review_kind + gate_reason
# ─────────────────────────────────────────────────────────────
def _mock_pipeline_app(snapshot: MagicMock) -> MagicMock:
    async def empty_async_gen(*args, **kwargs):
        if False:
            yield {}

    app = MagicMock()
    app.astream = empty_async_gen
    app.aget_state = AsyncMock(return_value=snapshot)
    return app


@pytest.mark.asyncio
async def test_graph_runner_mass_breakpoint_carries_gate_reason(monkeypatch):
    """FP&A 场景：D 级大厂规模拦截停审批断点 → waiting + mass_review + 规模拦截原因"""
    from app.automation import graph_runner, scheduler, workflow
    from app.services import feishu_service

    feishu_calls = []
    monkeypatch.setattr(feishu_service, "update_feishu_record",
                        lambda rid, updates, tid=None: feishu_calls.append((rid, updates)) or True)
    monkeypatch.setattr(workflow, "get_autopilot_config", lambda: _fake_config(mass_apply_max_headcount=5000))

    snapshot = MagicMock()
    snapshot.next = ("manual_review_node",)
    snapshot.values = {
        "grade": "D",
        "final_markdown": "",
        "feishu_fields": {"公司规模": "1000-9999人"},  # 区间上限 9999 ≥ 海投门槛 5000
    }
    monkeypatch.setattr(scheduler, "pipeline_app", _mock_pipeline_app(snapshot))

    res = await graph_runner._run_single_job_graph(
        {"job_id": "rec_fpa", "job_name": "Sr. FP&A Supervisor", "company_name": "安利",
         "platform": "BOSS直聘", "pipeline_task_id": "t1", "stop_at_review": False},
        {"configurable": {"thread_id": "rec_fpa"}},
        "t1",
    )

    assert res["outcome"] == "waiting"
    assert res["review_kind"] == "mass_review"
    assert res["status"] == "海投人工复核"
    assert "公司规模" in res["gate_reason"] and "5000" in res["gate_reason"]
    assert feishu_calls and feishu_calls[0][1] == {"跟进状态": "海投人工复核"}


@pytest.mark.asyncio
async def test_graph_runner_custom_breakpoint_review_kind(monkeypatch):
    """A/B 精投轨停审批断点 → waiting + custom_review（评级白名单原因）"""
    from app.automation import graph_runner, scheduler, workflow
    from app.services import feishu_service

    monkeypatch.setattr(feishu_service, "update_feishu_record", lambda rid, updates, tid=None: True)
    monkeypatch.setattr(workflow, "get_autopilot_config", lambda: _fake_config())

    snapshot = MagicMock()
    snapshot.next = ("manual_review_node",)
    snapshot.values = {
        "grade": "B",
        "final_markdown": "# 定制简历",
        "feishu_fields": {},
    }
    monkeypatch.setattr(scheduler, "pipeline_app", _mock_pipeline_app(snapshot))

    res = await graph_runner._run_single_job_graph(
        {"job_id": "rec_ab", "job_name": "精投岗", "company_name": "某司",
         "platform": "BOSS直聘", "pipeline_task_id": "t2", "stop_at_review": False},
        {"configurable": {"thread_id": "rec_ab"}},
        "t2",
    )

    assert res["outcome"] == "waiting"
    assert res["review_kind"] == "custom_review"
    assert res["status"] == "简历人工复核"
    assert "评级" in res["gate_reason"] and "白名单" in res["gate_reason"]


@pytest.mark.asyncio
async def test_graph_runner_review_status_early_end_maps_to_waiting(monkeypatch):
    """「复核」门牌提前 END（如 stop_at_review 物料未就绪）：桌面待审批 tab 必然收编，
    战报同口径计 waiting，不再误入「提前终止」"""
    from app.automation import graph_runner, scheduler, workflow

    monkeypatch.setattr(workflow, "get_autopilot_config", lambda: _fake_config())

    snapshot = MagicMock()
    snapshot.next = ()  # 图已 END，未停断点
    snapshot.values = {"grade": "C", "final_markdown": "", "status": "海投人工复核", "feishu_fields": {}}
    monkeypatch.setattr(scheduler, "pipeline_app", _mock_pipeline_app(snapshot))

    res = await graph_runner._run_single_job_graph(
        {"job_id": "rec_mat", "job_name": "物料未就绪岗", "company_name": "某司",
         "platform": "BOSS直聘", "pipeline_task_id": "t3", "stop_at_review": True},
        {"configurable": {"thread_id": "rec_mat"}},
        "t3",
    )

    assert res["outcome"] == "waiting"
    assert res["review_kind"] == "mass_review"
    assert res["status"] == "海投人工复核"
    # 安检已过却停在复核 = 物料未就绪/流程中断（与 snapshot_service._mass_review_reason 同文案）
    assert "物料未就绪" in res["gate_reason"]
