# 📂 app/core/llm_tracker.py
"""
全局 LLM Token 消耗埋点拦截层（统一收口）

设计目标：
1. 零遗漏 —— 只要 LLM 调用经过本模块包装的 client，token 消耗必被记录。
2. 零侵入 —— 调用方代码（client.chat.completions.create(...)）完全不用改。
3. 零阻塞 —— 写 SQLite 走 daemon 线程，主流程绝不被拖慢；写失败仅日志告警。

工作原理：
    用一个轻量代理对象包住原生 OpenAI/AsyncOpenAI client，只劫持
    `chat.completions.create` 这一个方法，在拿到 response 后从
    `response.usage` 抽取 prompt/completion/total_tokens，丢给
    log_token_usage() 写库。其余属性/方法全部透传给原生 client。
"""
from __future__ import annotations

import asyncio
import inspect
import logging
import os
import threading
from typing import Any

logger = logging.getLogger("llm_tracker")

# 是否全局禁用埋点（测试场景用环境变量关闭，避免污染统计）
_TRACKING_DISABLED = os.getenv("DISABLE_TOKEN_TRACKING", "").lower() in ("1", "true", "yes")


def _safe_log(
    action_name: str,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
    model_name: str,
    job_id: str | None = None,
    caller: str = "",
    estimated: int = 0,
    cached_tokens: int = 0,
) -> None:
    """异步写库：丢给 daemon 线程，绝不阻塞调用方。"""
    if _TRACKING_DISABLED:
        return
    # 全 0 的话没必要记（可能是异常兜底路径）
    if not any([prompt_tokens, completion_tokens, total_tokens]):
        return

    def _write():
        try:
            # 延迟导入，避免循环依赖
            from app.core.model_pricing import calc_cost_detailed
            from app.services.token_service import log_token_usage
            cost, is_est = calc_cost_detailed(model_name, prompt_tokens or 0, completion_tokens or 0, cached_tokens or 0)
            final_estimated = 1 if (estimated or is_est) else 0
            logger.info(
                f"[llm_tracker] 记录 Token: action={action_name}, model={model_name}, "
                f"prompt={prompt_tokens}, cached={cached_tokens}, completion={completion_tokens}, "
                f"cost=¥{cost:.6f}, estimated={bool(final_estimated)}"
            )
            log_token_usage(
                action_name=action_name,
                prompt_tokens=prompt_tokens or 0,
                completion_tokens=completion_tokens or 0,
                total_tokens=total_tokens or 0,
                model_name=model_name or "unknown",
                job_id=job_id,
                caller=caller,
                cost_cny=cost,
                estimated=final_estimated,
                cached_tokens=cached_tokens or 0,
            )
        except Exception as e:
            logger.warning(f"[llm_tracker] 写 token_log 失败（不影响主流程）: {e}")

    threading.Thread(target=_write, daemon=True).start()


def _guess_action_name(skip_frames: int = 3) -> str:
    """
    通过调用栈反推一个可读的 action_name。
    跳过本模块内部的几层包装，定位到真正业务调用方的函数名。
    """
    try:
        stack = inspect.stack()
        # 0=_guess_action_name, 1=_safe_log 调用方, 2=包装层, 3=业务调用方
        for frame_info in stack[skip_frames:]:
            mod = inspect.getmodule(frame_info.frame)
            mod_name = mod.__name__ if mod else "?"
            # 跳过本模块自身
            if "llm_tracker" in mod_name:
                continue
            func = frame_info.function or "unknown"
            # 用模块短名 + 函数名，方便在大盘里区分来源
            short_mod = mod_name.split(".")[-1] if mod_name != "?" else "?"
            return f"{short_mod}:{func}"
        return "llm_call"
    except Exception:
        return "llm_call"


def _extract_job_id(kwargs: dict, _args: tuple) -> str | None:
    """
    尽力从 create() 的 messages / extra_body / 额外参数中提取 job_id。
    多数调用方没有显式传 job_id，这里宽松匹配，找不到就返回 None。
    """
    # 1. 显式通过 extra_body 传的
    extra = kwargs.get("extra_body") or {}
    if isinstance(extra, dict):
        for k in ("job_id", "jobId", "task_id"):
            v = extra.get(k)
            if v:
                return str(v)
    # 2. 直接塞在 kwargs 里的（虽然 create 不认，但调用方可能误传）
    for k in ("job_id", "jobId", "task_id"):
        v = kwargs.get(k)
        if v:
            return str(v)
    return None


