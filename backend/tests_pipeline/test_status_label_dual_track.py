"""
门牌双轨回归测试（2026-08-29 门牌双头事故）
==========================================
业务规则：审批断点的门牌按评级分轨——
  - 低分轨（C-F，无定制简历）→「海投人工复核」
  - 精投轨（A/B 或有定制简历）→「简历人工复核」

背景：2026-08-29 发现 282 条 C/D/F 岗位挂在「简历人工复核」
（8月26日 门牌双轨化之前的历史单值遗留 + 现行路径散点写入），
本测试把现行代码的门牌词汇锁死，防止回退。
"""
import asyncio

from langgraph.checkpoint.memory import MemorySaver

from app.automation.workflow import build_pipeline_graph, manual_review_node

D_SCORER_RESULT = {
    "success": True,
    "record_id": "rec_test_d",
    "update_data": {
        "综合评级 (A-F)": "D",
        "AI评估详情": "测试评估详情",
        "跟进状态": "已完成初步评估",
    },
    "ai_score": 46,
    "grade": "D",
    "status": "已完成初步评估",
    "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    "rationales_text": "",
    "company_intel": "",
}


def _base_state(**overrides):
    state = {
        "job_id": "",
        "record_id": "rec_test_d",
        "platform": "智联招聘",
        "company_name": "测试公司",
        "job_name": "测试岗位",
        "jd_text": "测试JD",
        "salary": "2-3万",
        "city": "广州",
        "experience": "3-5年",
        "education": "本科",
        "job_url": "https://www.zhaopin.com/jobdetail/test",
        "resume_text": "测试简历",
        "mass_resume_text": "测试海投简历",
        "preferences_text": "测试偏好",
        "company_intel": "",
        "feishu_fields": {"公司规模": "10000人以上"},  # 触发海投大厂拦截 → 审批断点
        "ai_score": 0,
        "score": 0,
        "grade": "",
        "diagnosis_dict": {},
        "final_markdown": "",
        "greeting": "",
        "status": "",
        "messages": [],
        "error": None,
        "stop_at_review": False,
        "pipeline_task_id": "",
        "raw_job_id": "raw_1",
        "company_scale": "10000人以上",
    }
    state.update(overrides)
    return state


def _patch_boundaries(monkeypatch, writes):
    """把所有外部边界（飞书写入 / LLM 评分 / 配置）替换为确定性桩。"""
    def fake_update(record_id, updates, table_id=None):
        writes.append((record_id, dict(updates)))
        return True

    monkeypatch.setattr("app.automation.tools.update_feishu_record", fake_update)
    monkeypatch.setattr("app.services.feishu_service.update_feishu_record", fake_update)
    monkeypatch.setattr("app.automation.workflow.evaluate_single_job", lambda *a, **k: D_SCORER_RESULT)
    monkeypatch.setattr("ai_agents.ai_evaluator.get_auto_eval_threshold", lambda: "B")

    cfg = {
        "mass_apply_greeting": "测试海投话术",
        "auto_deliver_platforms": ["boss"],  # 智联不在白名单 → 安检拦截 → 审批断点
        "auto_deliver_grades": ["C", "D", "F"],
        "mass_apply_max_headcount": 1000,
    }
    monkeypatch.setattr("app.automation.workflow.get_autopilot_config", lambda: cfg)
    monkeypatch.setattr("app.automation.db.get_autopilot_config", lambda: cfg)

    from unittest.mock import AsyncMock
    fake_materials = {
        "pdf_token": "fake_pdf_token",
        "image_tokens": ["fake_img_token"],
        "img_token": "fake_img_token",
        "name": "测试简历",
    }
    monkeypatch.setattr("app.automation.materials._render_mass_resume_materials", AsyncMock(return_value=fake_materials))
    monkeypatch.setattr("app.automation.materials._render_mass_resume_materials_with_name", AsyncMock(return_value=fake_materials))
    monkeypatch.setattr("app.automation.materials._render_custom_resume_materials", AsyncMock(return_value=fake_materials))
    monkeypatch.setattr("app.automation.materials.ensure_mass_apply_materials", AsyncMock(return_value=fake_materials))


def test_low_track_pause_label_is_mass_review(monkeypatch):
    """D 级低分轨岗位跑到审批断点：门牌序列必须是 已完成初步评估 → 海投人工复核，
    且全程任何节点不得把门牌改写为「简历人工复核」。"""
    writes = []
    _patch_boundaries(monkeypatch, writes)

    app = build_pipeline_graph().compile(
        checkpointer=MemorySaver(),
        interrupt_before=["manual_review_node"],
    )
    config = {"configurable": {"thread_id": "rec_test_d"}}
    state = _base_state()

    async def run():
        async for _ in app.astream(state, config):
            pass
        return await app.aget_state(config)

    snap = asyncio.run(run())
    statuses = [w[1]["跟进状态"] for w in writes if "跟进状态" in w[1]]
    assert statuses == ["已完成初步评估", "海投人工复核"], f"门牌写入序列异常: {statuses}"
    assert "简历人工复核" not in statuses, "低分轨岗位不得挂精投门牌"
    assert snap.values.get("status") == "海投人工复核"


def test_manual_review_node_writes_by_track(monkeypatch):
    """审批断点节点直测：D 级（无定制简历）写「海投人工复核」；B 级（有定制简历）写「简历人工复核」"""
    writes = []
    _patch_boundaries(monkeypatch, writes)

    d_state = _base_state(grade="D", final_markdown="")
    asyncio.run(manual_review_node(d_state))
    assert writes[-1][1]["跟进状态"] == "海投人工复核", \
        f"D 级岗位门牌应为海投人工复核，实际: {writes[-1][1]}"

    writes.clear()
    b_state = _base_state(grade="B", final_markdown="# 定制简历")
    asyncio.run(manual_review_node(b_state))
    assert writes[-1][1]["跟进状态"] == "简历人工复核", \
        f"B 级定制岗位门牌应为简历人工复核，实际: {writes[-1][1]}"
