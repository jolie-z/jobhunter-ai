"""高分轨 LLM 调用去重回归测试。

背景：evaluate_node 曾以 task_mode="auto" 内联执行「8维初评 + 深评 + 改写 + 打招呼语」，
随后 rewrite_node 又把改写 + 打招呼语完整重做一遍——同一岗位这几段 LLM 成本翻倍。
深评也一直内联在初评节点里，职责错位且无法被指挥中心作为独立阶段观测。

拆分后的契约（本测试锁死）：
1. evaluate_node 只以 eval_only 调初评，绝不触发深评/改写/话术；
2. deep_eval_node 只调一次 deep_evaluate_resume，并回写 6 个深评字段；
3. rewrite_node 只消费 deep_diagnosis，不再调 deep_evaluate_resume；
4. 旧 checkpoint（没有 deep_diagnosis）回退用 diagnosis_dict，同样不补跑深评。
"""

import asyncio

from app.automation import workflow


class _FeishuTool:
    """替换 update_feishu_status 工具，记录每次回写。"""

    def __init__(self):
        self.writes = []

    async def ainvoke(self, payload):
        self.writes.append(payload)
        return "✅ fake"


def _base_state(**overrides):
    state = {
        "record_id": "rec_dedup_001",
        "job_id": "rec_dedup_001",
        "platform": "BOSS直聘",
        "company_name": "测试公司",
        "job_name": "AI 产品经理",
        "jd_text": "负责 AI 产品规划与落地",
        "salary": "30-50K",
        "city": "上海",
        "experience": "3-5年",
        "education": "本科",
        "resume_text": "候选人简历正文",
        "preferences_text": "偏好正文",
        "company_intel": "",
        "feishu_fields": {},
        "ai_score": 0,
        "score": 0,
        "grade": "",
        "diagnosis_dict": {"综合评级 (A-F)": "A", "AI评估详情": "初评详情"},
        "final_markdown": "",
        "greeting": "",
        "status": "",
        "error": None,
        "stop_at_review": False,
        "pipeline_task_id": "",
    }
    state.update(overrides)
    return state


def test_evaluate_node_forces_eval_only(monkeypatch):
    """初评节点必须显式传 eval_only；否则 evaluate_single_job 会在内部再跑深评+改写+话术。"""
    calls = []

    def fake_evaluate_single_job(
        _job_data, _resume_text, _company_intel="", _preferences_text="", task_mode="auto", progress_callback=None
    ):
        calls.append(task_mode)
        return {
            "success": True,
            "update_data": {"跟进状态": "已完成初步评估"},
            "ai_score": 88,
            "grade": "A",
            "status": "已完成初步评估",
            "company_intel": "",
        }

    tool = _FeishuTool()
    monkeypatch.setattr(workflow, "evaluate_single_job", fake_evaluate_single_job)
    monkeypatch.setattr(workflow, "update_feishu_status", tool)
    monkeypatch.setattr(workflow, "_get_eval_semaphore", lambda: asyncio.Semaphore(1))

    result = asyncio.run(workflow.evaluate_node(_base_state()))

    assert calls == ["eval_only"], f"evaluate_node 必须以 eval_only 调初评，实际: {calls}"
    assert result["grade"] == "A"
    assert result["diagnosis_dict"]["跟进状态"] == "已完成初步评估"
    assert tool.writes[0]["updates"] == {"跟进状态": "已完成初步评估"}


def test_deep_eval_node_runs_once_and_writes_six_fields(monkeypatch):
    """深评节点是高分轨唯一一次 deep_evaluate_resume 调用。"""
    deep_calls = []
    deep_result = {
        "extracted_skills": ["Python"],
        "dream_picture": "理想画像",
        "ats_ability_analysis": "能力词典",
        "resume_audit": "逐行审计",
        "strong_fit_assessment": "高杠杆匹配",
        "risk_red_flags": "致命硬伤",
        "deep_action_plan": "破局计划",
    }

    def fake_deep(resume_text, jd_text, ai_result=None):
        deep_calls.append((resume_text, jd_text, ai_result))
        return deep_result, {"prompt_tokens": 100, "completion_tokens": 20}

    tool = _FeishuTool()
    monkeypatch.setattr(workflow, "deep_evaluate_resume", fake_deep)
    monkeypatch.setattr(workflow, "update_feishu_status", tool)
    monkeypatch.setattr(workflow, "_get_eval_semaphore", lambda: asyncio.Semaphore(1))

    result = asyncio.run(workflow.deep_eval_node(_base_state()))

    assert len(deep_calls) == 1, "deep_evaluate_resume 只能调用一次"
    assert result["deep_diagnosis"] == deep_result
    updates = tool.writes[0]["updates"]
    assert updates == {
        "理想画像与能力信号": "理想画像",
        "核心能力词典": "能力词典",
        "简历逐行审计": "逐行审计",
        "高杠杆匹配点": "高杠杆匹配",
        "致命硬伤与毒点": "致命硬伤",
        "破局行动计划": "破局计划",
    }


