"""投递失败分诊（自愈体系 L1）：区分暂时性 / 持久性故障，遏制徒劳重试。

背景：定时发射波次只看飞书门牌（跟进状态=待投递），不看失败史——
持久性故障（引擎 bug、物料缺失、岗位下架）重试一百次也不会好，
暂时性故障（登录态、浏览器、网络抖动）重试才有意义且大概率自愈。

规则：
- 持久性故障：波次不再自动发射，岗位留在「执行失败」Tab 等人工处置（L2/L3 自愈的入口）；
- 暂时性故障：保留自动重试，但连续失败达 MAX_AUTO_RETRIES 后同样停手，防止无限空转；
- 无法归类（unknown）：按暂时性处理（宁可多试一次，也不误杀可自愈的岗位）。

判定依据是 delivery_node / 投递引擎返回的错误文本；关键词分类为过渡方案，
L2 落地时由投递引擎改为返回结构化错误码，此处只消费错误码。
"""

# 持久性故障：重试不可能自愈，直接停止自动重试
PERSISTENT_PATTERNS = (
    "引擎执行失败",   # 投递引擎代码级失败（如「❌ 智联投递引擎执行失败」）
    "缺少",           # 物料缺失（PDF/图片/打招呼语）
    "数据不全",       # 投递要素缺失
    "已下架",         # 岗位链接失效/下架
    "未在自动投递",   # 平台白名单拦截
    "未知平台",       # 无法路由的 platform
    "未找到",         # 飞书记录未找到等实体缺失
    # 结构化错误标签（投递引擎错误文本前缀，见 zhilian_auto_delivery 等引擎）
    "[简历]",         # 简历失配/弹窗异常，投错简历风险 → 一律转人工
    "[物料]",         # 物料缺失或非法（下载失败/解析失败/打招呼语非法）
    "[下架]",         # 岗位失效页
    "[风控]",         # 验证码/次数上限拦截
    "[状态]",         # 按钮状态无法确认（页面改版/歧义按钮），需人工核实
)

# 暂时性故障：环境/会话类抖动，重试（或 L2 自愈动作）后大概率恢复
TRANSIENT_PATTERNS = (
    "tab",           # 标签页捕获失败（The specified tab was not found）
    "超时", "timeout",
    "登录", "会话", "session",
    "网络", "network",
    "浏览器", "browser",
    "页面", "崩溃",
    "[登录]",        # 结构化标签：登录态失效，重登后可自愈
    "[环境]",        # 结构化标签：浏览器/网络等环境异常
    "[微聊受阻]",    # 结构化标签：附件已投递但打招呼未送达，支持单独一键补发
    "[微聊]",
    "微聊受阻",
    "打招呼",
)

# 暂时性故障连续失败达该次数后停止自动重试（人工重试不受此限）
MAX_AUTO_RETRIES = 2

# 51job 附件上传日配额耗尽（720721）的错误标记子串：持久性只在当日成立，配额随日期重置，
# 登记于往日的此类失败要恢复自动发射（见 is_stale_quota_failure / should_skip_auto_delivery）
DAILY_UPLOAD_QUOTA_MARKER = "今日上传次数已达上限"


def is_stale_quota_failure(failure: dict) -> bool:
    """失败条目是否为「往日登记的 51job 日配额耗尽」——配额已随日期重置，岗位应恢复自动发射。

    failed_at 缺失（历史条目）时不豁免，保守留人工处置。
    """
    from datetime import date

    entry = failure or {}
    if DAILY_UPLOAD_QUOTA_MARKER not in str(entry.get("error") or ""):
        return False
    failed_day = str(entry.get("failed_at") or "")[:10]
    if not failed_day:
        return False
    return failed_day < date.today().isoformat()


def classify_delivery_failure(error: str) -> str:
    """按错误文本归类失败：返回 'persistent' / 'transient' / 'unknown'。

    持久性优先判定：一条错误同时命中两类关键词时按持久性处理（宁可停下等人工，不空转）。
    例外：微聊受阻（附件已投但打招呼未送达）属于明确可单独重试的暂时性故障。
    """
    text = str(error or "").lower()
    if any(k in text for k in ("[微聊受阻]", "[微聊]", "微聊受阻", "[附件未送达]", "附件未送达")):
        return "transient"
    for p in PERSISTENT_PATTERNS:
        if p in text:
            return "persistent"
    for p in TRANSIENT_PATTERNS:
        if p in text:
            return "transient"
    return "unknown"


def should_skip_auto_delivery(failure: dict) -> tuple:
    """波次发射前分诊：该岗位是否应跳过自动发射。

    Args:
        failure: run_snapshot.delivery_failures 里的登记条目（含 error / failure_count）。

    Returns:
        (是否跳过, 跳过原因说明)。False 时原因恒为空串。
    """
    error = str((failure or {}).get("error") or "")
    kind = classify_delivery_failure(error)
    if kind == "persistent":
        # 51job 日配额耗尽是「当日持久、隔日自愈」：往日登记的条目跨天即恢复发射，
        # 且在此提前返回，不落入下方 failure_count 重试上限门禁
        if is_stale_quota_failure(failure):
            return False, ""
        return True, f"持久性故障（{error[:60]}），重试无法自愈，已停止自动发射待人工处置"
    count = int((failure or {}).get("failure_count") or 1)
    if count >= MAX_AUTO_RETRIES:
        return True, f"暂时性故障已连续失败 {count} 次，停止自动发射待人工处置"
    return False, ""
