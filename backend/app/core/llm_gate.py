"""
进程级全局 LLM 限流闸门 (app/core/llm_gate.py)

设计原则与规范依据：
1. 计数与等待分离：并发槽仅在 HTTP 在飞期间持有，退避休眠与等令牌绝不占槽。
2. 显式所有权移交（GLM2-P1-1 修复）：封装 SlotGuard 对象，支持向 GovernedStream 显式移交所有权，幂等 release 杜绝二次释放。
3. 双通道配额隔离：批处理请求受 LLM_BATCH_MAX_CONCURRENCY 限制，为前台交互保底并发位。
4. 全局 429 冷却窗：遇 429 原子开启冷却，后续请求在入闸前等待，阻断连锁雪崩。
5. 线程池物理隔离（GLM-P2-1 修复）：内建独立 ThreadPoolExecutor("llm-gate")，采用守护线程，严禁与业务线程池混用。
6. 热控回滚开关（GLM2-P1-4 修复）：LLM_GATE_ENABLED 支持 settings.json 热控优先，关闭即 100% 穿透直通。
"""
from __future__ import annotations

import asyncio
import functools
import logging
import os
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, TypeVar

logger = logging.getLogger("llm_gate")

# 批处理调用方显式集合单一来源（限制在 batch 配额内，为前台交互保留空位）。
# 收录口径：仅真实存在于生产代码的 caller 名（tests/test_llm_gate_wiring.py 架构自检
# 会扫描全仓 caller= 字面量，防止死名字静默降级批量隔离——66576328 曾因名单与真实
# caller 脱节使双通道隔离整体失效）。skill_rewrite/skill_greeting 等前台交互复用模块禁止收录。
BATCH_CALLERS = {
    "step1_rule_filter",     # 侦察兵初筛（scout，Semaphore(5) 波次）
    "ai_evaluator",          # Wave 1 批量初评（wave_pipeline / executor / automation）
    "ai_scorer",             # Wave 2 批量深评（wave_pipeline / executor）
    "job_table_hygiene",     # 岗位表查重批量复核（LangChain 显式过闸）
}

T = TypeVar("T")

# ── 交互通道覆写：前台手动任务与后台定时批量的配额隔离 ──
# 用 ContextVar 而非全局开关：只有「用户手动发起」的调用链置位（asyncio.to_thread 与
# 子任务创建均拷贝当前上下文，标记可穿透到 wave_pipeline 的线程执行体），定时/自动化
# 调用链不受影响。置位后即使 caller 在 BATCH_CALLERS 名单内，也只占全局并发槽、
# 不占 LLM_BATCH_MAX_CONCURRENCY 批处理配额——杜绝「定时批量打满 2 个批处理槽 →
# 用户前台单岗评估排队 60s×N 次 → AI评估失败」的通道挤兑。
_llm_interactive_override: ContextVar[bool] = ContextVar("_llm_interactive_override", default=False)


@contextmanager
def interactive_llm_channel():
    """把当前调用链标记为前台交互通道：批处理名单内的 caller 不再占用批处理配额。"""
    token = _llm_interactive_override.set(True)
    try:
        yield
    finally:
        _llm_interactive_override.reset(token)


def is_interactive_override_active() -> bool:
    return _llm_interactive_override.get()


def _read_gate_param(name: str, default: T, caster: Callable[[Any], T], *, env_first: bool = False) -> T:
    """
    读取闸门配置参数。
    双轨优先级（规范 §二.4）：
    - 熔断/回滚开关（env_first=False）：settings.json 热控 > 环境变量 > 默认值；
    - 容量/配额参数（env_first=True）：环境变量（容器/运维规格优先） > settings.json > 默认值。
    """
    if env_first:
        env_val = os.getenv(name)
        if env_val is not None:
            try:
                return caster(env_val)
            except (ValueError, TypeError) as e:
                logger.warning("[llm_gate] 从环境变量解析配置 %s 失败，回退 settings.json: %s", name, e)
    try:
        from common.config import get_setting
        val = get_setting(name)
        if val is not None:
            return caster(val)
    except Exception as e:
        logger.warning("[llm_gate] 从 settings.json 解析配置 %s 失败，尝试读取环境变量: %s", name, e)

    if not env_first:
        env_val = os.getenv(name)
        if env_val is not None:
            try:
                return caster(env_val)
            except (ValueError, TypeError) as e:
                logger.warning("[llm_gate] 从环境变量解析配置 %s 失败，回退默认值: %s", name, e)
    return default


