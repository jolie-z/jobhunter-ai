"""
Phase 1 统一 LLM 重试策略与调度模块单元测试 (tests/test_llm_retry_policy.py)

覆盖规范：
1. 架构自检：common.config 严格保持纯数据，绝对不反向 import app.core.llm_retry (GLM2-P1-2)
2. 回滚开关优先级：settings.json > 环境变量 > 默认开启 (GLM2-P1-4)
3. 策略判定 policy_for：client._configured_max_retries 优先级与 N ↦ N+1 尝试转换
4. 同步 run_with_retry：重试退避序列、不可重试类型快速熔断、原装异常对象透传 (GLM-P1-2)
5. 注入式钩子：on_retry 回调透传 platform 与等待时间，cancel_check 协作取消终止 (GLM2-P1-3)
6. 异步 arun_with_retry：非阻塞协程重试
"""
import asyncio
import os
import sys
from unittest.mock import patch

import pytest
from app.core.llm_errors import LLMErrorKind
from app.core.llm_retry import (
    Attempt,
    RetryPolicy,
    TaskCancelledException,
    arun_with_retry,
    compute_delay,
    is_llm_retry_policy_enabled,
    policy_for,
    run_with_retry,
)


def test_architecture_no_cyclic_import_config_to_retry():
    """【GLM2-P1-2 核心断言】架构自检：common.config 严格保持纯数据，绝对严禁反向 import app.core.llm_retry。"""
    import subprocess
    cmd = [
        sys.executable,
        "-c",
        "import sys; import common.config as cfg; "
        "assert 'app.core.llm_retry' not in sys.modules, '加载 common.config 绝不能隐式拉起 app.core.llm_retry'; "
        "assert not hasattr(cfg, 'RetryPolicy'); "
        "assert not hasattr(cfg, 'run_with_retry'); "
        "assert not hasattr(cfg, 'policy_for')"
    ]
    backend_dir = os.path.dirname(os.path.dirname(__file__))
    res = subprocess.run(cmd, capture_output=True, text=True, cwd=backend_dir)
    assert res.returncode == 0, f"架构单向依赖自检失败: {res.stderr}"


def test_rollback_switch_settings_overrides_env():
    """【GLM2-P1-4 核心断言】回滚热控开关优先级：settings.json > 系统环境变量。"""
    # 场景 1: 系统环境变量为 true，但 settings.json 显式配置为 false -> 严格返回 False
    with patch.dict(os.environ, {"LLM_RETRY_POLICY_ENABLED": "true"}), \
         patch("common.config.get_setting", return_value=False):
        assert is_llm_retry_policy_enabled() is False, "settings.json 的 false 必须绝对压过环境变量的 true"

    # 场景 2: settings.json 缺失 (None)，环境变量为 false -> 返回 False
    with patch.dict(os.environ, {"LLM_RETRY_POLICY_ENABLED": "false"}), \
         patch("common.config.get_setting", return_value=None):
        assert is_llm_retry_policy_enabled() is False

    # 场景 3: 两者皆无 -> 默认返回 True
    with patch.dict(os.environ, {}, clear=True), \
         patch("common.config.get_setting", return_value=None):
        assert is_llm_retry_policy_enabled() is True


def test_policy_for_resolution_order():
    """验证 policy_for 获取尝试次数的优先级与 N+1 转换。"""
    # 1. client 显式指定 _configured_max_retries = 1 -> 总尝试次数为 2
    class DummyClient:
        _configured_max_retries = 1

    p1 = policy_for("agent_map", client=DummyClient())
    assert p1.max_attempts == 2

    # 2. client 无属性，查 DEFAULT_CALLER_MAX_RETRIES 中的 agent_map (配置为 2) -> 总尝试次数为 3
    p2 = policy_for("agent_map", client=object())
    assert p2.max_attempts == 3

    # 3. 未知 caller 回落默认 2 次重试 -> 3 次尝试
    p3 = policy_for("unknown_caller")
    assert p3.max_attempts == 3

    # 4. 回滚开关关闭时，恒定返回单次策略 (max_attempts = 1)
    with patch("app.core.llm_retry.is_llm_retry_policy_enabled", return_value=False):
        p_off = policy_for("agent_map")
        assert p_off.max_attempts == 1


def test_run_with_retry_success_first_try():
    """首发成功：调用一次即返回结果，无重试且无休眠。"""
    sleep_calls = []
    policy = RetryPolicy(max_attempts=3)
    res = run_with_retry(lambda: "ok", policy, caller="test", sleep_fn=sleep_calls.append)
    assert res == "ok"
    assert len(sleep_calls) == 0


