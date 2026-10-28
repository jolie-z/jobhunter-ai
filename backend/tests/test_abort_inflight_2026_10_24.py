"""2026-10-24 真机工单：终止任务后链路仍在评估/改写/真实投递，回归锁定。

病灶：终止接口置位成功（200 + 标志置位），但岗位一旦进入 LangGraph 图
（evaluate→deep_eval→rewrite→greeting→delivery），节点链上没有任何环节检查
is_aborted()——终止后仍继续烧 token 评估、改写，并在 BOSS 上真实发送打招呼语/简历。

本文件锁定五个修复点：
1. graph_runner astream 循环末尾终止刹车：当前节点完成、后续节点永不启动；
2. 图自然结束的竞态保护：终止瞬间已投递成功的岗位不得误报为终止；
3. 投递节点全局终止兜底：未唤起引擎前拦截；
4. end_pipeline 清终止标志：避免残留污染后续单岗/定时波次流程；
5. /abort 在途投递破门打断 + 战报「手动终止」分桶与主卡片横幅。
"""
import asyncio
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.automation import abort as abort_mod  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_abort_state():
    abort_mod._state.update({"aborted": False, "pipeline_task_id": ""})
    abort_mod._platform_aborted.clear()
    abort_mod._cancelled_job_deliveries.clear()
    yield
    abort_mod._state.update({"aborted": False, "pipeline_task_id": ""})
    abort_mod._platform_aborted.clear()
    abort_mod._cancelled_job_deliveries.clear()


def _job_state(**overrides):
    state = {
        "record_id": "rec_abort_test",
        "job_id": "rec_abort_test",
        "job_name": "测试岗位",
        "company_name": "测试公司",
        "platform": "boss",
        "feishu_fields": {},
    }
    state.update(overrides)
    return state


# ==========================================
# 1) astream 循环末尾刹车：当前节点完成，下一节点不启动
# ==========================================

def _install_fake_app(monkeypatch, nodes, *, next_nodes, final_values, on_emit_job=None):
    """装一个「拉取才执行下一个节点」的假图（模拟 langgraph astream 的拉模式）。

    返回 pulls 列表：记录真实发生的节点执行次数，用于断言终止后不再启动新节点。
    """
    from app.automation import pipeline_broadcast as pb, scheduler

    pulls: list[str] = []

    class _FakeApp:
        def astream(self, _input, _config):
            async def _gen():
                for node in nodes:
                    pulls.append(node)
                    yield {node: {"grade": "B"}}

            return _gen()

        async def aget_state(self, _config):
            return SimpleNamespace(values=final_values, next=next_nodes)

    async def fake_emit_job(_task_id, **kwargs):
        if on_emit_job:
            on_emit_job(kwargs.get("node"))

    async def fake_noop(*_args, **_kwargs):
        return None

    monkeypatch.setattr(scheduler, "pipeline_app", _FakeApp())
    monkeypatch.setattr(pb, "emit_job", fake_emit_job)
    monkeypatch.setattr(pb, "emit_stage", fake_noop)
    monkeypatch.setattr(pb, "emit_log", fake_noop)
    return pulls


def test_graph_aborts_after_current_node_and_never_starts_next(monkeypatch):
    """终止发生在初评完成广播时：初评成果保留，深度评估/改写不再执行。"""
    from app.automation import graph_runner

    pulls = _install_fake_app(
        monkeypatch,
        nodes=("evaluate_node", "deep_eval_node", "rewrite_node"),
        next_nodes=("deep_eval_node",),
        final_values={"grade": "B"},
        on_emit_job=lambda node: abort_mod._state.update({"aborted": True})
        if node == "evaluate_node" else None,
    )

    res = asyncio.run(graph_runner._run_single_job_graph(
        _job_state(), {"configurable": {"thread_id": "rec_abort_test"}}, "pipeline_abort_test"))

    assert pulls == ["evaluate_node"], "终止后不得再拉取下一个节点（该节点永远不会启动）"
    assert res["outcome"] == "aborted"
    assert res["status"] == "手动终止"


