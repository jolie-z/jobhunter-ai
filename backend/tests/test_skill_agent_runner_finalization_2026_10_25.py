"""渐进式技能智能体定稿/截断回归（2026-10-25 工单）。

锁定：
1. finish_reason=length 的轮次整轮作废，不执行半截 tool_calls；
2. 01-05 后 LLM 报错，05_resume_polish 绝不升级为定稿；
3. 01-03 后 LLM 报错，03_truth_boundary 绝不升级为定稿；
4. 06 有效但其余产物缺失 → partial=True（上层按部分成功写回）；
5. 非 06 产物上的 is_final_resume=True 被忽略；
6. runner 不再自行写磁盘（产物只随返回值交给 router）。
"""

import json
from types import SimpleNamespace
from unittest.mock import patch

from ai_agents.skills import skill_agent_runner as sar


RESUME = """# 张三 - AI 工程师
## 个人优势
- 熟练掌握 Python、LangGraph、RAG 与 Agent 工具调用，具备从原型到生产的完整落地经验。
- 熟悉评测体系、Prompt 工程与结构化输出治理，能够独立承担复杂业务链路。
## 工作经历
- 某科技公司 AI 工程师：负责 Agent 工作流编排、工具调用协议与评测体系建设，支撑日均万级请求。
- 主导简历改写智能体的多轮推演与产物归档链路，完成截断检测、失败重试与写回对账保护。
## 项目经历
- 智能求职助手：设计多轮工具调用、参考资料检索与简历改写流水线，显著提升投递转化率。
- 企业知识库问答：搭建检索增强生成链路，优化召回与重排策略，降低幻觉率并提升回答可追溯性。
## 教育背景
- 某大学 计算机科学与技术 本科
## 专业技能
- Python / TypeScript / LangGraph / OpenAI Function Calling / RAG / 数据分析
"""


def _resp(content="", tool_calls=None, finish="stop"):
    msg = SimpleNamespace(content=content, tool_calls=tool_calls or [], reasoning_content="")
    return SimpleNamespace(
        choices=[SimpleNamespace(message=msg, finish_reason=finish)],
        usage=SimpleNamespace(
            prompt_tokens=10,
            completion_tokens=20,
            total_tokens=30,
            prompt_tokens_details=None,
        ),
    )


def _save(filename, content, title="阶段产物", is_final=False, call_id="call_save"):
    return SimpleNamespace(
        id=call_id,
        type="function",
        function=SimpleNamespace(
            name="save_step_artifact",
            arguments=json.dumps({
                "filename": filename,
                "title": title,
                "markdown_content": content,
                "is_final_resume": is_final,
            }, ensure_ascii=False),
        ),
    )


class _FakeLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    @property
    def chat(self):
        return SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _run(responses, max_turns=16, on_event=None, contract=None):
    llm = _FakeLLM(responses)
    with patch.object(sar, "get_openai_client", lambda *a, **k: llm):
        return sar.run_progressive_skill_agent(
            skill_id="test_package_skill",
            main_skill_content="# SOP",
            reference_map={"references/01.md": "# 规范"},
            original_resume="原简历",
            jd_text="JD",
            job_record_id="test_finalization_job",
            max_turns=max_turns,
            contract=contract,
            on_event=on_event,
        )


def _names(result):
    return [a["name"] for a in result.artifacts]


def test_truncated_narration_not_final():
    """截断的过渡语 + 后续空回复 → 失败，绝不生成 06。"""
    events = []
    result = _run(
        [
            _resp("我已阅读 JD 分析、材料审计、真实性边界……现在按 SOP 逐阶段落盘。", finish="length"),
            _resp(""),
            _resp(""),
        ],
        on_event=lambda t, d: events.append((t, d)),
    )
    assert result.markdown == ""
    assert result.artifacts == []
    assert result.partial is False
    assert "过程性文字" in result.error_reason or "截断" in result.error_reason
    assert not any(t == "agent_done" and d.get("status") == "success" for t, d in events)
    assert any(t == "agent_error" for t, d in events)


