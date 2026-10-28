"""Skill 输出契约扫描/token 预估回归（2026-10-25）。

目标：换一个产物结构不同的自定义 skill 时，系统能识别产物数量/类型、
是否含简历、最终文件，并给出 token 预估，而不是继续套 11 份简历 SOP。
"""

import json

import pytest

from ai_agents.skills import skill_dirs
from ai_agents.skills.skill_contract import (
    contract_summary,
    estimate_skill_run,
    get_skill_contract,
    scan_skill_contract,
)
from ai_agents.skills.skill_loader import get_skill_manager


def _require_real_skill():
    """本机可能有用户上传的 LLMInternSkill；公开仓库/其他机器没有时跳过。"""
    manager = get_skill_manager()
    if "custom_llminternskill" not in manager.skills:
        pytest.skip("custom_llminternskill not installed on this machine")
    return manager


def test_real_llmintern_skill_scan():
    manager = _require_real_skill()
    meta = manager.skills["custom_llminternskill"]
    contract = scan_skill_contract(
        meta.id,
        manager.loaded_contents[meta.id],
        manager.reference_maps[meta.id],
        name=meta.name,
        description=meta.description,
        is_package=meta.is_package,
        references_count=meta.references_count,
    )
    assert contract.engine == "agent"
    assert contract.output_kind == "resume"
    assert contract.expected_artifact_count == 11
    assert contract.final_artifact == "06_targeted_resume.md"
    assert contract.has_resume_output is True
    assert contract.output_count_source == "skill_md"
    assert [o.filename for o in contract.outputs][0] == "01_jd_analysis.md"
    assert [o.filename for o in contract.outputs][-1] == "11_final_pack.md"
    assert contract.warnings == []


def test_cover_letter_package_scan():
    content = """# Cover Letter Writer
## Output Files
```text
output/
├── 01_analysis.md
├── 02_draft.md
└── 03_cover_letter.md
```
"""
    contract = scan_skill_contract(
        "custom_cover", content, {"refs/a.md": "# A"},
        name="Cover Letter Writer", is_package=True, references_count=3,
    )
    assert contract.engine == "agent"
    assert contract.output_kind == "markdown"
    assert contract.expected_artifact_count == 3
    assert contract.final_artifact == "03_cover_letter.md"
    assert contract.has_resume_output is False
    assert contract.postprocess == "markdown_only"
    assert contract.writeback == "none"
    assert any("不会写回简历库" in w for w in contract.warnings)


def test_single_file_generic_skill_routes_agent():
    content = """# Data Report Writer
Write a concise markdown report.
"""
    contract = scan_skill_contract(
        "custom_report", content, {},
        name="Data Report Writer", is_package=False, references_count=0,
    )
    assert contract.engine == "agent"
    assert contract.output_kind == "markdown"
    assert contract.has_resume_output is False


def test_single_file_resume_skill_keeps_official_engine():
    content = """# Resume Rewrite Helper
This skill polishes a resume against a target JD.
"""
    contract = scan_skill_contract(
        "custom_resume_helper", content, {},
        name="Resume Helper", is_package=False, references_count=0,
    )
    assert contract.engine == "official"
    assert contract.output_kind == "resume"
    assert contract.has_resume_output is True


def test_inputs_section_not_misread_as_outputs():
    content = """# Generic Skill
## Inputs
```text
materials/
├── resume.md
├── notes.md
└── target_jd.txt
```
"""
    contract = scan_skill_contract(
        "custom_input_only", content, {},
        name="Generic Skill", is_package=True, references_count=2,
    )
    names = [o.filename for o in contract.outputs]
    assert "resume.md" not in names
    assert "notes.md" not in names
    # 没有可识别产物时返回 unknown，不硬编码 11 份
    assert contract.expected_artifact_count == 0
    assert contract.output_count_source == "unknown"