def test_graph_entry_guard_skips_first_node_when_already_aborted(monkeypatch):
    """批次建任务后、图启动前已收到终止：直接收口，不空跑首个 evaluate_node。"""
    from app.automation import graph_runner

    pulls = _install_fake_app(
        monkeypatch,
        nodes=("evaluate_node", "deep_eval_node"),
        next_nodes=("evaluate_node",),
        final_values={},
    )
    abort_mod._state["aborted"] = True

    res = asyncio.run(graph_runner._run_single_job_graph(
        _job_state(), {"configurable": {"thread_id": "rec_abort_test"}}, "pipeline_abort_test"))

    assert pulls == [], "入口终止守卫必须阻止首个节点启动"
    assert res["outcome"] == "aborted"


def test_graph_finished_delivery_not_misreported_as_aborted(monkeypatch):
    """终止瞬间图已自然跑完且投递成功：按真实结果交付，不得误报手动终止。"""
    from app.automation import graph_runner

    pulls = _install_fake_app(
        monkeypatch,
        nodes=("evaluate_node", "delivery_node"),
        next_nodes=(),
        final_values={"grade": "B", "status": "已投递"},
        on_emit_job=lambda node: abort_mod._state.update({"aborted": True})
        if node == "delivery_node" else None,
    )

    res = asyncio.run(graph_runner._run_single_job_graph(
        _job_state(), {"configurable": {"thread_id": "rec_abort_test"}}, "pipeline_abort_test"))

    assert pulls == ["evaluate_node", "delivery_node"]
    assert res["outcome"] == "delivered", "已送达岗位不能被终止瞬间的竞态误标"


# ==========================================
# 2) 投递节点全局终止兜底：不唤起引擎
# ==========================================

def test_delivery_node_blocked_before_engine_on_global_abort(monkeypatch):
    from app.automation import workflow

    class _BoomTool:
        async def ainvoke(self, *_args, **_kwargs):
            raise AssertionError("全局终止下不得调用投递引擎")

    monkeypatch.setattr(workflow, "deliver_boss_job", _BoomTool())
    abort_mod._state["aborted"] = True

    res = asyncio.run(workflow._delivery_node_inner(_job_state()))

    assert res["error"].startswith("[用户主动终止]")


def test_delivery_node_attribution_keeps_real_success(monkeypatch):
    """引擎执行期间收到全局终止、但实际已送达：保留成功，避免二次重复投递。"""
    from app.automation import workflow

    class _SuccessTool:
        async def ainvoke(self, *_args, **_kwargs):
            # 模拟终止指令在引擎执行期间下达（入口检查已通过）
            abort_mod._state["aborted"] = True
            return "✅ BOSS 投递引擎执行成功"

    class _StatusTool:
        async def ainvoke(self, *_args, **_kwargs):
            return "ok"

    monkeypatch.setattr(workflow, "deliver_boss_job", _SuccessTool())
    monkeypatch.setattr(workflow, "update_feishu_status", _StatusTool())

    res = asyncio.run(workflow._delivery_node_inner(_job_state(
        platform="boss",
        job_url="https://www.zhipin.com/job_detail/x.html",
        greeting="您好，非常期待与您沟通",
        image_items=[{"token": "tok", "name": "img.jpg"}],
    )))

    assert res.get("status") == "已投递", "已真实送达不得被终止归因覆写为失败"


# ==========================================
# 3) end_pipeline 清终止标志，防止污染后续流程
# ==========================================

def test_end_pipeline_clears_abort_flag():
    abort_mod.begin_pipeline("pipeline_abort_test")
    assert abort_mod.request_abort("pipeline_abort_test") is True
    assert abort_mod.is_aborted() is True
    abort_mod.cancel_job_delivery("rec_stale")
    abort_mod.request_platform_abort("boss")

    abort_mod.end_pipeline()

    assert abort_mod.is_aborted() is False, "收尾后必须清标志，避免误杀后续单岗/波次流程"
    assert abort_mod.current_pipeline_task_id() == ""
    assert abort_mod.is_job_delivery_cancelled("rec_stale") is False, "单岗取消标记不得残留到下一轮"
    assert abort_mod.is_platform_aborted("boss") is False, "平台终止登记不得残留到下一轮"