def test_truncated_turn_tool_calls_discarded():
    """finish_reason=length 时本轮 tool_calls 整轮作废，下一轮重新完整保存。"""
    events = []
    result = _run(
        [
            _resp("保存 01", [_save("01_jd_analysis.md", "SHOULD_NOT_SAVE", call_id="call_trunc")], finish="length"),
            _resp("保存 06", [_save("06_targeted_resume.md", RESUME, is_final=True, call_id="call_06")]),
            _resp(f"<FINAL_RESUME>\n{RESUME}\n</FINAL_RESUME>"),
        ],
        on_event=lambda t, d: events.append((t, d)),
    )
    assert "01_jd_analysis.md" not in _names(result), "截断轮的工具调用不得执行"
    assert result.markdown == RESUME.strip()
    assert result.artifact_count == 1
    assert any(t == "thinking" and d.get("stage") == "truncation" for t, d in events)


def test_01_05_then_error_does_not_promote_05():
    """Opus 路径 A：01-05 后 LLM 报错，05_resume_polish 不得当定稿。"""
    saves = [
        _save("01_jd_analysis.md", "01 内容", call_id="c1"),
        _save("02_materials_audit.md", "02 内容", call_id="c2"),
        _save("03_truth_boundary.md", "03 内容", call_id="c3"),
        _save("04_evidence_contract.md", "04 内容", call_id="c4"),
        _save("05_resume_polish.md", RESUME, is_final=True, call_id="c5"),
    ]
    result = _run([_resp("保存阶段产物", saves), RuntimeError("gateway down")])
    assert result.markdown == ""
    assert "06_targeted_resume.md" not in _names(result)
    assert result.partial is False
    assert result.error_reason


def test_01_03_then_error_does_not_promote_03():
    """Opus 路径 B：01-03 后 LLM 报错，03_truth_boundary 不得当定稿。"""
    saves = [
        _save("01_jd_analysis.md", "01 内容", call_id="c1"),
        _save("02_materials_audit.md", "02 内容", call_id="c2"),
        _save("03_truth_boundary.md", "03 内容", call_id="c3"),
    ]
    result = _run([_resp("保存阶段产物", saves), RuntimeError("gateway down")])
    assert result.markdown == ""
    assert result.artifacts and all(a["name"] != "06_targeted_resume.md" for a in result.artifacts)
    assert result.error_reason


def test_is_final_flag_on_05_ignored():
    """非 06 产物上的 is_final_resume=True 只记警告，不升级为定稿。"""
    result = _run([
        _resp("保存 05", [_save("05_resume_polish.md", RESUME, is_final=True)]),
        RuntimeError("gateway down"),
    ])
    assert result.markdown == ""
    assert "06_targeted_resume.md" not in _names(result)


def test_06_valid_partial_success():
    """06 有效 + 其余产物缺失 → partial=True，markdown 为 06。"""
    events = []
    result = _run(
        [
            _resp("保存 06", [_save("06_targeted_resume.md", RESUME, is_final=True)]),
            _resp("已完成"),
        ],
        on_event=lambda t, d: events.append((t, d)),
    )
    assert result.markdown == RESUME.strip()
    assert result.partial is True
    assert result.artifact_count == 1
    assert "1/11" in result.error_reason
    done = [d for t, d in events if t == "agent_done"]
    assert done and done[-1]["status"] == "partial"


def test_06_invalid_fails():
    """06 只有过渡语 → 拒绝保存；无其他定稿 → 失败。"""
    result = _run([
        _resp("保存 06", [_save("06_targeted_resume.md", "我已阅读 JD 分析……现在按 SOP 逐阶段落盘。")]),
        RuntimeError("gateway down"),
    ])
    assert result.markdown == ""
    assert result.artifacts == []
    assert result.partial is False


def test_duplicate_06_keeps_latest_valid():
    """重复保存 06：后一次无效时保留前一次有效版本。"""
    result = _run([
        _resp("保存 06 v1", [_save("06_targeted_resume.md", RESUME, call_id="c1")]),
        _resp("覆盖 06 v2", [_save("06_targeted_resume.md", "SHORT", call_id="c2")]),
        _resp("done"),
    ])
    assert result.markdown == RESUME.strip()
    assert result.artifact_count == 1