def _extract_model_name(kwargs: dict, response: Any) -> str:
    """从调用参数或 response 中拿 model 名。"""
    m = kwargs.get("model")
    if m:
        return str(m)
    try:
        return str(getattr(response, "model", "") or "unknown")
    except Exception:
        return "unknown"


def _read_cached_tokens(usage: Any) -> int:
    """
    从 usage（对象或字典）中提取命中缓存的 prompt token 数。
    兼容三种形态：
    - OpenAI SDK: usage.prompt_tokens_details.cached_tokens
    - dict: usage["prompt_tokens_details"]["cached_tokens"]
    - LangChain usage_metadata: usage["input_token_details"]["cache_read"]
    供应商不支持 / 字段缺失时返回 0。
    """
    try:
        if usage is None:
            return 0
        details = None
        if isinstance(usage, dict):
            details = usage.get("prompt_tokens_details")
            if details is None:
                # LangChain usage_metadata 风格：input_token_details.cache_read
                input_details = usage.get("input_token_details") or {}
                if isinstance(input_details, dict):
                    return int(input_details.get("cache_read", 0) or 0)
                return int(getattr(input_details, "cache_read", 0) or 0)
        else:
            details = getattr(usage, "prompt_tokens_details", None)
        if details is None:
            return 0
        if isinstance(details, dict):
            return int(details.get("cached_tokens", 0) or 0)
        return int(getattr(details, "cached_tokens", 0) or 0)
    except Exception:
        return 0


def _read_usage(response: Any) -> tuple[int, int, int, int]:
    """从 OpenAI 非流式 response 中读 usage，兼容字段缺失。返回 (prompt, completion, total, cached)。"""
    usage = getattr(response, "usage", None)
    if usage is None:
        return 0, 0, 0, 0
    pt = getattr(usage, "prompt_tokens", 0) or 0
    ct = getattr(usage, "completion_tokens", 0) or 0
    tt = getattr(usage, "total_tokens", 0) or (pt + ct)
    cached = _read_cached_tokens(usage)
    return int(pt), int(ct), int(tt), cached


