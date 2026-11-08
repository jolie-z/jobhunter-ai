"""
LLM 网关体检探针
================
供指挥中心「检测恢复」按钮使用：用当前生效的清洗 LLM 通道（与 AI 侦察兵同一配置，
洗通道专项配置优先，回落主通道）向网关发一次最小请求，返回 {ok, latency_ms, model,
error_kind, message}。失败时错误分类复用 app/core/llm_errors.classify_llm_error，
与链路阻塞登记（pipeline_blocked）同源同口径。

探测走 1 token 的真实 chat 推理路径：网关的 /models 只是静态路由表，账号池整体
不可用（2026-10-31 上游聚合网关 no_healthy_account 事故实测）时照样返回 200，探测不出
故障。仅当网关裁剪了 chat 路由（404/405）时降级为 GET /models 保底，保证「网关
活着但裁剪了 chat 路由」的部署也能检出可用。
"""
import logging
import time
from datetime import datetime

logger = logging.getLogger(__name__)

# 实测 上游聚合网关 对 deepseek-v4.1-flash-sg 的典型延迟 10-23s（/status last_latency_ms≈10068），
# 8s 超时会把健康网关误判为不可用→定时发射被误跳过（2026-10-31 重启后验收实测 8045ms 超时），
# 故放宽到 30s；对正常网关 probe 约 1-2s 返回，不影响日常发射节奏
_PROBE_TIMEOUT_SECONDS = 30.0


def _effective_llm_config() -> tuple[str | None, str | None, str | None]:
    """返回 (api_key, base_url, model)：优先清洗通道实际生效配置（阻塞根因所在通道）。"""
    try:
        from job_processor.step1_rule_filter import _cleaner_llm_config
        key, url, model = _cleaner_llm_config()
        if url:
            return key, url, model
    except Exception as e:
        logger.warning(f"[llm_health] 读取清洗通道配置失败，回落主通道: {e}")
    from common.config import _cfg
    return (
        _cfg("OPENAI_API_KEY", json_key="OPENAI_API_KEY"),
        _cfg("OPENAI_BASE_URL", "LLM_BASE_URL", json_key="OPENAI_BASE_URL"),
        _cfg("OPENAI_MODEL", "LLM_MODEL", json_key="OPENAI_MODEL"),
    )


def _classify_exception(exc: Exception) -> tuple[str, str]:
    from app.core.llm_errors import classify_llm_error
    kind, user_msg, _retry_after = classify_llm_error(exc)
    return (kind.value if hasattr(kind, "value") else str(kind)), user_msg


def probe_llm(timeout: float = _PROBE_TIMEOUT_SECONDS) -> dict:
    """向 LLM 网关发一次最小请求。绝不抛异常：任何失败都折叠为 ok=False 的结果体。"""
    key, url, model = _effective_llm_config()
    if not url:
        return {
            "ok": False, "latency_ms": None, "model": model,
            "error_kind": "bad_request",
            "message": "未配置 LLM 服务地址（OPENAI_BASE_URL）",
            "hint": "请先在配置页填写 LLM 服务地址与密钥",
            "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    import httpx
    headers = {"Authorization": f"Bearer {key or 'sk-probe'}"}
    base = str(url).rstrip("/")
    started = time.monotonic()

    def _latency() -> int:
        return int((time.monotonic() - started) * 1000)

    try:
        with httpx.Client(trust_env=False, timeout=timeout) as client:
            if not model:
                # 未配置模型名：chat 探测无意义（无效模型名会被网关卡通常判 400，
                # 造成"网关健康却报不可用"的误报停跑），降级为 /models 存活检查
                resp = client.get(f"{base}/models", headers=headers)
                resp.raise_for_status()
                return {
                    "ok": True, "latency_ms": _latency(), "model": None,
                    "error_kind": None,
                    "message": "网关可达（未配置模型名，仅完成存活检查，未验证账号池）",
                    "hint": "请在配置页填写模型名以启用完整账号池体检",
                    "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
            # 必须走真实推理路径：/models 是静态路由表，账号池全灭时照样 200（实测），
            # 只有 1 token chat 探测才会命中网关的账号池健康检查
            resp = client.post(
                f"{base}/chat/completions",
                headers=headers,
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 1,
                },
            )
            if resp.status_code in (404, 405):
                # 网关裁剪了 chat 路由：降级为 /models 保底（聊胜于无的存活检查）
                resp = client.get(f"{base}/models", headers=headers)
            resp.raise_for_status()
        return {
            "ok": True, "latency_ms": _latency(), "model": model,
            "error_kind": None, "message": "LLM 网关可用", "hint": None,
            "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    except Exception as e:
        kind, user_msg = _classify_exception(e)
        logger.warning(f"[llm_health] LLM 体检失败（kind={kind}）: {e}")
        return {
            "ok": False, "latency_ms": _latency(), "model": model,
            "error_kind": kind, "message": user_msg,
            "hint": str(e)[:200],
            "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
