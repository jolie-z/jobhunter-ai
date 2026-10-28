"""
全仓统一 LLM 重试策略与调度模块 (app/core/llm_retry.py)

设计原则与规范依据：
1. 重试权威唯一原则（根因 L3）：全进程只允许 RetryPolicy 统一策略，消除各业务模块私设重试循环。
2. 模块单向依赖（GLM2-P1-2 修复）：本模块单向 import common.config 纯数据配置；common.config 绝不反向引用本模块。
3. 原装异常透传契约（GLM-P1-2 修复）：重试耗尽时向异常对象注入 .kind 和 .user_msg 后直接上抛原装异常对象，保全调用方现有捕获语义。
4. 平台上下文与注入钩子（GLM2-P1-3 修复）：支持 on_retry 通知与 cancel_check 取消检查钩子。
5. 回滚开关热控（GLM2-P1-4 修复）：settings.json > 环境变量 > 默认开启（True）。
"""
from __future__ import annotations

import asyncio
import logging
import os
import random
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

from app.core.llm_errors import LLMErrorKind, classify_llm_error, compute_backoff_delay

logger = logging.getLogger("llm_retry")


class TaskCancelledException(Exception):
    """当 LLM 协作取消钩子检测到任务被取消时抛出。"""
    pass


@dataclass
class Attempt:
    number: int        # 从 1 开始，1, 2, ...
    is_last: bool


@dataclass
class RetryPolicy:
    max_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 10.0
    max_total_wait: float = 30.0
    honor_retry_after: bool = True
    jitter: bool = False
    retry_kinds: set[LLMErrorKind] = field(
        default_factory=lambda: {
            LLMErrorKind.rate_limited,
            LLMErrorKind.server,
            LLMErrorKind.timeout,
            LLMErrorKind.connection,
        }
    )
    on_retry: Callable[[str, int, float, dict], Any] | None = None
    cancel_check: Callable[[dict], bool] | None = None

    def is_enabled(self) -> bool:
        """判定策略是否允许重试（max_attempts > 1 且全局重试策略开启）。"""
        return self.max_attempts > 1 and is_llm_retry_policy_enabled()

    def __iter__(self) -> Iterator[Attempt]:
        attempts = max(1, self.max_attempts)
        for i in range(1, attempts + 1):
            yield Attempt(number=i, is_last=(i == attempts))


# 服务端 Retry-After 异常值防挂死兜底上限（5 分钟）
RETRY_AFTER_SANITY_CEILING: float = 300.0


def is_llm_retry_policy_enabled() -> bool:
    """
    熔断与回滚类开关读取（GLM2-P1-4 修复）：
    优先级：settings.json（运行时动态热控） > 环境变量 > 默认值（True）。
    注：与 common.config._is_retry_policy_enabled_data 保持镜像对齐，任何修改需同步。
    """
    # 1. 优先读取 settings.json
    try:
        from common.config import get_setting
        val = get_setting("LLM_RETRY_POLICY_ENABLED")
        if val is not None:
            if isinstance(val, bool):
                return val
            if isinstance(val, (int, float)):
                return bool(val)
            if isinstance(val, str):
                return val.strip().lower() in ("true", "1", "yes", "on")
    except Exception:
        pass

    # 2. 其次读取系统环境变量
    env_val = os.getenv("LLM_RETRY_POLICY_ENABLED")
    if env_val is not None:
        return env_val.strip().lower() in ("true", "1", "yes", "on")

    # 3. 默认开启
    return True


def compute_delay(
    policy: RetryPolicy,
    retry_after: float | None,
    attempt: Attempt | int,
    *,
    kind: LLMErrorKind | None = None,
) -> float:
    """计算当前重试尝试的等待延迟（服务端 Retry-After 场景优先尊重不强制受 max_delay 截断，普通退避受 policy.max_delay 约束）。"""
    attempt_num = attempt.number if isinstance(attempt, Attempt) else attempt
    idx = max(0, attempt_num - 1)
    ra = retry_after if policy.honor_retry_after else None
    # 优先尊重服务端 Retry-After（加 sanity 上限防异常超大值长时间挂起）；普通退避受 policy.max_delay 约束
    effective_max = min(RETRY_AFTER_SANITY_CEILING, max(policy.max_delay, ra)) if ra is not None else policy.max_delay
    delay = compute_backoff_delay(idx, retry_after=ra, kind=kind, max_delay=effective_max)

    # 如果没有指定 Retry-After 标头且开启抖动，增加 +/- 20% 随机扰动避免共振
    if policy.jitter and ra is None:
        jitter_factor = random.uniform(0.8, 1.2)
        delay = min(effective_max, max(policy.base_delay, delay * jitter_factor))

    return min(effective_max, max(0.1, delay))


