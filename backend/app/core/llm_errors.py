"""
统一 LLM 错误分类与退避解析模块 (app/core/llm_errors.py)

职责：
1. 提取标准化错误类别 LLMErrorKind（rate_limited, quota, auth, timeout 等）
2. 优先基于结构化对象（status_code、SDK 异常类型、响应头）精准判定，杜绝粗粒度子串匹配引发的误判
3. 防御性解析 Retry-After 标头（封顶 60s）
4. 提供统一的可读解释文案与上层重试指导
"""
from __future__ import annotations

import enum
import logging
import re
from typing import Any

logger = logging.getLogger("llm_errors")


class LLMErrorKind(str, enum.Enum):
    rate_limited = "rate_limited"      # 429 速率限制（RPM/TPM/并发超限）
    quota = "quota"                    # 余额不足/配额耗尽（402/insufficient_quota）
    auth = "auth"                      # 鉴权失败（401/API Key 无效或过期）
    timeout = "timeout"                # 超时（APITimeoutError/timed out）
    connection = "connection"          # 网络连接中断/DNS 失败（APIConnectionError）
    bad_request = "bad_request"        # 客户端请求错误（400/BadRequestError）
    server = "server"                  # 服务端错误（500/502/503/504）
    unknown = "unknown"                # 未知异常


class LLMGateTimeoutError(Exception):
    """限流闸门等待超时或拒绝（并发槽打满、RPM 耗尽或处于全局 429 冷却期）。"""
    def __init__(
        self,
        message: str = "LLM 限流闸门等待超时",
        *,
        kind: LLMErrorKind = LLMErrorKind.rate_limited,
        retry_after: float | None = None,
    ):
        super().__init__(message)
        self.status_code = 429
        self.kind = kind
        self.retry_after = retry_after
        self.user_msg = message


def _extract_retry_after(resp: Any) -> float | None:
    """从响应对象防御性提取并验证 Retry-After 标头（0 < val <= 60.0s；为 0 时保底 1.0s，确保间隔严格非零）。"""
    if resp is None:
        return None
    headers = getattr(resp, "headers", None) or {}
    header_val = None
    if hasattr(headers, "get"):
        header_val = headers.get("retry-after") or headers.get("Retry-After")
    if header_val is not None:
        try:
            val = float(header_val)
            if val <= 0.0:
                return 1.0  # 标头为 0 时保底 1.0s，杜绝 0 秒无效/狂发退避
            if val <= 60.0:
                return val
        except (ValueError, TypeError):
            pass
    return None


def _extract_status_code(exc: Exception, resp: Any) -> int | None:
    """安全提取 HTTP 状态码数值。"""
    code = getattr(exc, "status_code", None)
    if isinstance(code, int):
        return code
    if resp is not None:
        resp_code = getattr(resp, "status_code", None)
        if isinstance(resp_code, int):
            return resp_code
    return None


def compute_backoff_delay(
    attempt: int,
    retry_after: float | None = None,
    *,
    kind: LLMErrorKind | None = None,
    max_delay: float = 10.0,
) -> float:
    """
    统一计算退避等待秒数（有界、严格非零）：
    - 若服务端返回 Retry-After 标头，优先采用标头秒数（为 0 时保底 1.0s，封顶 max_delay）；
    - 速率限制或服务端异常按指数退避：1.0s * (2 ** attempt)，封顶 max_delay；
    - 其余网络异常（timeout/connection）采用温和线性退避：0.5s * (attempt + 1)；
    - 保证返回值严格非零且 <= max_delay。
    """
    if retry_after is not None:
        ra = float(retry_after)
        return min(max_delay, 1.0 if ra <= 0 else ra)
    if kind in (LLMErrorKind.rate_limited, LLMErrorKind.server, None):
        return min(max_delay, 1.0 * (2 ** attempt))
    return min(max_delay, 0.5 * (attempt + 1))