def test_run_with_retry_429_then_success():
    """429 速率限制重试：第 1、2 次抛 429，第 3 次成功返回。"""
    class FakeRateLimitError(Exception):
        status_code = 429

    attempts_count = 0
    sleep_calls = []

    def mock_call():
        nonlocal attempts_count
        attempts_count += 1
        if attempts_count < 3:
            raise FakeRateLimitError("Rate limit reached")
        return "finally_success"

    policy = RetryPolicy(max_attempts=3, base_delay=1.0, jitter=False)
    res = run_with_retry(mock_call, policy, caller="test", sleep_fn=sleep_calls.append)

    assert res == "finally_success"
    assert attempts_count == 3
    assert len(sleep_calls) == 2
    # 第 1 次重试 delay = 1.0s, 第 2 次重试 delay = 2.0s
    assert sleep_calls[0] == pytest.approx(1.0, 0.1)
    assert sleep_calls[1] == pytest.approx(2.0, 0.1)


def test_run_with_retry_exhaustion_preserves_original_exception():
    """【GLM-P1-2 核心断言】重试耗尽时上抛原装异常对象，保证调用方捕获语义；注入 .kind 和 .user_msg。"""
    class CustomRateLimitError(Exception):
        status_code = 429

    original_exc = CustomRateLimitError("Quota limit hit")
    policy = RetryPolicy(max_attempts=2, jitter=False)

    with pytest.raises(CustomRateLimitError) as exc_info:
        run_with_retry(lambda: (_ for _ in ()).throw(original_exc), policy, caller="test", sleep_fn=lambda _: None)

    raised = exc_info.value
    assert raised is original_exc, "上抛的必须是完全原装的异常实例"
    assert getattr(raised, "kind", None) == LLMErrorKind.rate_limited
    assert "速率限制" in getattr(raised, "user_msg", "")


def test_run_with_retry_non_retryable_auth_error_aborts_immediately():
    """鉴权错误 (401) 不可重试，立即上抛，不执行任何重试休眠。"""
    class AuthError(Exception):
        status_code = 401

    sleep_calls = []
    policy = RetryPolicy(max_attempts=3)

    with pytest.raises(AuthError):
        run_with_retry(
            lambda: (_ for _ in ()).throw(AuthError("Invalid API Key")),
            policy,
            caller="test",
            sleep_fn=sleep_calls.append,
        )

    assert len(sleep_calls) == 0, "401 鉴权错误绝不执行退避休眠"


def test_run_with_retry_hooks_and_cancellation():
    """【GLM2-P1-3 核心断言】on_retry 回调正确接收 platform/delay；cancel_check 协作取消能中断重试。"""
    class FakeTimeout(Exception):
        status_code = 408

    retry_events = []
    context = {"platform": "boss", "task_id": "task-999"}

    def on_retry_hook(caller, attempt_num, delay, ctx):
        retry_events.append((caller, attempt_num, delay, ctx.get("platform")))

    cancel_flag = False

    def cancel_checker(ctx):
        return cancel_flag

    # 1. 验证正常 on_retry 触发
    policy = RetryPolicy(max_attempts=2, jitter=False)
    with pytest.raises(FakeTimeout):
        run_with_retry(
            lambda: (_ for _ in ()).throw(FakeTimeout("Timed out")),
            policy,
            caller="agent_map",
            sleep_fn=lambda _: None,
            on_retry=on_retry_hook,
            context=context,
        )

    assert len(retry_events) == 1
    assert retry_events[0][0] == "agent_map"
    assert retry_events[0][1] == 1
    assert retry_events[0][3] == "boss"

    # 2. 验证 cancel_check 协作取消
    cancel_flag = True
    with pytest.raises(TaskCancelledException) as exc_info:
        run_with_retry(
            lambda: "should not be reached",
            policy,
            caller="agent_map",
            cancel_check=cancel_checker,
            context=context,
        )
    assert "cancelled before attempt 1" in str(exc_info.value)


@pytest.mark.asyncio
async def test_arun_with_retry_async_flow():
    """验证异步 arun_with_retry 非阻塞执行。"""
    class FakeServerErr(Exception):
        status_code = 503

    attempt_count = 0
    slept_delays = []

    async def fake_async_sleep(delay):
        slept_delays.append(delay)

    async def mock_async_fn():
        nonlocal attempt_count
        attempt_count += 1
        if attempt_count < 2:
            raise FakeServerErr("Server unavailable")
        return "async_ok"

    policy = RetryPolicy(max_attempts=2, jitter=False)
    res = await arun_with_retry(
        mock_async_fn,
        policy,
        caller="async_test",
        sleep_fn=fake_async_sleep,
    )

    assert res == "async_ok"
    assert attempt_count == 2
    assert len(slept_delays) == 1
