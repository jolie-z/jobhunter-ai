"""
简历改写「项目经历整块丢失」回归（2026-10-23 真机工单）

病灶（证据链全部在源码核实）：
1. skill_rewrite.py 改写调用 max_tokens=8192 写死；deepseek-v4.1-flash 推理模型思考计入
   输出预算，带画像+诊断注入的长输入下思考+正文触顶，产物在第三段工作经历中途截断
   （真机 token_log completion 精准=8192，归档产物以「出具客观」半句话收尾）。
2. 截断 → <FINAL_RESUME> 只有开标签 → 提取正则失配 → 旧兜底把含 <THINKING> 的残缺全文
   当正文（THINKING 块从不剔除）。
3. 全程无 finish_reason 检查；markdown_to_json 解析残缺 Markdown 得 projects/education
   为空的 JSON；skill_rewrite_and_save 无对账无条件写回「结构化数据」，清空了 4 个项目经历
   + 教育背景（改写前备份在 resume_backups/ 尚存，可恢复）。
   ——与 2026-10-22 A级画像「AI 返回空内容」同根：推理模型思考耗尽输出预算的第二次发作。

修复锁定（按类修复，非单点）：
A. skill_rewrite：max_tokens 32768 + 默认关思考（网关拒参降级重发）；finish_reason=length
   显式失败；THINKING 无条件剔除；<FINAL_RESUME> 有头无尾显式失败。
B. markdown_to_json：关思考 + 拒参降级；截断归因进 error 文案。
C. skill_agent_router 写回保底闸（API/异步双通道）：解析 error 键与模块清零（原非空→空）
   一律拒绝落盘。
"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from ai_agents import skill_rewrite
from ai_agents.markdown_to_json import parse_markdown_to_json
from app.strategy.routes.skill_agent_router import _guard_parsed_resume


def _resp(content: str, finish_reason: str = "stop", reasoning: str = ""):
    return SimpleNamespace(
        choices=[SimpleNamespace(
            message=SimpleNamespace(content=content, reasoning_content=reasoning),
            finish_reason=finish_reason,
        )],
        usage=SimpleNamespace(
            prompt_tokens=10, completion_tokens=5, total_tokens=15, prompt_tokens_details=None,
        ),
    )


class _FakeLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    @property
    def chat(self):
        return SimpleNamespace(completions=SimpleNamespace(create=self._create))


def _run_rewrite():
    events = []
    return skill_rewrite.run_skill_based_rewrite(
        original_resume="# 母本简历", jd_text="JD", diagnosis_dict={}, job_name="测试岗",
        skill_id="resume_rewrite", on_event=lambda t, d: events.append(t),
    )


def _patch_client(monkeypatch, fake):
    monkeypatch.setattr(skill_rewrite, "get_openai_client", lambda: fake)


# ───────────────── A. skill_rewrite 截断/思考防护 ─────────────────

def test_length_truncation_fails_explicitly(monkeypatch):
    """finish_reason=length：即使 content 非空（半截简历）也必须拒绝，绝不进入解析写回。"""
    _patch_client(monkeypatch, _FakeLLM([
        _resp("<THINKING>x</THINKING>\n<FINAL_RESUME>\n# 简历前半段", finish_reason="length")
    ]))
    final_md, _ = _run_rewrite()
    assert final_md.startswith("❌")
    assert "截断" in final_md and "finish_reason=length" in final_md


def test_unclosed_final_resume_tag_fails_explicitly(monkeypatch):
    """定稿标签有头无尾 = 截断铁证：不再静默把残缺全文当正文。"""
    _patch_client(monkeypatch, _FakeLLM([
        _resp("<THINKING>思考</THINKING>\n<FINAL_RESUME>\n# 半截简历内容没有闭合标签")
    ]))
    final_md, _ = _run_rewrite()
    assert final_md.startswith("❌")
    assert "未闭合" in final_md


def test_thinking_block_never_leaks_without_final_tag(monkeypatch):
    """无标签输出走旧兜底时，THINKING 块必须先被剔除（含未闭合形态）。"""
    _patch_client(monkeypatch, _FakeLLM([
        _resp("<THINKING>秘密推演过程</THINKING>\n```markdown\n# 正式简历\n- 内容\n```")
    ]))
    final_md, _ = _run_rewrite()
    assert not final_md.startswith("❌")
    assert "秘密推演过程" not in final_md
    assert "正式简历" in final_md


def test_unterminated_thinking_block_stripped_on_truncation(monkeypatch):
    """截断时 THINKING 可能只有开标签：剔除正则必须兜到行尾。"""
    _patch_client(monkeypatch, _FakeLLM([
        _resp("<THINKING>没收尾的思考流", finish_reason="length")
    ]))
    final_md, _ = _run_rewrite()
    assert final_md.startswith("❌")  # length 截断先拦


def test_unterminated_thinking_block_stripped_on_normal_stop(monkeypatch):
    """【R1-P2】finish_reason=stop 但 THINKING 只有开标签（忘闭合）且后随正文：
    剔除正则的 `$` 分支删到串尾（不合规输出宁可整段作废），正文随之清空 →
    显式走「空内容」失败，绝不让思考流混入正文流转。"""
    _patch_client(monkeypatch, _FakeLLM([
        _resp("<THINKING>没收尾的思考流\n# 正式简历正文\n- 内容A")
    ]))
    final_md, _ = _run_rewrite()
    assert final_md.startswith("❌"), "未闭合 THINKING 属不合规输出：宁失败不脏数据"
    assert "思考流" not in final_md


def test_max_tokens_raised_and_thinking_disabled_by_default(monkeypatch):
    """提额 32768 + 默认关思考（推理模型思考烧输出预算是本工单根因）。"""
    fake = _FakeLLM([
        _resp("<THINKING>t</THINKING>\n<FINAL_RESUME>\n# 定稿\n- 熟练掌握 Python\n</FINAL_RESUME>")
    ])
    _patch_client(monkeypatch, fake)
    final_md, _ = _run_rewrite()
    assert not final_md.startswith("❌")
    assert fake.calls[0]["max_tokens"] == 32768
    assert fake.calls[0]["extra_body"] == {"thinking": {"type": "disabled"}}


def test_gateway_rejecting_thinking_param_degrades(monkeypatch):
    """网关不认顶层 thinking 参数（400 含字样）→ 去掉后重发一次成功。"""
    fake = _FakeLLM([
        Exception("400 Invalid parameter: 'thinking' not supported"),
        _resp("<FINAL_RESUME>\n# 定稿\n</FINAL_RESUME>"),
    ])
    _patch_client(monkeypatch, fake)
    final_md, _ = _run_rewrite()
    assert not final_md.startswith("❌")
    assert len(fake.calls) == 2
    assert "extra_body" in fake.calls[0] and "extra_body" not in fake.calls[1]


def test_empty_content_with_length_reason_names_cause(monkeypatch):
    _patch_client(monkeypatch, _FakeLLM([_resp("", finish_reason="length")]))
    final_md, _ = _run_rewrite()
    assert final_md.startswith("❌") and "截断" in final_md


def test_normal_tagged_output_still_works(monkeypatch):
    """回归：合法带标签输出的主路径行为不变（标签内正文 + THINKING 不混入）。"""
    _patch_client(monkeypatch, _FakeLLM([
        _resp("<THINKING>内部推演</THINKING>\n<FINAL_RESUME>\n# 定稿简历\n- 熟练掌握 Python\n</FINAL_RESUME>")
    ]))
    final_md, usage = _run_rewrite()
    assert not final_md.startswith("❌")
    assert "定稿简历" in final_md and "内部推演" not in final_md
    assert usage["total_tokens"] == 15


# ───────────────── B. markdown_to_json 防护 ─────────────────

def _patch_m2j(monkeypatch, fake):
    import ai_agents.markdown_to_json as m2j
    monkeypatch.setattr(m2j, "get_openai_client", lambda: fake)


def test_m2j_disables_thinking_and_degrades_on_rejection(monkeypatch):
    fake = _FakeLLM([
        Exception("400 unknown parameter thinking"),
        _resp('{"summary": "ok", "workExperience": [], "personalProjects": [], "education": []}'),
    ])
    _patch_m2j(monkeypatch, fake)
    result = parse_markdown_to_json("# 简历")
    assert "error" not in result
    assert len(fake.calls) == 2
    assert fake.calls[0]["extra_body"] == {"thinking": {"type": "disabled"}}
    assert "extra_body" not in fake.calls[1]


def test_m2j_truncated_json_error_names_length(monkeypatch):
    fake = _FakeLLM([_resp('{"summary": "半截', finish_reason="length")])
    _patch_m2j(monkeypatch, fake)
    result = parse_markdown_to_json("# 简历")
    assert result.get("error") and "截断" in result["error"] and "finish_reason=length" in result["error"]


def test_m2j_empty_content_with_length_returns_attribution_error(monkeypatch):
    """【R1-P2】content 空 + length：不得用 "{}" 兜底静默返回空结构吞掉截断归因。"""
    fake = _FakeLLM([_resp("", finish_reason="length")])
    _patch_m2j(monkeypatch, fake)
    result = parse_markdown_to_json("# 简历")
    assert result.get("error") and "截断" in result["error"]


# ───────────────── C. 写回对账保底闸 ─────────────────

_SRC = {
    "workExperience": [{"title": "A"}, {"title": "B"}, {"title": "C"}],
    "personalProjects": [{"name": "P1"}, {"name": "P2"}, {"name": "P3"}, {"name": "P4"}],
    "education": [{"institution": "X大"}],
}


def test_guard_rejects_parser_error_dict():
    with pytest.raises(ValueError, match="解析失败"):
        _guard_parsed_resume(_SRC, {"error": "boom", "original_markdown": "x"})


def test_guard_rejects_module_wipeout():
    """真机事故复刻：4 个项目经历被清零 → 必须拒绝写回。"""
    wiped = dict(_SRC, personalProjects=[], education=[])
    with pytest.raises(ValueError) as exc:
        _guard_parsed_resume(_SRC, wiped)
    msg = str(exc.value)
    assert "项目经历" in msg and "教育背景" in msg and "已拒绝写回" in msg


def test_guard_allows_legitimate_trim():
    """剧本允许按岗位相关性合理裁剪：4→2、教育保留 → 放行。"""
    trimmed = dict(_SRC, personalProjects=_SRC["personalProjects"][:2])
    _guard_parsed_resume(_SRC, trimmed)  # 不抛即通过


def test_guard_skips_when_no_source_structured():
    """岗位链路无原结构化数据（None/空串/非法 JSON）→ 跳过对账，不误伤。"""
    _guard_parsed_resume(None, {"personalProjects": []})
    _guard_parsed_resume("", {"personalProjects": []})
    _guard_parsed_resume("not-json{{", {"personalProjects": []})
    _guard_parsed_resume(_SRC, "not-a-dict")  # 解析结果异常形态同样跳过


# ───────────────── 贯穿真实 router 链路的对账闸验证（R1-P1 反驳证据）─────────────────

@pytest.mark.asyncio
async def test_api_pipeline_guard_receives_real_source_and_blocks_wipeout(monkeypatch):
    """端到端：简历库模式走 skill_rewrite_and_save_api 真实链路（mock 到 LLM/飞书边界），
    证明 src_dict 从真实飞书记录接线到保底闸——改写结果清零项目经历时拒绝写回。"""
    import json as _json

    from fastapi import HTTPException

    from app.strategy.routes import skill_agent_router as sar

    src_payload = _json.dumps({
        "personalInfo": {"name": "张三"},
        "workExperience": [{"title": "A"}, {"title": "B"}, {"title": "C"}],
        "personalProjects": [{"name": "P1"}, {"name": "P2"}, {"name": "P3"}, {"name": "P4"}],
        "education": [{"institution": "X大"}],
    }, ensure_ascii=False)

    async def fake_get_record(table_id, record_id):
        return {"fields": {"结构化数据": src_payload}}

    monkeypatch.setattr(sar.feishu_client, "get_record", fake_get_record)

    def fake_rewrite(**kwargs):
        from ai_agents.engine_facade import RewriteResult
        return RewriteResult(
            markdown="# 完整改写产物（本测试由 parse 层直接注入清零结果）",
            usage={"total_tokens": 1},
            engine="official",
        )

    monkeypatch.setattr(
        "app.strategy.skill_rewrite_service.process_resume_rewrite_detailed", fake_rewrite
    )

    def fake_parse(md):
        # 真机事故形态复刻：解析「成功」但 projects/education 被清零（error 键拦不住的形态）
        return {"summary": "s", "workExperience": [], "personalProjects": [], "education": []}

    monkeypatch.setattr("app.strategy.skill_rewrite_service.parse_markdown_to_json", fake_parse)

    payload = sar.SkillRewriteAndSaveRequest(resume_record_id="recTEST123", jd_text="A级岗位画像")
    with pytest.raises(HTTPException) as exc:
        await sar.skill_rewrite_and_save_api(payload)

    assert exc.value.status_code == 422
    assert "项目经历" in str(exc.value.detail) and "已拒绝写回" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_api_pipeline_guard_passes_complete_rewrite_end_to_end(monkeypatch):
    """对照：完整改写（4 项目保留）穿透真实链路直到飞书写回调用（证明闸不误伤）。"""
    import json as _json

    from app.strategy.routes import skill_agent_router as sar

    src_payload = _json.dumps({
        "personalInfo": {"name": "张三"},
        "workExperience": [{"title": "A"}, {"title": "B"}],
        "personalProjects": [{"name": "P1"}, {"name": "P2"}, {"name": "P3"}, {"name": "P4"}],
        "education": [{"institution": "X大"}],
    }, ensure_ascii=False)
    written: dict = {}

    async def fake_get_record(table_id, record_id):
        return {"fields": {"结构化数据": src_payload}}

    async def fake_update_record(table_id, record_id, fields):
        written["fields"] = fields
        return True

    monkeypatch.setattr(sar.feishu_client, "get_record", fake_get_record)
    monkeypatch.setattr(sar.feishu_client, "update_record", fake_update_record)

    def fake_rewrite(**kwargs):
        from ai_agents.engine_facade import RewriteResult
        return RewriteResult(
            markdown="# 完整改写产物",
            usage={"total_tokens": 1},
            engine="official",
        )

    monkeypatch.setattr(
        "app.strategy.skill_rewrite_service.process_resume_rewrite_detailed", fake_rewrite
    )

    def fake_parse(md):
        return {
            "summary": "s",
            "workExperience": [{"title": "A"}, {"title": "B"}],
            "personalProjects": [{"name": "P1"}, {"name": "P2"}, {"name": "P3"}, {"name": "P4"}],
            "education": [{"institution": "X大"}],
        }

    monkeypatch.setattr("app.strategy.skill_rewrite_service.parse_markdown_to_json", fake_parse)
    monkeypatch.setattr(
        "app.strategy.skill_rewrite_service.save_skill_result",
        lambda **kwargs: {"success": True},
    )

    payload = sar.SkillRewriteAndSaveRequest(resume_record_id="recTEST456", jd_text="A级岗位画像")
    res = await sar.skill_rewrite_and_save_api(payload)

    assert res["status"] == "success"
    assert written["fields"].get("结构化数据"), "完整改写必须正常写回（闸不误伤）"