def test_continuation_counter_resets_after_tool_turn():
    """连续追问计数在工具轮清零：早期“只说话”不应永久占用后续额度。"""
    result = _run([
        _resp("我先看一下规范"),
        _resp("保存 01", [_save("01_jd_analysis.md", "01", call_id="c1")]),
        _resp("继续"),
        _resp("保存 06", [_save("06_targeted_resume.md", RESUME, call_id="c2")]),
        _resp("done"),
    ])
    assert result.markdown == RESUME.strip()
    assert result.partial is True


def test_max_turns_with_valid_06_partial():
    """轮次耗尽但 06 有效 → 部分成功，不判失败。"""
    result = _run(
        [_resp("保存 06", [_save("06_targeted_resume.md", RESUME)])],
        max_turns=1,
    )
    assert result.markdown == RESUME.strip()
    assert result.partial is True


def test_all_artifacts_complete_with_late_error_is_success():
    """11 份产物已齐、06 有效，尾声报错不降级为部分成功。"""
    files = [
        ("01_jd_analysis.md", "01"),
        ("02_materials_audit.md", "02"),
        ("03_truth_boundary.md", "03"),
        ("04_evidence_contract.md", "04"),
        ("05_resume_polish.md", "05"),
        ("06_targeted_resume.md", RESUME),
        ("07_interview_grilling.md", "07"),
        ("08_answer_cards.md", "08"),
        ("09_upgrade_plan.md", "09"),
        ("10_project_scout.md", "10"),
        ("11_final_pack.md", "11"),
    ]
    saves = [_save(name, content, call_id=f"c{i}") for i, (name, content) in enumerate(files)]
    result = _run([_resp("保存全部产物", saves), RuntimeError("late gateway error")])
    assert result.markdown == RESUME.strip()
    assert result.artifact_count == 11
    assert result.partial is False
    assert result.error_reason == ""


def test_truncation_exhaustion_with_valid_06_partial():
    """06 已有效后连续截断耗尽 → 部分成功。"""
    result = _run([
        _resp("保存 06", [_save("06_targeted_resume.md", RESUME)]),
        _resp("", finish="length"),
        _resp("", finish="length"),
        _resp("", finish="length"),
    ])
    assert result.markdown == RESUME.strip()
    assert result.partial is True
    assert "截断" in result.error_reason


def test_empty_artifact_rejected():
    """空产物拒绝保存，不影响后续 06。"""
    result = _run([
        _resp("保存空 01", [_save("01_jd_analysis.md", "", call_id="c1")]),
        _resp("保存 06", [_save("06_targeted_resume.md", RESUME, call_id="c2")]),
        _resp("done"),
    ])
    assert "01_jd_analysis.md" not in _names(result)
    assert "06_targeted_resume.md" in _names(result)
    assert result.markdown == RESUME.strip()


def test_plain_text_resume_fallback():
    """无标签但内容通过简历校验：允许作为定稿并补 06（旧兜底的安全版本）。"""
    result = _run([_resp(RESUME)])
    assert result.markdown == RESUME.strip()
    assert "06_targeted_resume.md" in _names(result)
    assert result.partial is True


def test_english_resume_fallback_accepted():
    """内容校验支持英文模块名，避免英文简历被误杀。"""
    en_resume = """# John Doe - AI Engineer
## Summary
AI engineer with 6 years of experience building LLM applications, agent workflows and evaluation systems.
## Work Experience
- Senior AI Engineer at Acme Corp: led the design of a multi-turn agent platform and tool-calling protocol.
- Built structured output validation and truncation recovery for a resume rewriting pipeline.
## Projects
- Job Hunter Assistant: designed retrieval-augmented generation, tool calling and multi-artifact delivery.
- Enterprise Knowledge Base: improved recall and reranking, reducing hallucination rate.
## Education
- B.S. in Computer Science, Example University
## Skills
- Python / TypeScript / LangGraph / RAG / OpenAI Function Calling
"""
    result = _run([_resp(en_resume)])
    assert result.markdown == en_resume.strip()
    assert "06_targeted_resume.md" in _names(result)
    assert result.partial is True


