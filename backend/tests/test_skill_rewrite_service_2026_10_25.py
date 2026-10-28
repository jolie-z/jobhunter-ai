"""Skill 改写共享流水线回归（2026-10-25 工单）。

覆盖：
1. 岗位模式只读一次启用简历，同一份底稿同时作为模型输入与对账基线；
2. 对账失败不归档、不写飞书；
3. 06 有效但其余产物缺失 → 部分成功写回 + partial meta；
4. 归档原子替换，旧文件不残留；
5. 归档失败时旧快照完整保留；
6. facade 2 元组兼容入口不被破坏；
7. 技能包 runner 失败不再静默回退官方引擎。
"""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from ai_agents.engine_facade import RewriteResult, process_resume_rewrite
from ai_agents.skills import skill_dirs
from app.strategy import skill_rewrite_service as svc
from app.strategy import skill_rewrite_preflight as preflight_mod


RESUME = """# 张三 - AI 工程师
## 个人优势
- 熟练掌握 Python、LangGraph、RAG 与 Agent 工具调用，具备从原型到生产的完整落地经验。
## 工作经历
- 某科技公司 AI 工程师：负责 Agent 工作流编排、工具调用协议与评测体系建设。
## 项目经历
- 智能求职助手：设计多轮工具调用、参考资料检索与简历改写流水线。
## 教育背景
- 某大学 计算机科学与技术 本科
## 专业技能
- Python / TypeScript / LangGraph / RAG / 数据分析
"""

SRC = {
    "personalInfo": {"name": "张三", "phone": "13800000000"},
    "workExperience": [{"title": "A"}, {"title": "B"}],
    "personalProjects": [{"name": "P1"}, {"name": "P2"}],
    "education": [{"institution": "X大"}],
}