def _to_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "yes", "on")
    return bool(v)


def is_llm_gate_enabled() -> bool:
    """
    闸门全局启用开关（优先级 settings.json 热控 > 环境变量 > 默认 True）。
    若置为 False，闸门完全旁路直通，零延迟零等待。
    """
    return _read_gate_param("LLM_GATE_ENABLED", True, _to_bool)


def is_batch_elastic_enabled() -> bool:
    """批处理弹性并发热控开关（settings.json 热控 > 环境变量 > 默认 True）。

    开启：批处理上限随前台需求弹性伸缩——前台零需求时批处理可用满全局槽
    （闲时全给全链路指挥中心），前台到来即时收缩、保底不低于 batch_max_concurrency。
    关闭（LLM_BATCH_ELASTIC=0）：回到硬顶 batch_max_concurrency 的旧行为（2026-11-03
    之前的「批处理恒 2 槽」契约），作为一键回滚通道。
    """
    return _read_gate_param("LLM_BATCH_ELASTIC", True, _to_bool)


class SlotGuard:
    """
    并发槽守卫对象（生命周期受控与幂等释放凭证）。
    支持所有权转移给流代理，__exit__ 与 __del__ 提供双重防泄漏兜底。
    """
    def __init__(self, gate: LLMGate, caller: str, is_batch: bool = False, bypassed: bool = False,
                 holds_fg: bool = False):
        self._gate = gate
        self.caller = caller
        self.is_batch = is_batch
        self.holds_fg = holds_fg
        self._bypassed = bypassed
        self._released = bypassed
        self._lock = threading.Lock()

    def release(self) -> None:
        """幂等释放持有的槽位，杜绝二次释放引发 BoundedSemaphore 报错。"""
        with self._lock:
            if not self._released:
                self._released = True
                self._gate._release_slot(self)

    def __enter__(self) -> SlotGuard:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.release()

    def __del__(self) -> None:
        try:
            self.release()
        except Exception:
            pass


class TokenBucket:
    """线程安全的 RPM 令牌桶算法实现（基于单调时钟 monotonic）。"""
    def __init__(self, max_rpm: int):
        self.max_rpm = max(1, max_rpm)
        self.capacity = float(self.max_rpm)
        self.rate = self.capacity / 60.0  # 每秒补充令牌数
        self.tokens = self.capacity
        self.last_update = time.monotonic()
        self._lock = threading.Lock()

    def _try_consume(self) -> float:
        """尝试扣减 1 个令牌。若成功返回 0.0；若不足返回需等待的秒数。"""
        with self._lock:
            now = time.monotonic()
            elapsed = now - self.last_update
            self.last_update = now
            self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)

            if self.tokens >= 1.0:
                self.tokens -= 1.0
                return 0.0

            return (1.0 - self.tokens) / self.rate

    def wait_for_token(self, timeout: float = 60.0) -> bool:
        start = time.monotonic()
        while True:
            wait_sec = self._try_consume()
            if wait_sec <= 0.0:
                return True
            if (time.monotonic() - start) + wait_sec > timeout:
                return False
            time.sleep(min(wait_sec, 0.1))

    async def async_wait_for_token(self, timeout: float = 60.0) -> bool:
        start = time.monotonic()
        while True:
            wait_sec = self._try_consume()
            if wait_sec <= 0.0:
                return True
            if (time.monotonic() - start) + wait_sec > timeout:
                return False
            await asyncio.sleep(min(wait_sec, 0.1))


_daemon_thread_lock = threading.Lock()


class DaemonThreadPoolExecutor(ThreadPoolExecutor):
    """守护线程池：生成的 worker 线程全为 daemon 线程，进程退出或测试收尾时绝不阻塞解释器。"""
    def _adjust_thread_count(self):
        with _daemon_thread_lock:
            orig_thread = threading.Thread

            def daemon_thread(*args, **kwargs):
                kwargs["daemon"] = True
                return orig_thread(*args, **kwargs)

            try:
                threading.Thread = daemon_thread
                super()._adjust_thread_count()
            finally:
                threading.Thread = orig_thread