def test_unclosed_final_tag_not_accepted_as_plain_resume():
    """未闭合 <FINAL_RESUME> 即使正文很长也是截断铁证，不得走纯文本兜底。"""
    result = _run([
        _resp(f"<FINAL_RESUME>\n{RESUME}\n"),
        _resp(""),
        _resp(""),
    ])
    assert result.markdown == ""
    assert "06_targeted_resume.md" not in _names(result)
    assert result.partial is False


def test_invalid_closed_final_tag_not_accepted_as_plain_resume():
    """闭合标签内容不合格（如以未完成标点结尾）时，不得把带标签的原始全文当正文。"""
    bad_inner = RESUME.rstrip() + "，"
    result = _run([
        _resp(f"<FINAL_RESUME>\n{bad_inner}\n</FINAL_RESUME>"),
        _resp(""),
        _resp(""),
    ])
    assert result.markdown == ""
    assert "06_targeted_resume.md" not in _names(result)
    assert result.partial is False


def test_model_call_uses_no_thinking_and_32768():
    """确认 agent 通道复用 10-23 的关思考 + 32768 预算。"""
    llm = _FakeLLM([_resp(RESUME)])
    with patch.object(sar, "get_openai_client", lambda *a, **k: llm):
        sar.run_progressive_skill_agent(
            skill_id="test_package_skill",
            main_skill_content="# SOP",
            reference_map={},
            original_resume="原简历",
            jd_text="JD",
            job_record_id="test_finalization_job",
            max_turns=1,
        )
    call = llm.calls[0]
    assert call["max_tokens"] == 32768
    assert call["extra_body"] == {"thinking": {"type": "disabled"}}


COVER = """# 求职信

尊敬的招聘经理：

您好！我是一名具备六年 AI 工程经验的候选人，长期负责大模型应用、Agent 工作流与检索增强生成系统的设计与落地。在过往项目中，我主导了多轮工具调用协议、评测体系与结构化输出治理，能够独立承担从需求分析到上线运维的完整链路。

我关注贵司在智能招聘与人才匹配方向的产品实践，也希望将自己在简历解析、岗位匹配与自动化投递方面的经验带入团队。期待有机会与您进一步交流。

此致
敬礼
"""


def _contract(outputs, final=None, kind="markdown", expected=None, has_resume=False):
    return {
        "engine": "agent",
        "output_kind": kind,
        "final_artifact": final,
        "postprocess": "markdown_only" if kind != "resume" else "resume_json",
        "writeback": "none" if kind != "resume" else "resume_or_job",
        "outputs": [
            {
                "filename": name,
                "title": name,
                "required": True,
                "is_final": name == final,
                "kind": kind,
                "is_resume": False,
            }
            for name in outputs
        ],
        "expected_artifact_count": expected if expected is not None else len(outputs),
        "has_resume_output": has_resume,
        "warnings": [],
    }


def test_generic_contract_declared_final_accepted():
    """非简历 skill：契约声明的 final 文件可以正常成为交付物。"""
    contract = _contract(["01_analysis.md", "02_cover_letter.md"], final="02_cover_letter.md")
    result = _run([
        _resp("保存产物", [
            _save("01_analysis.md", "分析内容", call_id="c1"),
            _save("02_cover_letter.md", COVER, call_id="c2"),
        ]),
        _resp("完成"),
    ], contract=contract)
    assert result.markdown == COVER.strip()
    assert result.result_kind == "markdown"
    assert result.has_resume_output is False
    assert result.artifact_count == 2
    assert result.final_artifact == "02_cover_letter.md"
    assert result.partial is False


def test_generic_declared_final_missing_fails():
    """契约声明了 final，但模型没产出它：不得拿其他阶段产物顶替。"""
    contract = _contract(["01_analysis.md", "02_cover_letter.md"], final="02_cover_letter.md")
    result = _run([
        _resp("保存 01", [_save("01_analysis.md", "分析内容")]),
    ], max_turns=1, contract=contract)
    assert result.markdown == ""
    assert result.error_reason
    assert "02_cover_letter.md" in result.error_reason