def test_json_output_contract():
    content = """# Structured Result
## Output Files
- `result.json` (structured result)
"""
    contract = scan_skill_contract(
        "custom_json", content, {},
        name="Structured Result", is_package=True, references_count=1,
    )
    assert contract.output_kind == "json"
    assert contract.final_artifact == "result.json"
    assert contract.outputs[0].kind == "json"
    assert contract.postprocess == "markdown_only"


def test_official_contract_is_resume():
    contract = get_skill_contract("resume_rewrite")
    assert contract["engine"] == "official"
    assert contract["output_kind"] == "resume"
    assert contract["postprocess"] == "resume_json"
    summary = contract_summary(contract)
    assert summary["has_resume_output"] is True


def test_estimate_heuristic_without_history():
    contract = {
        "engine": "agent",
        "expected_artifact_count": 3,
    }
    est = estimate_skill_run(
        skill_id="custom_never_run",
        contract=contract,
        main_content="# SOP" * 100,
        reference_map={"a.md": "x" * 1000},
        jd_chars=500,
        resume_chars=1000,
    )
    assert est["source"] == "heuristic"
    assert est["point"] > 0
    assert est["low"] < est["point"] < est["high"]


def test_estimate_uses_history_when_available():
    job_id = "recContractHistory"
    skill_id = "custom_history_skill"
    try:
        skill_dirs.save_skill_result(
            job_record_id=job_id,
            skill_id=skill_id,
            files=[{"name": "final.md", "content": "ok"}],
            token_usage={"total_tokens": 250000},
            replace_existing=True,
        )
        est = estimate_skill_run(
            skill_id=skill_id,
            contract={"engine": "agent", "expected_artifact_count": 3},
        )
        assert est["source"] == "history"
        assert est["point"] == 250000
        assert est["sample_count"] >= 1
    finally:
        skill_dirs.delete_job_results(job_id)


def test_scan_endpoint_returns_real_skill_contract(monkeypatch):
    import asyncio
    from app.api.routes.skills import scan_skill_outputs
    import ai_agents.skills.skill_contract as skill_contract

    _require_real_skill()
    # 测试不得改写真实技能包目录的 meta.json
    monkeypatch.setattr(skill_contract, "persist_contract", lambda *a, **k: None)

    result = asyncio.run(scan_skill_outputs("custom_llminternskill"))
    assert result["success"] is True
    data = result["data"]
    assert data["summary"]["engine"] == "agent"
    assert data["summary"]["expected_output_count"] == 11
    assert data["summary"]["has_resume_output"] is True
    assert data["summary"]["final_artifact"] == "06_targeted_resume.md"
    assert data["estimated_tokens"]["point"] > 0


def test_upload_scan_helper_returns_contract_and_estimate(monkeypatch):
    from app.api.routes.skills_upload import _build_skill_scan_payload
    import ai_agents.skills.skill_contract as skill_contract

    _require_real_skill()
    monkeypatch.setattr(skill_contract, "persist_contract", lambda *a, **k: None)

    scan = _build_skill_scan_payload("custom_llminternskill")
    assert scan["summary"]["expected_output_count"] == 11
    assert scan["contract"]["final_artifact"] == "06_targeted_resume.md"
    assert scan["estimate_scope"] == (
        "history_full_run" if scan["estimated_tokens"]["source"] == "history" else "skill_only"
    )
    assert scan["estimated_tokens"]["point"] > 0


def test_cover_letter_mentioning_resume_not_misclassified():
    """SKILL.md 提到 resume，但显式产物清单里没有简历文件 → 按通用 skill 处理。"""
    content = """# Cover Letter Writer
This skill tailors a cover letter based on your resume.
## Output Files
- `01_analysis.md`
- `03_cover_letter.md`
"""
    contract = scan_skill_contract(
        "custom_cover2", content, {},
        name="Cover Letter Writer", is_package=True, references_count=2,
    )
    assert contract.output_kind == "markdown"
    assert contract.has_resume_output is False
    assert contract.final_artifact == "03_cover_letter.md"
    assert contract.postprocess == "markdown_only"