# ==========================================
# 4) /abort 在途投递破门打断
# ==========================================

def test_abort_endpoint_interrupts_inflight_deliveries(monkeypatch):
    from app.automation import delivery_interrupter, run_snapshot
    from app.automation.routes import control_router

    abort_mod.begin_pipeline("pipeline_abort_test")
    interrupted: list[str] = []
    monkeypatch.setattr(run_snapshot, "get_active_inflight_job_ids", lambda: {"rec_a", "rec_b"})
    monkeypatch.setattr(
        delivery_interrupter, "interrupt_active_job",
        lambda rid: interrupted.append(rid) or True,
    )

    with patch("app.api.routes.crawlers.stop_platform"):
        res = asyncio.run(control_router.abort_pipeline(
            control_router.AbortRequest(task_id="pipeline_abort_test")))

    assert res["aborted"] is True
    assert res["interrupted"] == ["rec_a", "rec_b"], "在途投递必须逐个破门打断"
    assert sorted(interrupted) == ["rec_a", "rec_b"]


# ==========================================
# 5) 战报分桶与主卡片横幅
# ==========================================

def test_report_buckets_manual_abort_separately():
    from app.automation import pipeline_report as pr

    text = pr.build_pipeline_report(
        started_at=datetime.now(),
        scrape_counts={},
        disabled_platforms=[],
        platform_cn={},
        cleaning={},
        synced_count=0,
        job_results=[
            {"job_name": "A岗", "company_name": "甲", "platform": "boss", "grade": "B",
             "outcome": pr.OUTCOME_ABORTED, "error": ""},
            {"job_name": "B岗", "company_name": "乙", "platform": "boss", "grade": "",
             "outcome": pr.OUTCOME_ABORTED, "error": ""},
            {"job_name": "C岗", "company_name": "丙", "platform": "boss", "grade": "C",
             "outcome": pr.OUTCOME_DELIVERED, "error": ""},
        ],
        aborted=True,
    )

    assert "手动终止（2 条" in text, "终止岗位必须单列，不得静默消失"
    assert "｜手动终止" in text, "A/B 高价值段必须标注终止"
    assert "评估失败" not in text, "未完成初评的终止岗不得折算成评估失败"
    assert "⛔ 本次任务被手动终止" in text


def test_master_card_marks_manual_abort():
    from app.services.pipeline_card_builders import build_master_pipeline_card

    card = build_master_pipeline_card(aborted=True, aborted_cnt=2, aborted_ungraded_cnt=1)

    assert card["header"]["template"] == "red"
    dumped = str(card["elements"])
    assert "手动终止" in dumped
    assert "评估异常中断" not in dumped, "未完成初评的终止岗不得计入评估异常中断"


def test_send_master_card_propagates_aborted(monkeypatch):
    """主卡片是飞书侧第一事实源：aborted 必须贯穿到卡片，不能只体现在文本兜底报告。"""
    from app.automation import pipeline_report as pr

    captured: dict = {}

    async def fake_send(receive_id, card_content, receive_id_type=None):
        captured["card"] = card_content
        return True

    monkeypatch.setattr("app.core.feishu_messaging.is_valid_receive_id", lambda _x: True)
    monkeypatch.setattr("app.services.report_feishu._get_receive_id", lambda: "ou_test")
    monkeypatch.setattr("app.core.feishu_messaging.send_feishu_card", fake_send)

    ok = asyncio.run(pr.send_pipeline_master_card(
        started_at=datetime.now(),
        scrape_counts={"boss": 2},
        cleaning={"total": 2},
        job_results=[{
            "record_id": "rec_abort_test", "job_name": "测试岗位", "company_name": "测试公司",
            "platform": "boss", "grade": "B", "outcome": pr.OUTCOME_ABORTED, "error": "",
        }],
        aborted=True,
    ))

    assert ok is True
    assert captured["card"]["header"]["template"] == "red"
    assert "手动终止" in str(captured["card"]["elements"])