def test_generic_no_declared_final_uses_last_valid():
    """契约未声明 final：允许取最后一份通过通用校验的产物。"""
    contract = _contract(["01_analysis.md", "02_cover_letter.md"], final=None)
    result = _run([
        _resp("保存产物", [
            _save("01_analysis.md", "分析内容", call_id="c1"),
            _save("02_cover_letter.md", COVER, call_id="c2"),
        ]),
        _resp("完成"),
    ], contract=contract)
    assert result.markdown == COVER.strip()
    assert result.result_kind == "markdown"
    assert result.artifact_count == 2
    assert result.final_artifact == "02_cover_letter.md"
    assert result.partial is False


def test_generic_partial_when_required_outputs_missing():
    """final 有效但声明产物缺失 → partial N/M。"""
    contract = _contract(
        ["01_analysis.md", "02_draft.md", "03_cover_letter.md"],
        final="03_cover_letter.md",
    )
    result = _run([
        _resp("保存 01+03", [
            _save("01_analysis.md", "分析内容", call_id="c1"),
            _save("03_cover_letter.md", COVER, call_id="c3"),
        ]),
        _resp("完成"),
    ], contract=contract)
    assert result.markdown == COVER.strip()
    assert result.partial is True
    assert result.artifact_count == 2
    assert "2/3" in result.error_reason


def test_generic_final_output_tag():
    """通用 skill 支持 <FINAL_OUTPUT> 标签，自动补一份 final_output.md。"""
    contract = _contract(["01_analysis.md"], final=None, expected=1)
    result = _run([
        _resp(f"<FINAL_OUTPUT>\n{COVER}\n</FINAL_OUTPUT>"),
    ], contract=contract)
    assert result.markdown == COVER.strip()
    assert "final_output.md" in _names(result)
    assert result.final_artifact == "final_output.md"
    assert result.partial is False


def test_generic_json_final():
    """JSON 产物按 JSON 校验，不要求简历模块。"""
    contract = _contract(["result.json"], final="result.json", kind="json", expected=1)
    payload = json.dumps({"cover_letter": COVER}, ensure_ascii=False)
    result = _run([
        _resp("保存 JSON", [_save("result.json", payload)]),
        _resp("完成"),
    ], contract=contract)
    assert result.markdown == payload.strip()
    assert result.result_kind == "json"
    assert result.partial is False


def test_generic_final_flag_on_other_file_ignored_when_final_declared():
    """契约已声明 final 时，其他文件上的 is_final_resume=True 不得抢定稿。"""
    contract = _contract(["01_analysis.md", "02_cover_letter.md"], final="02_cover_letter.md")
    result = _run([
        _resp("保存产物", [
            _save("01_analysis.md", "EARLY DRAFT", is_final=True, call_id="c1"),
            _save("02_cover_letter.md", COVER, call_id="c2"),
        ]),
        _resp("完成"),
    ], contract=contract)
    assert result.markdown == COVER.strip()


def test_generic_invalid_final_rejected():
    """契约 final 内容未通过通用校验 → 拒绝保存，整轮失败。"""
    contract = _contract(["01_analysis.md", "02_cover_letter.md"], final="02_cover_letter.md")
    result = _run([
        _resp("保存 02", [_save("02_cover_letter.md", "SHORT")]),
        _resp(""),
        _resp(""),
    ], contract=contract)
    assert result.markdown == ""
    assert result.partial is False


def test_resume_contract_without_final_accepts_is_final_flag():
    """简历类契约未声明 final 时，is_final_resume=True 必须能成为定稿（不得强求 06）。"""
    contract = {
        "engine": "agent",
        "output_kind": "resume",
        "final_artifact": None,
        "postprocess": "resume_json",
        "writeback": "resume_or_job",
        "outputs": [],
        "expected_artifact_count": 0,
        "has_resume_output": True,
        "warnings": [],
    }
    result = _run([
        _resp("保存简历", [_save("custom_resume.md", RESUME, is_final=True)]),
        _resp("完成"),
    ], contract=contract)
    assert result.markdown == RESUME.strip()
    assert result.final_artifact == "custom_resume.md"
    assert "06_targeted_resume.md" not in _names(result)
    assert result.partial is False