class LLMGate:
    """进程级全局 LLM 限流闸门单例。"""
    def __init__(self):
        # 容量与配额参数：环境变量（运维规格优先） > settings.json > 默认值（规范 §二.4）
        self.max_concurrency = _read_gate_param("LLM_MAX_CONCURRENCY", 4, int, env_first=True)
        self.batch_max_concurrency = _read_gate_param("LLM_BATCH_MAX_CONCURRENCY", 2, int, env_first=True)
        # 弹性批处理上限（闲时前台零需求 → 批处理可用满全局槽；前台到来即时收缩）
        self.batch_elastic_max = min(
            _read_gate_param("LLM_BATCH_ELASTIC_MAX", self.max_concurrency, int, env_first=True),
            self.max_concurrency,
        )
        self.max_rpm = _read_gate_param("LLM_MAX_RPM", 60, int, env_first=True)
        self.cooldown_seconds = _read_gate_param("LLM_429_COOLDOWN_SECONDS", 5.0, float, env_first=True)

        self._global_sem = threading.BoundedSemaphore(self.max_concurrency)
        self._token_bucket = TokenBucket(self.max_rpm)

        # 统一使用单调时钟 monotonic 避免墙钟回拨引发误判
        self._cooldown_until = 0.0
        self._active_slots = 0
        self._total_requests = 0
        self._total_successes = 0
        self._total_rejected = 0
        self._total_rate_limited = 0
        self._total_server_breaks = 0
        # 服务端错误熔断：连续 5xx/账号池不可用达阈值时复用全局冷却窗，
        # 阻断"逐请求全价烧完重试预算"的硬撞（2026-10-31 上游聚合网关 no_healthy_account 事故）
        self.server_breaker_threshold = _read_gate_param(
            "LLM_SERVER_BREAKER_THRESHOLD", 3, int, env_first=True)
        self.server_breaker_cooldown = _read_gate_param(
            "LLM_SERVER_BREAKER_COOLDOWN_SECONDS", 45.0, float, env_first=True)
        self._server_error_streak = 0
        self._lock = threading.Lock()
        # 弹性批处理状态（与主锁同锁，stats 快照保持一致）：
        # _batch_active = 持有批处理槽的在飞请求数；_fg_demand = 等待中/持槽中的前台请求数。
        # 批处理上限不再用固定信号量硬顶（旧 _batch_sem 恒 2），改按前台需求动态钳制。
        self._batch_active = 0
        self._fg_demand = 0
        self._slot_cond = threading.Condition(self._lock)

        workers = _read_gate_param(
            "LLM_GATE_EXECUTOR_WORKERS", max(16, self.max_concurrency * 4), int, env_first=True
        )
        self._executor = DaemonThreadPoolExecutor(max_workers=max(1, workers), thread_name_prefix="llm-gate")

    @staticmethod
    def is_batch_caller(caller: str) -> bool:
        if not caller:
            return False
        return caller.strip().lower() in BATCH_CALLERS

    def get_cooldown_remaining(self) -> float:
        """获取当前全局 429 冷却窗口剩余秒数（基于 monotonic）。"""
        with self._lock:
            return max(0.0, self._cooldown_until - time.monotonic())

    def wait_if_global_cooldown(self, timeout: float = 60.0) -> bool:
        """闸外等待全局 429 冷却，绝不提前占用并发槽。若剩余时间超过 timeout 则直接返回 False 拒绝。"""
        if not is_llm_gate_enabled():
            return True
        remaining = self.get_cooldown_remaining()
        if remaining <= 0:
            return True
        if remaining > timeout:
            logger.warning("[llm_gate] 全局 429 冷却剩余时间 (%.1fs) 超过最大等待上限 (%.1fs)，拒绝放行", remaining, timeout)
            return False
        logger.info("[llm_gate] 请求闸外等待全局 429 冷却 %.2fs...", remaining)
        time.sleep(remaining)
        return True

    async def async_wait_if_global_cooldown(self, timeout: float = 60.0) -> bool:
        """异步闸外等待全局 429 冷却，非阻塞协程。若剩余时间超过 timeout 则直接返回 False 拒绝。"""
        if not is_llm_gate_enabled():
            return True
        remaining = self.get_cooldown_remaining()
        if remaining <= 0:
            return True
        if remaining > timeout:
            logger.warning("[llm_gate] 异步全局 429 冷却剩余时间 (%.1fs) 超过最大等待上限 (%.1fs)，拒绝放行", remaining, timeout)
            return False
        logger.info("[llm_gate] 异步请求闸外等待全局 429 冷却 %.2fs...", remaining)
        await asyncio.sleep(remaining)
        return True

    def wait_for_rpm_token(self, timeout: float = 60.0) -> bool:
        """等令牌桶补充（等待期间绝不占用并发槽）。"""
        if not is_llm_gate_enabled():
            return True
        return self._token_bucket.wait_for_token(timeout=timeout)

    async def async_wait_for_rpm_token(self, timeout: float = 60.0) -> bool:
        """异步等令牌桶补充。"""
        if not is_llm_gate_enabled():
            return True
        return await self._token_bucket.async_wait_for_token(timeout=timeout)

    def _elastic_batch_cap_locked(self, elastic_on: bool) -> int:
        """批处理弹性上限（必须在 self._lock/条件下调用）。

        cap = clamp(elastic_ceiling - _fg_demand, batch_max_concurrency, elastic_ceiling)：
        前台零需求 → 批处理可用满 elastic_ceiling（默认=全局 4 槽全给全链路指挥中心）；
        前台每 +1 → 批处理上限 -1；触底不低于 batch_max_concurrency（前台保底并发位）。
        elastic_on=False（热控回滚）→ 恒等于旧硬顶 batch_max_concurrency。
        """
        if not elastic_on:
            return self.batch_max_concurrency
        ceiling = self.batch_elastic_max
        return min(max(self.batch_max_concurrency, ceiling - self._fg_demand), ceiling)

    def _acquire_batch_slot(self, timeout: float, elastic_on: bool) -> bool:
        """等待并占用一个批处理槽位（上限动态，前台到来即时收缩）。超时返回 False。"""
        deadline = time.monotonic() + timeout
        with self._slot_cond:
            while True:
                if self._batch_active < self._elastic_batch_cap_locked(elastic_on):
                    self._batch_active += 1
                    return True
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                # 上限变化（前台到来/离开）与槽位释放都会 notify；1s 切片兜底防丢通知
                self._slot_cond.wait(min(remaining, 1.0))

    def _release_batch_slot_only(self) -> None:
        """归还批处理槽位计数并唤醒等待者（全局槽获取失败时的回滚路径）。"""
        with self._slot_cond:
            self._batch_active = max(0, self._batch_active - 1)
            self._slot_cond.notify_all()

    def acquire_slot(
        self,
        caller: str = "",
        timeout: float = 60.0,
        force_interactive: bool | None = None,
    ) -> SlotGuard | None:
        """获取并发槽位凭证（双通道配额隔离 + 批处理弹性上限）。超时返回 None 表示拒绝，上层严禁旁路放行。

        force_interactive: 显式指定交互通道覆写结果。同步调用链可不传（自动读 ContextVar）；
        异步路径因 run_in_executor 不拷贝上下文，必须在事件循环内先解析再显式传入。
        """
        if not is_llm_gate_enabled():
            return SlotGuard(self, caller, is_batch=False, bypassed=True)

        with self._lock:
            self._total_requests += 1

        interactive = (
            force_interactive if force_interactive is not None else is_interactive_override_active()
        )
        is_batch = self.is_batch_caller(caller) and not interactive
        start = time.monotonic()

        if is_batch:
            # 弹性开关每次获取现读（settings.json 热控即时生效），不落缓存
            if not self._acquire_batch_slot(timeout, is_batch_elastic_enabled()):
                logger.warning("[llm_gate] 批处理请求 %s 等待批处理并发槽超时 (%.1fs)", caller, timeout)
                with self._lock:
                    self._total_rejected += 1
                return None
            remaining_timeout = max(0.1, timeout - (time.monotonic() - start))
            if not self._global_sem.acquire(timeout=remaining_timeout):
                self._release_batch_slot_only()
                logger.warning("[llm_gate] 批处理请求 %s 等待全局并发槽超时 (%.1fs)", caller, timeout)
                with self._lock:
                    self._total_rejected += 1
                return None
        else:
            # 前台需求计数先于等待建立：批处理等待者立即感知上限收缩并让位
            with self._slot_cond:
                self._fg_demand += 1
                self._slot_cond.notify_all()
            if not self._global_sem.acquire(timeout=timeout):
                with self._slot_cond:
                    self._fg_demand -= 1
                    self._slot_cond.notify_all()
                logger.warning("[llm_gate] 交互请求 %s 等待全局并发槽超时 (%.1fs)", caller, timeout)
                with self._lock:
                    self._total_rejected += 1
                return None

        with self._lock:
            self._active_slots += 1

        return SlotGuard(self, caller, is_batch=is_batch, bypassed=False, holds_fg=not is_batch)

    def _release_slot(self, guard: SlotGuard) -> None:
        """底层槽位归还。"""
        if guard._bypassed:
            return
        with self._slot_cond:
            self._active_slots = max(0, self._active_slots - 1)
            if guard.is_batch:
                self._batch_active = max(0, self._batch_active - 1)
            if guard.holds_fg:
                self._fg_demand = max(0, self._fg_demand - 1)
            # 唤醒批处理等待者：槽位释放/前台离开都会让弹性上限变大
            self._slot_cond.notify_all()

        try:
            self._global_sem.release()
        except ValueError:
            pass

    async def async_acquire_slot(self, caller: str = "", timeout: float = 60.0) -> SlotGuard | None:
        """异步获取并发槽位（委托独立守护线程池等待 semaphore，不阻塞事件循环）。

        run_in_executor 不拷贝 ContextVar：交互通道覆写必须先在事件循环内解析成
        显式参数再跨越线程边界，否则前台手动任务的标记会在线程池中静默丢失。
        """
        if not is_llm_gate_enabled():
            return SlotGuard(self, caller, is_batch=False, bypassed=True)
        loop = asyncio.get_running_loop()
        interactive = is_interactive_override_active()
        return await loop.run_in_executor(
            self._executor,
            functools.partial(self.acquire_slot, caller, timeout, force_interactive=interactive),
        )

    def notify_rate_limited(self, retry_after: float | None = None) -> None:
        """收到上游 429 速率限制时，原子开启全局冷却窗（基于 monotonic，上限 300s）。"""
        cd = retry_after if retry_after and retry_after > 0 else self.cooldown_seconds
        cd = min(cd, 300.0)  # 300s sanity 兜底
        with self._lock:
            self._cooldown_until = max(self._cooldown_until, time.monotonic() + cd)
            self._total_rate_limited += 1
            logger.warning("[llm_gate] 触发全局 429 冷却窗: 持续 %.1fs", cd)

    def notify_server_error(self) -> None:
        """上游 5xx/服务端故障（含账号池整体不可用）计数：连续达阈值即开启全局熔断冷却窗。

        与 429 冷却共用同一冷却窗机制（wait_if_global_cooldown 统一闸外等待）；
        任一次成功即清零计数——间歇性 5xx 不会误触发熔断。
        """
        with self._lock:
            self._server_error_streak += 1
            if self._server_error_streak < max(1, self.server_breaker_threshold):
                return
            self._server_error_streak = 0
            self._total_server_breaks += 1
            cd = min(max(1.0, self.server_breaker_cooldown), 300.0)
            self._cooldown_until = max(self._cooldown_until, time.monotonic() + cd)
            logger.warning(
                "[llm_gate] 连续 %d 次上游服务端错误，触发全局熔断冷却窗: 持续 %.1fs",
                self.server_breaker_threshold, cd,
            )

    def record_success(self) -> None:
        """记录调用成功（同时清零服务端错误连击计数）。"""
        with self._lock:
            self._total_successes += 1
            self._server_error_streak = 0

    def stats(self) -> dict[str, Any]:
        """输出闸门当前实时状态快照，供系统诊断与监控。"""
        elastic_on = is_batch_elastic_enabled()
        with self._lock:
            cooldown_rem = max(0.0, self._cooldown_until - time.monotonic())
            return {
                "enabled": is_llm_gate_enabled(),
                "max_concurrency": self.max_concurrency,
                "batch_max_concurrency": self.batch_max_concurrency,
                "batch_elastic": elastic_on,
                "batch_elastic_max": self.batch_elastic_max,
                "batch_effective_cap": self._elastic_batch_cap_locked(elastic_on),
                "batch_active": self._batch_active,
                "fg_demand": self._fg_demand,
                "active_slots": self._active_slots,
                "max_rpm": self.max_rpm,
                "available_tokens": round(self._token_bucket.tokens, 2),
                "cooldown_remaining": round(cooldown_rem, 2),
                "total_requests": self._total_requests,
                "total_successes": self._total_successes,
                "total_rejected": self._total_rejected,
                "total_rate_limited": self._total_rate_limited,
                "total_server_breaks": self._total_server_breaks,
                "server_error_streak": self._server_error_streak,
            }


_gate_singleton: LLMGate | None = None
_gate_singleton_lock = threading.Lock()


def get_llm_gate() -> LLMGate:
    global _gate_singleton
    if _gate_singleton is None:
        with _gate_singleton_lock:
            if _gate_singleton is None:
                _gate_singleton = LLMGate()
    return _gate_singleton


def reset_llm_gate() -> None:
    global _gate_singleton
    with _gate_singleton_lock:
        if _gate_singleton is not None:
            try:
                _gate_singleton._executor.shutdown(wait=False)
            except Exception:
                pass
        _gate_singleton = LLMGate()
