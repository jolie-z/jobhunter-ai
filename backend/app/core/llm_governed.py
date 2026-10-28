"""
LLM 统一治理层调度入口 (app/core/llm_governed.py)

设计原则与规范依据：
1. 闸门包住单次发送（Spec Phase 2）：并发槽仅在单次 HTTP 往返在飞期间持有，退避休眠与等令牌绝不占槽。
2. 显式所有权移交（GLM2-P1-1 修复）：响应为流式时，槽位释放权移交给 GovernedStream / AsyncGovernedStream，流耗尽或 close 时释放。
3. 平台上下文透传（GLM2-P1-3 修复）：通过 current_llm_context (ContextVar) 向重试回调与协作取消钩子透明传递上下文。
4. 原装异常透传契约（GLM-P1-2 修复）：重试耗尽时上抛原装异常对象，挂载 kind 与 user_msg，保证调用方捕获语义 100% 兼容。
5. 双流分离治理：明确区分同步 (govern_sync_call) 与异步 (govern_async_call) 通道，异步链路全协程非阻塞。
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from typing import Any

from app.core.llm_errors import LLMErrorKind, LLMGateTimeoutError, classify_llm_error
from app.core.llm_gate import LLMGate, SlotGuard, get_llm_gate, is_llm_gate_enabled
from app.core.llm_retry import (
    RetryPolicy,
    TaskCancelledException,
    compute_delay,
    policy_for,
)

logger = logging.getLogger("llm_governed")

# 全局平台与任务上下文透传通道（线程/协程安全）
current_llm_context: ContextVar[dict | None] = ContextVar("current_llm_context", default=None)

# 显式过闸重入护栏：同一调用链内嵌套进入 governed_llm_passage 只占一次槽、只扣一次令牌
# （例如 LangChain 模型 streaming=True 时 invoke 内部再走 _stream），防止自我等待死锁。
_in_governed_passage: ContextVar[bool] = ContextVar("_in_governed_passage", default=False)


def _cooldown_rejection(gate: LLMGate) -> LLMGateTimeoutError:
    rem = gate.get_cooldown_remaining()
    return LLMGateTimeoutError(
        f"系统处于全局 429 冷却期（剩余 {rem:.1f}s），已拒绝放行以阻断雪崩", retry_after=rem
    )


def _rpm_rejection() -> LLMGateTimeoutError:
    return LLMGateTimeoutError("请求速率 (RPM) 达上限且等待超时，已拦截以保护上游服务", retry_after=1.0)


def _slot_rejection(caller: str) -> LLMGateTimeoutError:
    return LLMGateTimeoutError(f"并发槽位已满（caller={caller}），等待超时被闸门拒绝", retry_after=2.0)


def _notify_upstream_rate_limit(gate: LLMGate, err: Exception, kind: LLMErrorKind, retry_after: float | None) -> None:
    """仅上游响应型 429 才触发全局冷却窗，闸门内部背压异常不污染上游拦截计数。"""
    if kind == LLMErrorKind.rate_limited and not isinstance(err, LLMGateTimeoutError):
        gate.notify_rate_limited(retry_after)


def _resolve_invocation_context(
    caller: str, client: Any, policy: RetryPolicy | None
) -> tuple[RetryPolicy, dict, Any, Any]:
    """抽取公共上下文与重试/取消钩子解析逻辑。"""
    effective_policy = policy or policy_for(caller, client=client)
    ctx = current_llm_context.get() or {}
    on_retry = ctx.get("on_retry") if isinstance(ctx, dict) else None
    cancel_check = ctx.get("cancel_check") if isinstance(ctx, dict) else None
    return effective_policy, ctx, on_retry, cancel_check


def _is_stream_request(kwargs: dict) -> bool:
    """根据请求参数判定是否为流式调用。"""
    return bool(kwargs.get("stream", False))


@contextmanager
def governed_llm_passage(caller: str = "", timeout: float = 60.0):
    """
    显式过闸上下文管理器（同步）：冷却窗 -> RPM 令牌 -> 并发槽，离开时释放槽。

    供 LangChain 等不经 llm_tracker 的叶子 LLM 调用使用（规范 Phase 2：闸门为显式式）。
    被拒绝时抛 LLMGateTimeoutError，严禁旁路裸发上游；调用体内出现上游 429 时同样
    开启全局冷却窗。同一上下文嵌套进入为重入（不重复占槽、不重复扣令牌）。
    """
    if not is_llm_gate_enabled() or _in_governed_passage.get():
        yield
        return
    gate = get_llm_gate()
    if not gate.wait_if_global_cooldown(timeout=timeout):
        raise _cooldown_rejection(gate)
    if not gate.wait_for_rpm_token(timeout=timeout):
        raise _rpm_rejection()
    guard = gate.acquire_slot(caller, timeout=timeout)
    if guard is None:
        raise _slot_rejection(caller)
    token = _in_governed_passage.set(True)
    try:
        yield
        gate.record_success()
    except Exception as e:
        kind, _msg, retry_after = classify_llm_error(e)
        _notify_upstream_rate_limit(gate, e, kind, retry_after)
        raise
    finally:
        guard.release()
        try:
            _in_governed_passage.reset(token)
        except ValueError:
            pass  # 流式生成器被 GC 关闭等罕见路径下上下文已切换，护栏自然失效即可


@asynccontextmanager
async def async_governed_llm_passage(caller: str = "", timeout: float = 60.0):
    """
    显式过闸上下文管理器（异步）：与同步版同源，等待与占槽全程非阻塞。
    """
    if not is_llm_gate_enabled() or _in_governed_passage.get():
        yield
        return
    gate = get_llm_gate()
    if not (await gate.async_wait_if_global_cooldown(timeout=timeout)):
        raise _cooldown_rejection(gate)
    if not (await gate.async_wait_for_rpm_token(timeout=timeout)):
        raise _rpm_rejection()
    guard = await gate.async_acquire_slot(caller, timeout=timeout)
    if guard is None:
        raise _slot_rejection(caller)
    token = _in_governed_passage.set(True)
    try:
        yield
        gate.record_success()
    except Exception as e:
        kind, _msg, retry_after = classify_llm_error(e)
        _notify_upstream_rate_limit(gate, e, kind, retry_after)
        raise
    finally:
        guard.release()
        try:
            _in_governed_passage.reset(token)
        except ValueError:
            pass


class GovernedStream:
    """
    同步流式代理：在流迭代消费期间独占并发槽，在流关闭或消费结束时幂等释放。
    """
    def __init__(self, raw_stream: Any, caller: str = "", guard: SlotGuard | None = None):
        self._raw_stream = raw_stream
        self.caller = caller
        self._guard = guard

    def __iter__(self):
        try:
            yield from self._raw_stream
        finally:
            self.close()

    def close(self) -> None:
        """幂等释放移交的并发槽。"""
        if self._guard is not None:
            g = self._guard
            self._guard = None
            g.release()
        if hasattr(self._raw_stream, "close"):
            try:
                self._raw_stream.close()
            except Exception:
                pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def __del__(self):
        try:
            if self._guard is not None:
                logger.warning(
                    "[llm_governed] GovernedStream 未消费完即被 GC 回收，__del__ 兜底释放并发槽（caller=%s）",
                    self.caller,
                )
            self.close()
        except Exception:
            pass

    def __getattr__(self, name: str) -> Any:
        return getattr(self._raw_stream, name)


class AsyncGovernedStream:
    """
    异步流式代理：在异步流迭代消费期间独占并发槽，在流关闭或消费结束时幂等释放。
    """
    def __init__(self, raw_stream: Any, caller: str = "", guard: SlotGuard | None = None):
        self._raw_stream = raw_stream
        self.caller = caller
        self._guard = guard

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return await self._raw_stream.__anext__()
        except StopAsyncIteration:
            await self.aclose()
            raise
        except Exception:
            await self.aclose()
            raise

    async def aclose(self) -> None:
        """异步幂等释放移交的并发槽。"""
        if self._guard is not None:
            g = self._guard
            self._guard = None
            g.release()
        if hasattr(self._raw_stream, "aclose"):
            try:
                await self._raw_stream.aclose()
            except Exception:
                pass
        elif hasattr(self._raw_stream, "close"):
            try:
                self._raw_stream.close()
            except Exception:
                pass

    def close(self) -> None:
        """同步回退释放。"""
        if self._guard is not None:
            g = self._guard
            self._guard = None
            g.release()
        if hasattr(self._raw_stream, "close"):
            try:
                self._raw_stream.close()
            except Exception:
                pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.aclose()

    def __del__(self):
        try:
            if self._guard is not None:
                logger.warning(
                    "[llm_governed] AsyncGovernedStream 未消费完即被 GC 回收，__del__ 兜底释放并发槽（caller=%s）",
                    self.caller,
                )
            self.close()
        except Exception:
            pass

    def __getattr__(self, name: str) -> Any:
        return getattr(self._raw_stream, name)


def govern_sync_call(
    raw_create: Callable[..., Any],
    args: tuple,
    kwargs: dict,
    caller: str = "",
    client: Any = None,
    policy: RetryPolicy | None = None,
) -> Any:
    """
    同步 LLM 调用治理入口：
    挂载进程全局限流闸门（冷却窗 -> RPM 令牌 -> 并发槽），支持流式所有权移交与出闸后退避休眠。
    若等待超时或被拒绝，严禁裸发请求上游，直接抛出原装可降级异常。
    """
    effective_policy, ctx, on_retry, cancel_check = _resolve_invocation_context(caller, client, policy)
    if not is_llm_gate_enabled() and not effective_policy.is_enabled():
        return raw_create(*args, **kwargs)

    gate = get_llm_gate()
    is_stream = _is_stream_request(kwargs)

    for attempt in effective_policy:
        if cancel_check and cancel_check(ctx):
            raise TaskCancelledException(f"LLM task cancelled before attempt {attempt.number}")

        guard: SlotGuard | None = None
        err: Exception | None = None

        # 1. 冷却窗与 RPM 令牌检查（失败绝不旁路直通，直接构造拒绝异常阻断雪崩）
        # 冷却窗在每次发送前检查（规范 Phase 2 原始约束）：已过期时零成本直通；
        # 仍有效时必须等待——上游 429 不带 Retry-After 时退避延迟（1s 级）可能短于
        # 冷却窗（默认 5s），且其他并发请求可能在休眠期间延长冷却窗，重试轮跳过
        # 检查会在冷却期内发出请求，削弱"阻断连锁雪崩"保证。
        if not gate.wait_if_global_cooldown():
            err = _cooldown_rejection(gate)
        elif not gate.wait_for_rpm_token():
            err = _rpm_rejection()
        else:
            # 2. 申请并发槽位（超时返回 None 视为拒绝，严禁裸发请求上游）
            guard = gate.acquire_slot(caller)
            if guard is None:
                err = _slot_rejection(caller)
            else:
                try:
                    resp = raw_create(*args, **kwargs)
                    gate.record_success()
                    if is_stream:
                        stream_guard = guard
                        guard = None  # 所有权显式移交流代理，置空局部 guard 杜绝 finally 二次释放
                        return GovernedStream(resp, caller=caller, guard=stream_guard)
                    return resp
                except Exception as e:
                    err = e
                finally:
                    if guard is not None:
                        guard.release()

        # 3. 出闸后分类异常并决定重试（槽位已完全释放，重试休眠绝不占用并发位）
        kind, msg, retry_after = classify_llm_error(err)
        _notify_upstream_rate_limit(gate, err, kind, retry_after)

        if not effective_policy.is_enabled() or kind not in effective_policy.retry_kinds or attempt.is_last:
            err.kind = kind
            err.user_msg = msg
            raise err

        delay = compute_delay(effective_policy, retry_after, attempt, kind=kind)
        if on_retry:
            on_retry(caller, attempt.number, delay, ctx)

        time.sleep(delay)
        if cancel_check and cancel_check(ctx):
            raise TaskCancelledException(f"LLM task cancelled after sleep in attempt {attempt.number}")


async def govern_async_call(
    raw_create: Callable[..., Any],
    args: tuple,
    kwargs: dict,
    caller: str = "",
    client: Any = None,
    policy: RetryPolicy | None = None,
) -> Any:
    """
    异步 LLM 调用治理入口：
    挂载异步非阻塞全局限流闸门，支持异步流式所有权移交与异步出闸后退避休眠。
    若等待超时或被拒绝，严禁裸发请求上游，直接抛出原装可降级异常。
    """
    effective_policy, ctx, on_retry, cancel_check = _resolve_invocation_context(caller, client, policy)
    if not is_llm_gate_enabled() and not effective_policy.is_enabled():
        return await raw_create(*args, **kwargs)

    gate = get_llm_gate()
    is_stream = _is_stream_request(kwargs)

    for attempt in effective_policy:
        if cancel_check and cancel_check(ctx):
            raise TaskCancelledException(f"LLM async task cancelled before attempt {attempt.number}")

        guard: SlotGuard | None = None
        err: Exception | None = None

        # 1. 异步等待冷却窗与 RPM 令牌（非阻塞协程，绝不占用并发槽）
        # 冷却窗在每次发送前检查（与同步侧同源）：已过期零成本直通，仍有效必须等待，
        # 防止无 Retry-After 的 429 场景下重试轮在冷却期内发出请求。
        if not (await gate.async_wait_if_global_cooldown()):
            err = _cooldown_rejection(gate)
        elif not (await gate.async_wait_for_rpm_token()):
            err = _rpm_rejection()
        else:
            # 2. 异步申请并发槽位
            guard = await gate.async_acquire_slot(caller)
            if guard is None:
                err = _slot_rejection(caller)
            else:
                try:
                    resp = await raw_create(*args, **kwargs)
                    gate.record_success()
                    if is_stream:
                        stream_guard = guard
                        guard = None
                        return AsyncGovernedStream(resp, caller=caller, guard=stream_guard)
                    return resp
                except Exception as e:
                    err = e
                finally:
                    if guard is not None:
                        guard.release()

        # 3. 出闸后分类异常并决定重试
        kind, msg, retry_after = classify_llm_error(err)
        _notify_upstream_rate_limit(gate, err, kind, retry_after)

        if not effective_policy.is_enabled() or kind not in effective_policy.retry_kinds or attempt.is_last:
            err.kind = kind
            err.user_msg = msg
            raise err

        delay = compute_delay(effective_policy, retry_after, attempt, kind=kind)
        if on_retry:
            on_retry(caller, attempt.number, delay, ctx)

        await asyncio.sleep(delay)
        if cancel_check and cancel_check(ctx):
            raise TaskCancelledException(f"LLM async task cancelled after sleep in attempt {attempt.number}")
