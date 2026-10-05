"""51job 风控分级守卫 — fail-closed 原则的唯一判定器。

原则（plan §3.4，plan-review R2 PASS）：宁可漏采，不可硬刚。
L0 正常 / L1 单次技术异常（可重试1次，允许降级DOM）/ L2 限流（停当前词冷却）/ L3 封禁信号（立即终止全平台）。

关键约束（R1 审查修正项）：L2/L3 信号下严禁降级回 DOM 路径——在已被风控标记的
会话下高频打开页面等同于硬刚。降级仅允许 L1。

判定信号全部可从响应/页面观测：
- HTTP 非 200、content-type 非 JSON、body 含滑块/验证文案 → L3
- status != 1 且 totalCount>0 的异常空页 → L2
- 偶发超时 / JSON 解析失败 / HTTP 5xx → L1
"""
from enum import IntEnum


class RiskLevel(IntEnum):
    L0_OK = 0        # 正常响应
    L1_SOFT = 1      # 单次超时/解析失败/HTTP 5xx → 记录，可重试 1 次；仅此级允许降级 DOM
    L2_THROTTLE = 2  # 连续空页/限流信号 → 停止当前词，冷却 30 分钟
    L3_BLOCKED = 3   # 滑块/验证码/登录失效/封禁信号 → 立即终止整个平台任务


# 滑块/WAF 拦截页特征（2026-09-24 实测：阿里云 WAF，plan 附录 A）
_BLOCK_MARKERS = (
    "请按住滑块", "拖动滑块", "滑动验证", "Access Verification",
    "访问验证", "滑动以完成验证", "verify", "captcha",
)
# 限流/投递上限文案（与 delivery 引擎既有关键词同源收敛）
_THROTTLE_MARKERS = (
    "今日投递太多", "您今日投递太多", "休息一下明天再来", "达到上限", "次数过多", "访问异常",
)


def classify_http_response(status: int, content_type: str, body_text: str) -> RiskLevel:
    """对一次采集 API 响应分级。body_text 为响应体文本（可为空串）。

    status <= 0（页内 fetch 执行异常/网络故障）归 L1 技术异常（R1 P1 修复）：
    网络抖动不是风控信号，误判 L3 会直接熔断全平台任务。
    """
    if status <= 0:
        return RiskLevel.L1_SOFT
    if status == 200 and "json" in (content_type or "").lower():
        low = (body_text or "")[:4000].lower()
        if any(m.lower() in low for m in _BLOCK_MARKERS):
            return RiskLevel.L3_BLOCKED
        if any(m in (body_text or "")[:2000] for m in _THROTTLE_MARKERS):
            return RiskLevel.L2_THROTTLE
        return RiskLevel.L0_OK
    # 非 200：5xx 视为服务端抖动（L1），其余（403/429/302 到验证页等）视为风控（L3）
    if 500 <= status < 600:
        return RiskLevel.L1_SOFT
    return RiskLevel.L3_BLOCKED


def classify_api_body(body: dict) -> tuple[RiskLevel, str]:
    """对已解析的 search-pc JSON body 分级。返回 (level, reason)。

    L0：status=1 且有岗位或明确 totalCount=0（合法零结果）
    L2：status 异常但 totalCount>0（有效词被限流），或 items 空且 totalCount 推算页数覆盖当前页
    L1：body 结构完全解析不出（可能接口改版）
    """
    if not isinstance(body, dict):
        return RiskLevel.L1_SOFT, "body 非 dict（接口结构可能变化）"
    status = body.get("status")
    try:
        status = int(status)
    except (TypeError, ValueError):
        return RiskLevel.L1_SOFT, f"status 字段异常: {status!r}"
    job_node = (body.get("resultbody") or {}).get("job") or {}
    items = job_node.get("items") or []
    total = 0
    for key in ("totalCount", "total", "totalNum", "engineSearchTotal", "count"):
        val = job_node.get(key)
        if isinstance(val, int) and val > 0:
            total = val
            break
        if isinstance(val, str) and val.isdigit() and int(val) > 0:
            total = int(val)
            break
    if status == 1:
        if items or total == 0:
            return RiskLevel.L0_OK, "" if items else "合法零结果（totalCount=0）"
        # status=1 但 items 空且 total>0：请求页越界或偶发空页 → 保守按 L0（由末页收窄逻辑防越界）
        return RiskLevel.L0_OK, "空页（由 totalCount 末页收窄防越界）"
    if total > 0:
        return RiskLevel.L2_THROTTLE, f"status={status} 且 totalCount={total}：有效词被限流"
    return RiskLevel.L2_THROTTLE, f"status={status}（无法证明为合法空结果）"


def classify_page_signal(page_text: str) -> RiskLevel | None:
    """对页面文本（详情页/搜索页 DOM）做滑块/限流检测。无信号返回 None。"""
    text = page_text or ""
    if any(m in text for m in _BLOCK_MARKERS):
        return RiskLevel.L3_BLOCKED
    if any(m in text for m in _THROTTLE_MARKERS):
        return RiskLevel.L2_THROTTLE
    return None


def should_degrade_to_dom(level: RiskLevel) -> bool:
    """是否允许降级回旧 DOM 路径。仅 L1（技术异常）可以；L2/L3 严禁（fail-closed）。"""
    return level == RiskLevel.L1_SOFT


def should_terminate_task(level: RiskLevel) -> bool:
    """是否立即终止整个平台任务（L3 全停；L2 停当前词冷却 30 分钟由调用方处理）。"""
    return level == RiskLevel.L3_BLOCKED


# L2 冷却时长（秒）：停当前词 30 分钟，当日不自动重试同词
L2_COOLDOWN_SECS = 30 * 60
