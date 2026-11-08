"""engine_facade 截断自动重试单测（2026-11-01 根因排查配套）。

上游 deepseek-v4.1-flash 经 上游聚合网关 聚合后偶发「正常收尾但正文半截」的静默截断
（finish_reason 非 length）。截断自动重试统一收敛在 process_resume_rewrite_detailed
官方引擎分支——5 个批量调用方与 router 路径一次覆盖，调用方只做闸门不再重试。
"""
from unittest.mock import MagicMock, patch

from ai_agents.engine_facade import (
    _REWRITE_MAX_RETRIES,
    RewriteResult,
    process_resume_rewrite,
    process_resume_rewrite_detailed,
)

TRUNCATED = "❌ 简历定制失败：定稿标签 <FINAL_RESUME> 未闭合（输出疑似被截断），已拒绝使用残缺内容，请重试。"
VALID_MD = "# 正常简历\n重构版内容"
VALID_USAGE = {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150, "cached_tokens": 0}


def _patch_official_engine(mock_engine):
    """官方引擎路径的最小 mock 集：引擎函数 + 引擎路由钉 official。"""
    return (
        patch("ai_agents.engine_facade.run_skill_based_rewrite", mock_engine),
        patch("ai_agents.engine_facade.resolve_rewrite_engine", return_value="official"),
    )


def test_rewrite_retry_succeeds_after_truncation():
    """首次截断 ❌ → 自动重试一次成功：底层引擎共调用 2 次，返回正常简历"""
    mock_engine = MagicMock(side_effect=[(TRUNCATED, {}), (VALID_MD, VALID_USAGE)])
    p_engine, p_route = _patch_official_engine(mock_engine)

    with p_engine, p_route:
        result = process_resume_rewrite_detailed(
            jd_text="JD 文本",
            diagnosis_dict={},
            job_name="测试岗",
            rewrite_mode="skill",
            original_resume_override="原始简历",
            skill_id="default",
        )

    assert mock_engine.call_count == 2
    assert result.markdown == VALID_MD
    assert result.usage == VALID_USAGE
    assert result.error_reason == ""
    assert result.engine == "official"


def test_rewrite_retry_exhausted_returns_error_with_reason():
    """连续截断：重试耗尽后返回 ❌ 串，共调用 1+2 次，error_reason 如实记录"""
    mock_engine = MagicMock(return_value=(TRUNCATED, {}))
    p_engine, p_route = _patch_official_engine(mock_engine)

    with p_engine, p_route:
        result = process_resume_rewrite_detailed(
            jd_text="JD 文本",
            diagnosis_dict={},
            job_name="测试岗",
            rewrite_mode="skill",
            original_resume_override="原始简历",
            skill_id="default",
        )

    assert mock_engine.call_count == _REWRITE_MAX_RETRIES + 1
    assert result.markdown == TRUNCATED
    assert result.error_reason.startswith("❌ 简历定制失败")


def test_rewrite_valid_first_attempt_never_retries():
    """首次即正常：不触发任何重试"""
    mock_engine = MagicMock(return_value=(VALID_MD, VALID_USAGE))
    p_engine, p_route = _patch_official_engine(mock_engine)

    with p_engine, p_route:
        result = process_resume_rewrite_detailed(
            jd_text="JD 文本",
            diagnosis_dict={},
            job_name="测试岗",
            rewrite_mode="skill",
            original_resume_override="原始简历",
            skill_id="default",
        )

    assert mock_engine.call_count == 1
    assert result.markdown == VALID_MD
    assert result.error_reason == ""


def test_rewrite_retry_emits_rewrite_retry_events():
    """每次重试都发出 rewrite_retry 事件（供 wave_pipeline 桥接 SSE 保持前端可见）"""
    mock_engine = MagicMock(side_effect=[(TRUNCATED, {}), (TRUNCATED, {}), (VALID_MD, VALID_USAGE)])
    p_engine, p_route = _patch_official_engine(mock_engine)
    events = []

    with p_engine, p_route:
        process_resume_rewrite_detailed(
            jd_text="JD 文本",
            diagnosis_dict={},
            job_name="测试岗",
            rewrite_mode="skill",
            original_resume_override="原始简历",
            skill_id="default",
            on_event=lambda t, p: events.append((t, p)),
        )

    retry_events = [p for t, p in events if t == "rewrite_retry"]
    assert len(retry_events) == 2
    assert retry_events[0]["attempt"] == 1
    assert retry_events[1]["attempt"] == 2
    assert retry_events[1]["max_retries"] == _REWRITE_MAX_RETRIES


def test_tuple_gateway_inherits_retry_result():
    """2 元组兼容入口（5 个批量调用方在用）透传 facade 重试后的最终结果"""
    mock_engine = MagicMock(side_effect=[(TRUNCATED, {}), (VALID_MD, VALID_USAGE)])
    p_engine, p_route = _patch_official_engine(mock_engine)

    with p_engine, p_route:
        markdown, usage = process_resume_rewrite(
            jd_text="JD 文本",
            diagnosis_dict={},
            job_name="测试岗",
            rewrite_mode="skill",
            original_resume_override="原始简历",
        )

    assert mock_engine.call_count == 2
    assert markdown == VALID_MD
    assert usage == VALID_USAGE