def _payload(**overrides):
    base = dict(
        job_id="",
        resume_record_id="recResume1",
        jd_text="JD",
        job_name="测试岗",
        skill_id="custom_skill",
        include_diagnosis=True,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _resume_record(src=SRC):
    return {"fields": {"结构化数据": json.dumps(src, ensure_ascii=False)}}


@pytest.mark.asyncio
async def test_job_mode_context_uses_single_active_resume_for_model_and_guard():
    """岗位模式只读一次启用简历；模型输入与对账基线完全同源。"""
    calls = []

    def fake_get_full():
        calls.append(1)
        return json.dumps(SRC, ensure_ascii=False)

    payload = _payload(job_id="recJob1", resume_record_id=None)
    with patch.object(svc, "get_full_active_resume_from_feishu", fake_get_full), \
         patch.object(svc, "_load_job_diagnosis", AsyncMock(return_value=({"fields": {}}, {}))):
        ctx = await svc.resolve_context(payload)

    assert len(calls) == 1, "启用简历必须只读取一次"
    assert ctx.clean_id == "recJob1"
    assert ctx.personal_info == SRC["personalInfo"]
    assert ctx.src_struct is not None and "personalInfo" not in ctx.src_struct
    assert json.loads(ctx.original_resume_override) == {
        k: v for k, v in SRC.items() if k != "personalInfo"
    }


@pytest.mark.asyncio
async def test_guard_failure_blocks_archive_and_write():
    """解析结果清零原有模块 → 422 对账拦截；归档与飞书写回都不得发生。"""
    def fake_rewrite(**kwargs):
        return RewriteResult(markdown=RESUME, usage={"total_tokens": 1}, engine="agent")

    def fake_parse(md):
        return {
            "summary": "s",
            "workExperience": [{"title": "A"}],
            "personalProjects": [],
            "education": [],
        }

    with patch.object(svc.feishu_client, "get_record", AsyncMock(return_value=_resume_record())), \
         patch.object(svc, "process_resume_rewrite_detailed", fake_rewrite), \
         patch.object(svc, "parse_markdown_to_json", fake_parse), \
         patch.object(svc, "save_skill_result") as archive_mock, \
         patch.object(svc.feishu_client, "update_record") as update_mock:
        with pytest.raises(svc.SkillRewriteGuardError):
            await svc.run_skill_rewrite_pipeline(_payload())

    archive_mock.assert_not_called()
    update_mock.assert_not_called()


@pytest.mark.asyncio
async def test_partial_success_writes_back_and_archives():
    """06 有效 + 仅 2/11 产物 → partial 写回，归档带 partial meta。"""
    artifacts = [
        {"name": "06_targeted_resume.md", "content": RESUME},
        {"name": "01_jd_analysis.md", "content": "01 内容"},
    ]

    def fake_rewrite(**kwargs):
        return RewriteResult(
            markdown=RESUME,
            usage={"total_tokens": 10},
            artifacts=artifacts,
            partial=True,
            artifact_count=2,
            expected_artifact_count=11,
            engine="agent",
            error_reason="已生成 2/11 份产物",
        )

    def fake_parse(md):
        return {
            "summary": "s",
            "workExperience": [{"title": "A"}, {"title": "B"}],
            "personalProjects": [{"name": "P1"}, {"name": "P2"}],
            "education": [{"institution": "X大"}],
        }

    captured = {}

    def fake_archive(**kwargs):
        captured.update(kwargs)
        return {"success": True}

    written = {}

    async def fake_update(**kwargs):
        written.update(kwargs)
        return True

    with patch.object(svc.feishu_client, "get_record", AsyncMock(return_value=_resume_record())), \
         patch.object(svc, "process_resume_rewrite_detailed", fake_rewrite), \
         patch.object(svc, "parse_markdown_to_json", fake_parse), \
         patch.object(svc, "save_skill_result", fake_archive), \
         patch.object(svc.feishu_client, "update_record", fake_update):
        outcome = await svc.run_skill_rewrite_pipeline(_payload())

    assert outcome.partial is True
    assert outcome.artifact_count == 2
    assert outcome.persisted["ai_rewrite_json"] is True
    assert captured["replace_existing"] is True
    assert captured["meta_extra"]["partial"] is True
    assert captured["meta_extra"]["artifact_count"] == 2
    assert captured["meta_extra"]["expected_artifact_count"] == 11
    assert {f["name"] for f in captured["files"]} == {
        "06_targeted_resume.md", "01_jd_analysis.md"
    }
    assert written["fields"].get("结构化数据")
    assert outcome.parsed_json["personalInfo"]["name"] == "张三"


@pytest.mark.asyncio
async def test_engine_error_blocks_archive_and_write():
    """引擎返回 ❌ → 直接失败，不解析、不归档、不写回。"""
    def fake_rewrite(**kwargs):
        return RewriteResult(markdown="❌ 输出被截断", error_reason="输出被截断", engine="agent")

    with patch.object(svc.feishu_client, "get_record", AsyncMock(return_value=_resume_record())), \
         patch.object(svc, "process_resume_rewrite_detailed", fake_rewrite), \
         patch.object(svc, "parse_markdown_to_json") as parse_mock, \
         patch.object(svc, "save_skill_result") as archive_mock, \
         patch.object(svc.feishu_client, "update_record") as update_mock:
        with pytest.raises(svc.SkillRewriteEngineError):
            await svc.run_skill_rewrite_pipeline(_payload())

    parse_mock.assert_not_called()
    archive_mock.assert_not_called()
    update_mock.assert_not_called()


def test_atomic_archive_replaces_stale_files():
    """原子快照：上一次的多余文件必须被清掉，meta 与实际文件一致。"""
    job_id = "recAtomic20261025"
    try:
        skill_dirs.save_skill_result(
            job_record_id=job_id,
            skill_id="atomic_skill",
            files=[
                {"name": "01_a.md", "content": "old-a"},
                {"name": "02_b.md", "content": "old-b"},
                {"name": "03_c.md", "content": "old-c"},
            ],
            token_usage={"total_tokens": 1},
            replace_existing=True,
        )
        skill_dirs.save_skill_result(
            job_record_id=job_id,
            skill_id="atomic_skill",
            files=[{"name": "06_targeted_resume.md", "content": RESUME}],
            token_usage={"total_tokens": 2},
            replace_existing=True,
            meta_extra={
                "partial": True,
                "artifact_count": 1,
                "expected_artifact_count": 11,
                "engine": "agent",
            },
        )
        skill_dir = skill_dirs.get_skill_run_dir(job_id, "atomic_skill")
        names = sorted(p.name for p in skill_dir.glob("*.md"))
        assert names == ["06_targeted_resume.md"]
        meta = json.loads((skill_dir / "meta.json").read_text(encoding="utf-8"))
        assert meta["file_count"] == 1
        assert meta["partial"] is True
        assert meta["artifact_count"] == 1
        # meta 的文件路径必须指向最终目录，不能残留 staging 临时路径
        assert ".staging" not in meta["files"][0]["path"]
        assert meta["files"][0]["path"].endswith("atomic_skill/06_targeted_resume.md")
        items = skill_dirs.list_job_skill_artifacts(job_id, "atomic_skill")
        assert items and items[0]["partial"] is True
        assert items[0]["expected_artifact_count"] == 11
    finally:
        skill_dirs.delete_job_results(job_id)


def test_archive_failure_preserves_old_snapshot():
    """替换阶段失败时旧快照必须原样保留，staging 目录清理干净。"""
    job_id = "recAtomicFail20261025"
    try:
        skill_dirs.save_skill_result(
            job_record_id=job_id,
            skill_id="atomic_skill",
            files=[{"name": "06_targeted_resume.md", "content": "OLD"}],
            token_usage={"total_tokens": 1},
        )
        with patch.object(
            skill_dirs, "_atomic_replace_directory", side_effect=RuntimeError("swap failed")
        ):
            with pytest.raises(RuntimeError):
                skill_dirs.save_skill_result(
                    job_record_id=job_id,
                    skill_id="atomic_skill",
                    files=[{"name": "06_targeted_resume.md", "content": "NEW"}],
                    token_usage={"total_tokens": 2},
                    replace_existing=True,
                )
        skill_dir = skill_dirs.get_skill_run_dir(job_id, "atomic_skill")
        assert (skill_dir / "06_targeted_resume.md").read_text(encoding="utf-8") == "OLD"
        assert not list(skill_dir.parent.glob(".atomic_skill.staging-*"))
    finally:
        skill_dirs.delete_job_results(job_id)


def test_two_tuple_facade_still_compatible():
    """8 处旧调用依赖的 2 元组入口必须保持不变。"""
    def fake_detailed(**kwargs):
        return RewriteResult(markdown="# 定稿", usage={"total_tokens": 3}, engine="official")

    with patch("ai_agents.engine_facade.process_resume_rewrite_detailed", fake_detailed):
        markdown, usage = process_resume_rewrite(
            jd_text="JD",
            diagnosis_dict={},
            original_resume_override="原简历",
        )
    assert markdown == "# 定稿"
    assert usage["total_tokens"] == 3


def test_agent_runner_failure_does_not_fall_back_to_official():
    """技能包 runner 抛异常 → 显式失败，绝不静默回退官方引擎。"""
    from ai_agents import engine_facade

    fake_manager = SimpleNamespace(
        loaded_contents={"pkg": "# SOP"},
        reference_maps={"pkg": {}},
    )

    with patch.object(engine_facade, "resolve_rewrite_engine", return_value="agent"), \
         patch("ai_agents.skills.skill_loader.get_skill_manager", return_value=fake_manager), \
         patch("ai_agents.skills.skill_agent_runner.run_progressive_skill_agent",
               side_effect=RuntimeError("agent boom")), \
         patch.object(engine_facade, "run_skill_based_rewrite") as official_mock:
        result = engine_facade.process_resume_rewrite_detailed(
            jd_text="JD",
            diagnosis_dict={},
            original_resume_override="原简历",
            skill_id="pkg",
        )

    official_mock.assert_not_called()
    assert result.markdown.startswith("❌")
    assert "agent boom" in result.error_reason
    assert result.engine == "agent"


def test_detailed_maps_agent_result_fields():
    """facade detailed 必须完整透传 runner 的 artifacts/partial/engine。"""
    from ai_agents import engine_facade
    from ai_agents.skills.skill_agent_runner import ProgressiveAgentResult

    fake_manager = SimpleNamespace(
        loaded_contents={"pkg": "# SOP"},
        reference_maps={"pkg": {}},
    )
    agent_result = ProgressiveAgentResult(
        markdown=RESUME,
        usage={"total_tokens": 5},
        artifacts=[{"name": "06_targeted_resume.md", "content": RESUME}],
        partial=True,
        artifact_count=1,
        expected_artifact_count=11,
        engine="agent",
        error_reason="已生成 1/11 份产物",
    )

    with patch.object(engine_facade, "resolve_rewrite_engine", return_value="agent"), \
         patch("ai_agents.skills.skill_loader.get_skill_manager", return_value=fake_manager), \
         patch("ai_agents.skills.skill_agent_runner.run_progressive_skill_agent",
               return_value=agent_result):
        result = engine_facade.process_resume_rewrite_detailed(
            jd_text="JD",
            diagnosis_dict={},
            original_resume_override="原简历",
            skill_id="pkg",
        )

    assert result.markdown == RESUME
    assert result.partial is True
    assert result.artifact_count == 1
    assert result.expected_artifact_count == 11
    assert result.engine == "agent"
    assert result.artifacts[0]["name"] == "06_targeted_resume.md"


@pytest.mark.asyncio
async def test_sync_router_returns_partial_fields(monkeypatch):
    """同步接口的 data 必须带 partial/N/11，供前端展示部分成功。"""
    from app.strategy.routes import skill_agent_router as sar

    outcome = svc.SkillRewriteOutcome(
        markdown=RESUME,
        usage={"total_tokens": 1},
        parsed_json={"personalInfo": {}},
        artifacts=[{"name": "06_targeted_resume.md", "content": RESUME}],
        partial=True,
        artifact_count=1,
        expected_artifact_count=11,
        engine="agent",
        persisted={"ai_rewrite_json": True, "follow_status": None},
    )

    async def fake_pipeline(payload, on_event=None):
        return outcome

    monkeypatch.setattr(sar, "run_skill_rewrite_pipeline", fake_pipeline)
    res = await sar.skill_rewrite_and_save_api(
        sar.SkillRewriteAndSaveRequest(resume_record_id="recSmoke1", jd_text="JD")
    )
    assert res["status"] == "success"
    assert res["data"]["partial"] is True
    assert res["data"]["artifact_count"] == 1
    assert res["data"]["expected_artifact_count"] == 11
    assert res["data"]["engine"] == "agent"


@pytest.mark.asyncio
async def test_async_router_complete_payload_marks_partial(monkeypatch):
    """异步 SSE 的 complete 事件必须带 partial/N/11，且 status=partial。"""
    from app.jobs.task_manager import task_event_manager
    from app.strategy.routes import skill_agent_router as sar

    outcome = svc.SkillRewriteOutcome(
        markdown=RESUME,
        usage={"total_tokens": 1},
        parsed_json={"personalInfo": {}},
        artifacts=[{"name": "06_targeted_resume.md", "content": RESUME}],
        partial=True,
        artifact_count=1,
        expected_artifact_count=11,
        engine="agent",
        persisted={"ai_rewrite_json": True, "follow_status": None},
    )

    async def fake_pipeline(payload, on_event=None):
        return outcome

    monkeypatch.setattr(sar, "run_skill_rewrite_pipeline", fake_pipeline)
    monkeypatch.setattr(sar, "resolve_rewrite_engine", lambda _sid: "agent")

    resp = await sar.skill_rewrite_async_api(
        sar.SkillRewriteAndSaveRequest(resume_record_id="recSmoke2", jd_text="JD")
    )
    queue = task_event_manager.get_queue(resp["task_id"])
    events = []
    try:
        while True:
            event = await asyncio.wait_for(queue.get(), timeout=2)
            if event is None:
                break
            events.append(event)
    finally:
        task_event_manager.remove_task(resp["task_id"])

    complete = [e for e in events if e.get("type") == "complete"]
    assert complete, f"未收到 complete 事件: {events}"
    assert complete[-1]["status"] == "partial"
    assert complete[-1]["data"]["partial"] is True
    assert complete[-1]["data"]["artifact_count"] == 1
    assert complete[-1]["data"]["expected_artifact_count"] == 11


COVER = """# 求职信

尊敬的招聘经理：

您好！我是一名具备六年 AI 工程经验的候选人，长期负责大模型应用、Agent 工作流与检索增强生成系统的设计与落地。在过往项目中，我主导了多轮工具调用协议、评测体系与结构化输出治理，能够独立承担从需求分析到上线运维的完整链路。

我关注贵司在智能招聘与人才匹配方向的产品实践，也希望将自己在简历解析、岗位匹配与自动化投递方面的经验带入团队。期待有机会与您进一步交流。

此致
敬礼
"""

GENERIC_CONTRACT = {
    "engine": "agent",
    "output_kind": "markdown",
    "final_artifact": "02_cover_letter.md",
    "postprocess": "markdown_only",
    "writeback": "none",
    "outputs": [
        {"filename": "01_analysis.md", "title": "分析", "required": True, "is_final": False, "kind": "markdown", "is_resume": False},
        {"filename": "02_cover_letter.md", "title": "求职信", "required": True, "is_final": True, "kind": "markdown", "is_resume": False},
    ],
    "expected_artifact_count": 2,
    "has_resume_output": False,
    "resume_output_files": [],
    "output_count_source": "skill_md",
    "final_source": "final_marker",
    "warnings": [],
}


@pytest.mark.asyncio
async def test_generic_skill_archives_without_resume_write():
    """非简历 skill：只归档，不解析简历 JSON、不写飞书简历字段。"""
    def fake_rewrite(**kwargs):
        return RewriteResult(
            markdown=COVER,
            usage={"total_tokens": 10},
            artifacts=[
                {"name": "01_analysis.md", "content": "分析"},
                {"name": "02_cover_letter.md", "content": COVER},
            ],
            partial=False,
            artifact_count=2,
            expected_artifact_count=2,
            engine="agent",
            result_kind="markdown",
            has_resume_output=False,
            final_artifact="02_cover_letter.md",
        )

    captured = {}

    def fake_archive(**kwargs):
        captured.update(kwargs)
        return {"success": True}

    with patch.object(svc, "get_skill_contract", lambda _sid: GENERIC_CONTRACT), \
         patch.object(svc.feishu_client, "get_record", AsyncMock(return_value=_resume_record())), \
         patch.object(svc, "process_resume_rewrite_detailed", fake_rewrite), \
         patch.object(svc, "parse_markdown_to_json") as parse_mock, \
         patch.object(svc, "save_skill_result", fake_archive), \
         patch.object(svc.feishu_client, "update_record") as update_mock:
        outcome = await svc.run_skill_rewrite_pipeline(_payload())

    parse_mock.assert_not_called()
    update_mock.assert_not_called()
    assert outcome.result_kind == "markdown"
    assert outcome.has_resume_output is False
    assert outcome.parsed_json == {}
    assert outcome.persisted["ai_rewrite_json"] is False
    assert captured["meta_extra"]["result_kind"] == "markdown"
    assert captured["meta_extra"]["final_artifact"] == "02_cover_letter.md"
    assert outcome.final_artifact == "02_cover_letter.md"
    assert [f["name"] for f in captured["files"]] == ["01_analysis.md", "02_cover_letter.md"]


@pytest.mark.asyncio
async def test_preflight_reports_outputs_and_token_estimate():
    """预检返回产物清单/是否含简历/将加载内容/token 预估。"""
    fake_manager = SimpleNamespace(
        loaded_contents={"custom_skill": "# SOP " * 50},
        reference_maps={"custom_skill": {"a.md": "x" * 500}},
    )
    with patch.object(svc, "get_skill_contract", lambda _sid: GENERIC_CONTRACT), \
         patch.object(svc.feishu_client, "get_record", AsyncMock(return_value=_resume_record())), \
         patch("ai_agents.skills.skill_loader.get_skill_manager", return_value=fake_manager):
        report = await preflight_mod.preflight_skill_rewrite(_payload())

    assert report["result_kind"] == "markdown"
    assert report["has_resume_output"] is False
    assert report["expected_artifact_count"] == 2
    assert [o["filename"] for o in report["outputs"]] == ["01_analysis.md", "02_cover_letter.md"]
    assert report["will_load"]["jd_chars"] == len("JD")
    assert report["will_load"]["resume_chars"] > 0
    assert report["will_load"]["references_count"] == 1
    assert report["estimated_tokens"]["point"] > 0
    assert any("不会写回简历库" in w for w in report["warnings"])


@pytest.mark.asyncio
async def test_preflight_router_endpoint_passthrough(monkeypatch):
    """router 预检端点：成功返回 data，service 异常映射 HTTP 状态。"""
    from app.strategy.routes import skill_agent_router as sar

    async def fake_preflight(payload):
        return {
            "skill_id": "custom_cover",
            "engine": "agent",
            "result_kind": "markdown",
            "has_resume_output": False,
            "expected_artifact_count": 2,
            "outputs": [],
            "warnings": [],
            "will_load": {},
            "estimated_tokens": {"point": 1, "low": 1, "high": 2, "source": "heuristic"},
        }

    monkeypatch.setattr(sar, "preflight_skill_rewrite", fake_preflight)
    res = await sar.skill_rewrite_preflight_api(
        sar.SkillRewriteAndSaveRequest(resume_record_id="recSmoke3", jd_text="JD")
    )
    assert res["status"] == "success"
    assert res["data"]["result_kind"] == "markdown"


@pytest.mark.asyncio
async def test_test_skill_rewrite_endpoint_returns_artifacts(monkeypatch):
    """旧 2 元组入口不再静默丢 artifacts：/test_skill_rewrite 改走 detailed 并返回产物。"""
    from app.strategy.routes import skill_agent_router as sar
    from ai_agents.engine_facade import RewriteResult

    def fake_detailed(**kwargs):
        return RewriteResult(
            markdown="# ok",
            usage={"total_tokens": 1},
            artifacts=[{"name": "x.md", "content": "x"}],
            result_kind="markdown",
            engine="agent",
        )

    monkeypatch.setattr(sar, "process_resume_rewrite_detailed", fake_detailed)
    res = await sar.test_skill_rewrite_api(
        sar.TestSkillRewriteRequest(
            job_id="", jd_text="JD", job_name="x", skill_id="pkg", include_diagnosis=False
        )
    )
    assert res["data"]["artifacts"][0]["name"] == "x.md"
    assert res["data"]["result_kind"] == "markdown"
