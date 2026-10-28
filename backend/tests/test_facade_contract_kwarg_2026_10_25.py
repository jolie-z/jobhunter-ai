"""facade contract 参数回归（2026-10-25 0.3.4 真机工单）。

skill_rewrite_service.execute_rewrite 显式传 contract= 契约快照，而
process_resume_rewrite_detailed 未声明该参数——真机首跑即
`TypeError: got an unexpected keyword argument 'contract'`，任务在引擎
启动前就终止。既有测试全部 mock 掉 facade，mock 不校验签名，故漏网。

锁定三件事：
1. facade 签名接受 contract；
2. 传入的契约快照原样生效并到达 agent runner（不得被内部重解析覆盖）；
3. 旧调用方（不传 contract）行为不变，仍按 skill_id 内部解析。
"""

import asyncio
import inspect
from types import SimpleNamespace
from unittest.mock import patch

from ai_agents import engine_facade
from ai_agents.skills.skill_agent_runner import ProgressiveAgentResult
from app.strategy.skill_rewrite_service import SkillRewriteContext, execute_rewrite


def _context(**kw) -> SkillRewriteContext:
    base = dict(
        skill_id="pkg",
        jd_text="目标岗位 JD",
        job_name="AI 工程师",
        original_resume_override="原简历正文",
        contract={"expected_artifact_count": 3, "output_kind": "resume", "final_artifact": "06.md"},
    )
    base.update(kw)
    return SkillRewriteContext(**base)


def test_facade_signature_accepts_contract():
    params = inspect.signature(engine_facade.process_resume_rewrite_detailed).parameters
    assert "contract" in params
    assert params["contract"].default is None


def test_execute_rewrite_contract_snapshot_reaches_agent():
    """真机崩溃路径端到端：execute_rewrite → 真实 facade → agent runner。"""
    received = {}

    def fake_runner(**kwargs):
        received.update(kwargs)
        return ProgressiveAgentResult(markdown="改写完成产物", usage={}, artifacts=[], engine="agent")

    fake_manager = SimpleNamespace(loaded_contents={"pkg": "# SOP"}, reference_maps={"pkg": {}})
    ctx = _context()

    with patch.object(engine_facade, "resolve_rewrite_engine", return_value="agent"), \
         patch("ai_agents.skills.skill_loader.get_skill_manager", return_value=fake_manager), \
         patch("ai_agents.skills.skill_agent_runner.run_progressive_skill_agent", side_effect=fake_runner):
        result = asyncio.run(execute_rewrite(ctx))

    assert received.get("contract") == ctx.contract
    assert result.markdown == "改写完成产物"
    assert result.engine == "agent"


def test_provided_contract_wins_over_internal_resolution():
    """传入快照必须生效：即使内部解析返回不同契约，也以调用方为准。"""

    def fake_official_rewrite(**kwargs):
        return "官方引擎产物", {"total_tokens": 1}

    with patch.object(engine_facade, "resolve_rewrite_engine", return_value="official"), \
         patch("ai_agents.skills.skill_contract.get_skill_contract",
               return_value={"expected_artifact_count": 99, "final_artifact": "wrong.md"}), \
         patch.object(engine_facade, "run_skill_based_rewrite", side_effect=fake_official_rewrite):
        result = engine_facade.process_resume_rewrite_detailed(
            jd_text="JD",
            diagnosis_dict={},
            original_resume_override="原简历正文",
            skill_id="pkg",
            contract={"expected_artifact_count": 3, "output_kind": "resume", "final_artifact": "06.md"},
        )

    assert result.expected_artifact_count == 3
    assert result.final_artifact == "06.md"


def test_legacy_callers_still_resolve_contract_internally():
    """不传 contract 的旧调用方（router 同步路径 / process_resume 委托）不受影响。"""

    def fake_official_rewrite(**kwargs):
        return "官方引擎产物", {"total_tokens": 1}

    with patch.object(engine_facade, "resolve_rewrite_engine", return_value="official"), \
         patch("ai_agents.skills.skill_contract.get_skill_contract",
               return_value={"expected_artifact_count": 5, "final_artifact": "resolved.md"}), \
         patch.object(engine_facade, "run_skill_based_rewrite", side_effect=fake_official_rewrite):
        result = engine_facade.process_resume_rewrite_detailed(
            jd_text="JD",
            diagnosis_dict={},
            original_resume_override="原简历正文",
            skill_id="pkg",
        )

    assert result.expected_artifact_count == 5
    assert result.final_artifact == "resolved.md"