def policy_for(caller: str = "", client: Any = None) -> RetryPolicy:
    """
    针对指定 caller 与 client 构造 RetryPolicy：
    1. 若回滚开关关闭，返回单次策略（max_attempts=1）；
    2. 尝试次数优先读取 client._configured_max_retries，其次从 common.config.DEFAULT_CALLER_MAX_RETRIES 获取；
    3. 转换规则：max_attempts = configured_retries + 1（例如 2 次重试对应 3 次尝试）。
    """
    if not is_llm_retry_policy_enabled():
        return RetryPolicy(max_attempts=1)

    configured_retries = None
    if client is not None:
        configured_retries = getattr(client, "_configured_max_retries", None)

    if configured_retries is None:
        try:
            from common.config import DEFAULT_CALLER_MAX_RETRIES
            configured_retries = DEFAULT_CALLER_MAX_RETRIES.get(caller, 2)
        except Exception:
            configured_retries = 2

    max_attempts = max(1, configured_retries + 1)
    return RetryPolicy(max_attempts=max_attempts)


def run_with_retry(
    fn: Callable[[], Any],
    policy: RetryPolicy,
    caller: str = "",
    sleep_fn: Callable[[float], None] | None = None,
    on_retry: Callable[[str, int, float, dict], Any] | None = None,
    cancel_check: Callable[[dict], bool] | None = None,
    context: dict | None = None,
) -> Any:
    """
    执行同步调用并在可重试异常发生时执行退避重试。
    保证原装异常对象透传契约（注入 .kind 和 .user_msg）。
    """
    ctx = context if context is not None else {}
    _on_retry = on_retry or policy.on_retry
    _cancel_check = cancel_check or policy.cancel_check
    _sleep = sleep_fn if sleep_fn is not None else time.sleep

    last_exc = None
    for attempt in policy:
        if _cancel_check and _cancel_check(ctx):
            raise TaskCancelledException(f"LLM task cancelled before attempt {attempt.number}")

        try:
            return fn()
        except Exception as e:
            last_exc = e
            kind, msg, retry_after = classify_llm_error(e)

            # 注入结构化异常属性供上层调用方可选透明读取
            try:
                e.kind = kind
                e.user_msg = msg
            except Exception:
                pass

            # 若错误不可重试或已是最后一次尝试，直接上抛原装异常
            if kind not in policy.retry_kinds or attempt.is_last:
                raise e

            delay = compute_delay(policy, retry_after, attempt, kind=kind)
            logger.warning(
                f"[llm_retry] {caller or 'unknown'} 触发重试: attempt={attempt.number}/{policy.max_attempts}, "
                f"kind={kind.value}, delay={delay:.2f}s, error={msg}"
            )

            if _on_retry:
                try:
                    _on_retry(caller, attempt.number, delay, ctx)
                except Exception as cb_err:
                    logger.warning(f"[llm_retry] on_retry 回调异常: {cb_err}")

            _sleep(delay)

            if _cancel_check and _cancel_check(ctx):
                raise TaskCancelledException(f"LLM task cancelled after sleep in attempt {attempt.number}")

    if last_exc:
        raise last_exc


async def arun_with_retry(
    fn: Callable[[], Any],
    policy: RetryPolicy,
    caller: str = "",
    sleep_fn: Callable[[float], Any] | None = None,
    on_retry: Callable[[str, int, float, dict], Any] | None = None,
    cancel_check: Callable[[dict], bool] | None = None,
    context: dict | None = None,
) -> Any:
    """
    执行异步调用并在可重试异常发生时执行非阻塞退避重试。
    """
    ctx = context if context is not None else {}
    _on_retry = on_retry or policy.on_retry
    _cancel_check = cancel_check or policy.cancel_check
    _sleep = sleep_fn if sleep_fn is not None else asyncio.sleep

    last_exc = None
    for attempt in policy:
        if _cancel_check and _cancel_check(ctx):
            raise TaskCancelledException(f"LLM async task cancelled before attempt {attempt.number}")

        try:
            res = fn()
            if asyncio.iscoroutine(res):
                return await res
            return res
        except Exception as e:
            last_exc = e
            kind, msg, retry_after = classify_llm_error(e)

            try:
                e.kind = kind
                e.user_msg = msg
            except Exception:
                pass

            if kind not in policy.retry_kinds or attempt.is_last:
                raise e

            delay = compute_delay(policy, retry_after, attempt, kind=kind)
            logger.warning(
                f"[llm_retry] async {caller or 'unknown'} 触发重试: attempt={attempt.number}/{policy.max_attempts}, "
                f"kind={kind.value}, delay={delay:.2f}s, error={msg}"
            )

            if _on_retry:
                try:
                    _on_retry(caller, attempt.number, delay, ctx)
                except Exception as cb_err:
                    logger.warning(f"[llm_retry] on_retry 回调异常: {cb_err}")

            await _sleep(delay)

            if _cancel_check and _cancel_check(ctx):
                raise TaskCancelledException(f"LLM async task cancelled after sleep in attempt {attempt.number}")

    if last_exc:
        raise last_exc
