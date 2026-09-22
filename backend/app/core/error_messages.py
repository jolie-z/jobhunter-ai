# 上游 LLM/网络原始报错 → 用户可行动中文提示 的统一翻译器
#
# 双层咽喉点设计（见 docs/reports/agy-review 2026-09-22/23 简历库七项修复方案）：
#   第一层：resume_upload_service 写 error_msg 时调用；
#   第二层：upload_router SSE 出口对将发文本再兜一遍。
# 幂等性：所有输出均为 _KNOWN_FRIENDLY 中的固定文案，第二层收到后直接放行，
#         不会二次翻译或重复拼接（用显式集合判定，不做启发式猜测）。
# 防泄漏：任何分支都不把原文片段（URL/堆栈/错误码/网关信息）拼回用户文案；
#         完整原文只进后端日志（调用方 logger.exception 已覆盖）。
# 匹配精度：数字类（状态码）一律 \b 词边界正则，杜绝 "requested 40251 tokens"
#         命中 "402" 之类把超长上下文误判成账单问题（R1 审查修正）。

from __future__ import annotations

import re

# (匹配规则, 用户文案)。顺序即匹配优先级：账单 → 鉴权 → 限流 → 超时 → 网络 → 网关 → 内容审核
_RULES: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"\b402\b|insufficient|quota|余额|billing|payment|arrears|欠费|配额|\bbalance\b", re.I),
        "AI 服务余额不足或配额已用完，请前往模型服务账户充值/调整额度后重试",
    ),
    (
        re.compile(r"\b401\b|\b403\b|unauthorized|forbidden|invalid[ _]api[ _]key|incorrect[ _]api[ _]key|鉴权|认证失败|api[ _]key", re.I),
        "AI 服务鉴权失败（API Key 无效或过期），请检查「白盒控制台-配置」中的 OPENAI_API_KEY",
    ),
    (
        re.compile(r"\b429\b|rate[ _]limit|too[ _]many[ _]requests|限流|请求过于频繁|throttl", re.I),
        "AI 服务请求过于频繁（触发限流），请稍等片刻再重试",
    ),
    (
        re.compile(r"timeout|timed[ _]out|deadline[ _]exceeded|超时", re.I),
        "AI 服务响应超时，请稍后重试；若持续超时请检查网络或更换模型服务",
    ),
    (
        re.compile(r"connection|connect|ssl|network|unreachable|reset[ _]by[ _]peer|broken[ _]pipe|getaddrinfo|name[ _]or[ _]service[ _]not[ _]known|网络", re.I),
        "无法连接 AI 服务，请检查网络连接后重试",
    ),
    (
        re.compile(r"\b50[0-4]\b|internal[ _]server[ _]error|bad[ _]gateway|service[ _]unavailable|无可用渠道|no[ _]available[ _]channel|模型不存在|model[ _]not[ _]found|does[ _]not[ _]exist", re.I),
        "AI 服务暂时不可用（网关/模型异常），请稍后重试，或检查模型名称是否正确",
    ),
    (
        re.compile(r"content[ _-]?filter|sensitive|敏感|审核|risk[ _]control|blocked", re.I),
        "内容未通过 AI 服务安全审核，请调整内容后重试",
    ),
]

# 本模块可能产出的全部文案（含兜底），用于幂等放行判定
_KNOWN_FRIENDLY: frozenset[str] = frozenset(msg for _, msg in _RULES) | {
    "解析失败，请重试；若持续失败请查看后端日志",
    "服务异常，请稍后重试；若持续失败请查看后端日志",
}

# 空值/纯空白时的兜底
_EMPTY_FALLBACK = "解析失败，请重试；若持续失败请查看后端日志"


def friendly_error(raw: str | None, fallback: str = "服务异常，请稍后重试；若持续失败请查看后端日志") -> str:
    """把上游原始报错翻译为固定中文文案；无法识别时返回通用兜底（不附原文）。

    幂等：输入已是本模块产出的文案时原样返回，可安全地多层嵌套调用。
    """
    if not raw or not raw.strip():
        return fallback if fallback in _KNOWN_FRIENDLY else _EMPTY_FALLBACK

    text = raw.strip()
    # 幂等放行：已是本模块文案（含历史已入库的友好文案）
    if text in _KNOWN_FRIENDLY:
        return text

    for pattern, message in _RULES:
        if pattern.search(text):
            return message

    # 未识别：固定兜底，不携带原文（防 URL/堆栈/个人数据二次泄漏）
    return fallback