def _estimate_tokens_from_messages(messages: list) -> tuple[int, int, int]:
    """
    本地粗估 prompt token（流式场景供应商不返回 usage 时的兜底）。
    经验值：中文 ~1.5 字/token，英文 ~4 字符/token。这里取折中 1.5。
    """
    try:
        total_chars = 0
        for m in messages or []:
            c = m.get("content", "") if isinstance(m, dict) else str(m)
            total_chars += len(str(c))
        pt = max(1, total_chars // 2)  # 字符数/2 ≈ token 数（偏保守）
        return pt, 0, pt
    except Exception:
        return 0, 0, 0


# ============================================================
# 包装层：用 __getattr__ 透传一切，只劫持 create
# ============================================================

class _TrackedCompletions:
    """劫持 chat.completions.create 的最小代理。"""
    def __init__(self, raw_completions, model_default: str | None = None, caller: str = ""):
        self._raw = raw_completions
        self._model_default = model_default
        self._caller = caller

    def __getattr__(self, name):
        return getattr(self._raw, name)

    def create(self, *args, **kwargs):
        """同步非流式：调原生 → 读 usage → 写库 → 原样返回。"""
        is_stream = kwargs.get("stream", False)
        messages = kwargs.get("messages") or []
        model = kwargs.get("model") or self._model_default or "unknown"

        if is_stream:
            return self._wrap_stream_sync(self._raw.create(*args, **kwargs), messages, model)

        response = self._raw.create(*args, **kwargs)
        try:
            pt, ct, tt, cached = _read_usage(response)
            action = _guess_action_name(skip_frames=2)
            job_id = _extract_job_id(kwargs, args)
            _safe_log(action, pt, ct, tt, _extract_model_name(kwargs, response), job_id,
                      caller=self._caller, cached_tokens=cached)
        except Exception as e:
            logger.warning(f"[llm_tracker] 同步埋点异常: {e}")
        return response

    def _wrap_stream_sync(self, stream, messages, model):
        """同步流式：迭代 chunk，抓末尾 usage，找不到则本地估算。"""
        collected_content_len = 0
        usage_pt = usage_ct = usage_tt = usage_cached = 0
        last_chunk = None
        caller = self._caller

        class _GenProxy:
            def __iter__(inner):
                nonlocal collected_content_len, usage_pt, usage_ct, usage_tt, usage_cached, last_chunk
                try:
                    for chunk in stream:
                        last_chunk = chunk
                        # 累积 completion 内容长度（用于兜底估算）
                        try:
                            delta = chunk.choices[0].delta.content if chunk.choices else None
                            if delta:
                                collected_content_len += len(str(delta))
                        except Exception:
                            pass
                        # 流式 usage 通常在最后一个 chunk
                        u = getattr(chunk, "usage", None)
                        if u:
                            usage_pt = getattr(u, "prompt_tokens", 0) or usage_pt
                            usage_ct = getattr(u, "completion_tokens", 0) or usage_ct
                            usage_tt = getattr(u, "total_tokens", 0) or usage_tt
                            usage_cached = _read_cached_tokens(u) or usage_cached
                        yield chunk
                finally:
                    _finish_stream_log(usage_pt, usage_ct, usage_tt,
                                       collected_content_len, messages, model, caller=caller,
                                       cached_tokens=usage_cached)

        return _GenProxy()


class _TrackedAsyncCompletions:
    """异步版 chat.completions.create 代理。"""
    def __init__(self, raw_completions, model_default: str | None = None, caller: str = ""):
        self._raw = raw_completions
        self._model_default = model_default
        self._caller = caller

    def __getattr__(self, name):
        return getattr(self._raw, name)

    async def create(self, *args, **kwargs):
        is_stream = kwargs.get("stream", False)
        messages = kwargs.get("messages") or []
        model = kwargs.get("model") or self._model_default or "unknown"

        if is_stream:
            return self._wrap_stream_async(
                await self._raw.create(*args, **kwargs), messages, model
            )

        response = await self._raw.create(*args, **kwargs)
        try:
            pt, ct, tt, cached = _read_usage(response)
            action = _guess_action_name(skip_frames=2)
            job_id = _extract_job_id(kwargs, args)
            _safe_log(action, pt, ct, tt, _extract_model_name(kwargs, response), job_id,
                      caller=self._caller, cached_tokens=cached)
        except Exception as e:
            logger.warning(f"[llm_tracker] 异步埋点异常: {e}")
        return response

    def _wrap_stream_async(self, stream, messages, model):
        """异步流式代理。"""
        collected_content_len = 0
        usage_pt = usage_ct = usage_tt = usage_cached = 0
        caller = self._caller

        class _AsyncGenProxy:
            def __aiter__(inner):
                return inner

            async def __anext__(inner):
                nonlocal collected_content_len, usage_pt, usage_ct, usage_tt, usage_cached
                try:
                    chunk = await stream.__anext__()
                except StopAsyncIteration:
                    _finish_stream_log(usage_pt, usage_ct, usage_tt,
                                       collected_content_len, messages, model, caller=caller,
                                       cached_tokens=usage_cached)
                    raise
                # 累积内容长度
                try:
                    delta = chunk.choices[0].delta.content if chunk.choices else None
                    if delta:
                        collected_content_len += len(str(delta))
                except Exception:
                    pass
                # 抓 usage
                u = getattr(chunk, "usage", None)
                if u:
                    usage_pt = getattr(u, "prompt_tokens", 0) or usage_pt
                    usage_ct = getattr(u, "completion_tokens", 0) or usage_ct
                    usage_tt = getattr(u, "total_tokens", 0) or usage_tt
                    usage_cached = _read_cached_tokens(u) or usage_cached
                return chunk

        return _AsyncGenProxy()


def _finish_stream_log(usage_pt, usage_ct, usage_tt, content_len, messages, model, caller="", cached_tokens: int = 0):
    """流式结束时统一收尾：有精确 usage 就记，没有就用本地估算兜底。"""
    try:
        estimated = 0
        if usage_tt:
            pt, ct, tt = int(usage_pt), int(usage_ct), int(usage_tt)
        else:
            # 兜底估算
            pt, _, _ = _estimate_tokens_from_messages(messages)
            ct = max(0, content_len // 2)
            tt = pt + ct
            estimated = 1
        action = _guess_action_name(skip_frames=4)
        _safe_log(action, pt, ct, tt, model, None, caller=caller, estimated=estimated,
                  cached_tokens=cached_tokens if usage_tt else 0)
    except Exception as e:
        logger.warning(f"[llm_tracker] 流式收尾埋点异常: {e}")


# ============================================================
# 对外入口：make_tracked_client
# ============================================================

class TrackedClient:
    """
    透明代理：包住原生 OpenAI/AsyncOpenAI 实例。
    只重写 .chat.completions 这条路径以挂载埋点，其余属性全透传。
    """
    def __init__(self, raw_client, model_default: str | None = None, caller: str = ""):
        # 用 object.__setattr__ 避开本类 __setattr__/__getattr__ 递归
        object.__setattr__(self, "_raw", raw_client)
        object.__setattr__(self, "_model_default", model_default)
        object.__setattr__(self, "_caller", caller)
        # 预先包装好 chat.completions
        raw_chat = raw_client.chat
        raw_completions = raw_chat.completions
        # 根据原生 client 类型选择同步/异步包装
        if _is_async_client(raw_client):
            tracked = _TrackedAsyncCompletions(raw_completions, model_default, caller=caller)
        else:
            tracked = _TrackedCompletions(raw_completions, model_default, caller=caller)
        # 重建一个轻量 chat 对象，只换掉 completions 属性
        chat_proxy = _ChatProxy(raw_chat, tracked)
        object.__setattr__(self, "_chat_proxy", chat_proxy)

    @property
    def chat(self):
        return self._chat_proxy

    def __getattr__(self, name):
        # 非 chat 的属性全部透传给原生 client
        return getattr(self._raw, name)


class _ChatProxy:
    """chat 代理：只替换 .completions，其余属性透传。"""
    def __init__(self, raw_chat, tracked_completions):
        self._raw = raw_chat
        self.completions = tracked_completions

    def __getattr__(self, name):
        return getattr(self._raw, name)


def _is_async_client(client: Any) -> bool:
    """判断原生 client 是 AsyncOpenAI 还是 OpenAI。"""
    # AsyncOpenAI 的 chat.completions.create 是协程函数
    try:
        create = client.chat.completions.create
        if asyncio.iscoroutinefunction(create):
            return True
    except Exception:
        pass
    cls_name = type(client).__name__
    return cls_name == "AsyncOpenAI"


def make_tracked_client(raw_client: Any, model_default: str | None = None, caller: str = "") -> TrackedClient:
    """
    对外统一入口：把任意 OpenAI / AsyncOpenAI client 包装成带埋点的 TrackedClient。

    用法（在 client 工厂函数里）：
        return make_tracked_client(OpenAI(...), caller="ai_evaluator")

    参数:
        raw_client: 原生 OpenAI 或 AsyncOpenAI 实例
        model_default: 默认模型名（调用方未在 create 中指定 model 时使用）
        caller: 调用来源标签（如 "ai_evaluator", "step1_ai_scout"），用于大盘按模块统计
    """
    if raw_client is None:
        return None
    # 已经包装过就不重复包
    if isinstance(raw_client, TrackedClient):
        return raw_client
    return TrackedClient(raw_client, model_default=model_default, caller=caller)


# ============================================================
# LangChain 专用：BaseCallbackHandler
# 用于 ChatOpenAI（agent_workflow / agent_router 等不走 OpenAI SDK 的场景）
# ============================================================

def make_langchain_token_callback(model_name: str | None = None, caller: str = ""):
    """
    创建一个 LangChain 回调处理器，在每次 LLM 调用结束时抽取 token usage 写库。

    用法：
        from langchain_openai import ChatOpenAI
        llm = ChatOpenAI(..., callbacks=[make_langchain_token_callback("gpt-4o", caller="agent_workflow")])
    """
    try:
        from langchain_core.callbacks import BaseCallbackHandler
    except ImportError:
        # LangChain 未安装时返回空列表，不影响其他功能
        return None

    model = model_name
    _caller = caller

    class TokenCallbackHandler(BaseCallbackHandler):
        """LangChain 回调：on_llm_end 时从 response.llm_output 读 token usage。"""

        def on_llm_end(self, response, **kwargs):
            try:
                llm_output = getattr(response, "llm_output", None) or {}
                usage = llm_output.get("token_usage") or llm_output.get("usage") or {}
                if not usage:
                    generations = getattr(response, "generations", []) or []
                    for gen_list in generations:
                        for gen in (gen_list if isinstance(gen_list, list) else [gen_list]):
                            msg = getattr(gen, "message", None)
                            if msg:
                                usage = getattr(msg, "usage_metadata", None) or (getattr(msg, "response_metadata", {}) or {}).get("token_usage") or {}
                                if usage:
                                    break
                        if usage:
                            break

                pt = int(usage.get("prompt_tokens", 0) or usage.get("input_tokens", 0) or 0)
                ct = int(usage.get("completion_tokens", 0) or usage.get("output_tokens", 0) or 0)
                tt = int(usage.get("total_tokens", 0) or (pt + ct))
                cached = _read_cached_tokens(usage)
                action = _guess_action_name(skip_frames=2)
                _safe_log(action, pt, ct, tt, model or "langchain", None, caller=_caller,
                          cached_tokens=cached)
            except Exception as e:
                logger.warning(f"[llm_tracker] LangChain 回调埋点异常: {e}")

    return TokenCallbackHandler()