def classify_llm_error(exc: Exception) -> tuple[LLMErrorKind, str, float | None]:
    """
    统一将各类 LLM 调用异常（OpenAI SDK、HTTPX、字符串包装异常等）
    分类为核心类型枚举、友好用户文案以及建议的退避时间 (Retry-After)。

    返回: (kind, user_msg, retry_after)
    - kind: LLMErrorKind 枚举
    - user_msg: 面向用户界面展示或上层调用的解释文案
    - retry_after: 服务端指定的等待秒数（1.0 ~ 60.0s，若无则为 None）
    """
    if isinstance(exc, LLMGateTimeoutError):
        return (exc.kind, exc.user_msg, exc.retry_after)

    resp = getattr(exc, "response", None)
    retry_after = _extract_retry_after(resp)
    status_code = _extract_status_code(exc, resp)

    err_str = str(exc)
    err_lower = err_str.lower()
    exc_type = type(exc).__name__.lower()

    # 安全防御性提取 SDK body 或 code（【P1 修复】对 body 及 body["error"] 严格判定 isinstance(dict)，杜绝 None/str 抛 AttributeError）
    body = getattr(exc, "body", None)
    err_code = ""
    if isinstance(body, dict):
        raw_code = body.get("code")
        err_obj = body.get("error")
        err_subcode = err_obj.get("code") if isinstance(err_obj, dict) else None
        err_code = str(raw_code or err_subcode or "").lower()

    # 1. 优先结构化状态码与类型判定

    # 鉴权错误 (401 / AuthenticationError)
    if status_code == 401 or "authenticationerror" in exc_type or "invalid api key" in err_lower or "unauthorized" in err_lower:
        return (
            LLMErrorKind.auth,
            "AI 模型鉴权失败（API Key 无效或过期），请检查 OPENAI_API_KEY 配置",
            None,
        )

    # 余额/额度不足 (402 或特定的 insufficient_quota / 余额不足)
    # 注意：严禁用孤立的 "insufficient" 匹配，必须精准匹配 "insufficient_quota" 或 "余额不足"
    if (
        status_code == 402
        or err_code == "insufficient_quota"
        or "insufficient_quota" in err_lower
        or "insufficient quota" in err_lower
        or "billing" in err_lower
        or "余额不足" in err_str
        or "欠费" in err_str
    ):
        return (
            LLMErrorKind.quota,
            "AI 模型余额不足/配额耗尽，请检查模型服务账户后重试",
            None,
        )

    # 速率限制 (429 / RateLimitError / 智谱 1302 独立单词匹配 / 明确速率限制关键词)
    if (
        status_code == 429
        or "ratelimiterror" in exc_type
        or bool(re.search(r"\b1302\b", err_str))
        or "rate limit" in err_lower
        or "速率限制" in err_str
        or "达到速率限制" in err_str
        or "too many requests" in err_lower
    ):
        return (
            LLMErrorKind.rate_limited,
            "AI 模型触发速率限制，请稍后重试或减少并发任务",
            retry_after,
        )

    # 超时 (APITimeoutError / timeout)
    if "timeouterror" in exc_type or status_code == 408 or "timed out" in err_lower or "timeout" in err_lower:
        return (
            LLMErrorKind.timeout,
            "AI 模型连接超时，请检查网络后重试",
            None,
        )

    # 网络连接中断 (APIConnectionError / connection)
    if "connectionerror" in exc_type or "无法建立连接" in err_str or "connection error" in err_lower:
        return (
            LLMErrorKind.connection,
            "AI 模型无法建立连接，请检查网络或 Base URL",
            None,
        )

    # 服务端异常 (500 / 502 / 503 / 504 / InternalServerError)
    if (
        (status_code is not None and 500 <= status_code <= 599)
        or "internalservererror" in exc_type
        or any(re.search(rf"\b{code}\b", err_lower) for code in ("500", "502", "503", "504"))
    ):
        return (
            LLMErrorKind.server,
            f"模型服务端异常（{status_code or '5xx'}）：{err_str[:140]}",
            retry_after,
        )

    # 客户端请求错误 (400 / 404 / BadRequestError / NotFoundError)
    # 使用状态码或单词边界正则匹配，杜绝形如 "400ms" 误判
    if (
        status_code in (400, 404)
        or "badrequesterror" in exc_type
        or "notfounderror" in exc_type
        or bool(re.search(r"\b(400|404)\b", err_lower))
    ):
        return (
            LLMErrorKind.bad_request,
            f"服务端拒绝请求（{status_code or '400'}）：{err_str[:140]}",
            None,
        )

    # 兜底未知异常
    return (
        LLMErrorKind.unknown,
        f"LLM 映射流程异常: {err_str[:160]}",
        None,
    )