def test_deep_eval_node_does_not_overwrite_fields_on_fallback(monkeypatch):
    """深评失败兜底：不得把「深度评估失败」或空串回写飞书，也不得把无效诊断传给改写。"""
    fallback = {
        "extracted_skills": [],
        "dream_picture": "深度评估失败",
        "ats_ability_analysis": "深度评估失败",
        "resume_audit": "深度评估失败",
        "strong_fit_assessment": "深度评估失败",
        "risk_red_flags": "深度评估失败",
        "deep_action_plan": "深度评估失败",
    }

    tool = _FeishuTool()
    monkeypatch.setattr(workflow, "deep_evaluate_resume", lambda *a, **k: (fallback, {}))
    monkeypatch.setattr(workflow, "update_feishu_status", tool)
    monkeypatch.setattr(workflow, "_get_eval_semaphore", lambda: asyncio.Semaphore(1))

    result = asyncio.run(workflow.deep_eval_node(_base_state()))

    assert result == {"deep_diagnosis": {}, "deep_eval_completed": True}
    assert tool.writes == [], "深评失败时不得覆盖飞书已有深评字段"


def test_deep_eval_node_only_writes_valid_fields(monkeypatch):
    """部分解析失败：只回写有效字段，失败标记不得进入 deep_diagnosis。"""
    partial = {
        "dream_picture": "有效画像",
        "ats_ability_analysis": "深度评估失败",
        "resume_audit": "",
        "strong_fit_assessment": "有效匹配点",
        "risk_red_flags": "深度评估失败",
        "deep_action_plan": "深度评估失败",
    }

    tool = _FeishuTool()
    monkeypatch.setattr(workflow, "deep_evaluate_resume", lambda *a, **k: (partial, {}))
    monkeypatch.setattr(workflow, "update_feishu_status", tool)
    monkeypatch.setattr(workflow, "_get_eval_semaphore", lambda: asyncio.Semaphore(1))

    result = asyncio.run(workflow.deep_eval_node(_base_state()))

    assert result["deep_diagnosis"] == {
        "dream_picture": "有效画像",
        "strong_fit_assessment": "有效匹配点",
    }
    assert tool.writes[0]["updates"] == {
        "理想画像与能力信号": "有效画像",
        "高杠杆匹配点": "有效匹配点",
    }


def test_rewrite_node_consumes_deep_diagnosis_without_rerunning_deep_eval(monkeypatch):
    """改写/话术只消费深评结果，绝不重复深评。"""
    deep = {"dream_picture": "画像", "strong_fit_assessment": "匹配点"}
    captured = {}

    def fake_rewrite(**kwargs):
        captured["rewrite_diagnosis"] = kwargs["diagnosis_dict"]
        captured["rewrite_jd"] = kwargs["jd_text"]
        return "# 定制简历", {}

    def fake_greeting(_jd_text, diagnosis_dict, _resume_text, _job_name=""):
        captured["greeting_diagnosis"] = diagnosis_dict
        return "您好，我非常匹配该岗位。", {}

    def bomb_deep(*_args, **_kwargs):
        raise AssertionError("rewrite_node 不得重复调用 deep_evaluate_resume")

    tool = _FeishuTool()
    monkeypatch.setattr(workflow, "deep_evaluate_resume", bomb_deep)
    monkeypatch.setattr(workflow, "process_resume_rewrite", fake_rewrite)
    monkeypatch.setattr(workflow, "process_greeting_generation", fake_greeting)
    monkeypatch.setattr(workflow, "get_autopilot_config", lambda: {"rewrite_skill_id": "custom_skill"})
    monkeypatch.setattr(workflow, "update_feishu_status", tool)
    monkeypatch.setattr("ai_agents.markdown_to_json.parse_markdown_to_json", lambda md: {})

    state = _base_state(deep_diagnosis=deep)
    result = asyncio.run(workflow.rewrite_node(state))

    assert captured["rewrite_diagnosis"] == deep
    assert captured["greeting_diagnosis"] == deep
    assert "薪资范围: 30-50K" in captured["rewrite_jd"], "改写应拿到全景 JD 上下文"
    assert result["status"] == "简历人工复核"
    assert result["final_markdown"] == "# 定制简历"


def test_rewrite_node_old_checkpoint_falls_back_without_deep_eval(monkeypatch):
    """旧 checkpoint 没有 deep_diagnosis：回退初评数据，仍不得补跑深评。"""
    captured = {}

    def fake_rewrite(**kwargs):
        captured["diagnosis"] = kwargs["diagnosis_dict"]
        return "# 旧检查点简历", {}

    def bomb_deep(*_args, **_kwargs):
        raise AssertionError("旧 checkpoint 兼容路径也不得补跑深评")

    tool = _FeishuTool()
    monkeypatch.setattr(workflow, "deep_evaluate_resume", bomb_deep)
    monkeypatch.setattr(workflow, "process_resume_rewrite", fake_rewrite)
    monkeypatch.setattr(workflow, "process_greeting_generation", lambda *a, **k: ("您好", {}))
    monkeypatch.setattr(workflow, "get_autopilot_config", lambda: {"rewrite_skill_id": "custom_skill"})
    monkeypatch.setattr(workflow, "update_feishu_status", tool)
    monkeypatch.setattr("ai_agents.markdown_to_json.parse_markdown_to_json", lambda md: {})

    asyncio.run(workflow.rewrite_node(_base_state()))

    assert captured["diagnosis"] == _base_state()["diagnosis_dict"]
