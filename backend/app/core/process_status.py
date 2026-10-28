"""raw_jobs.process_status 状态词表 —— 单一事实源。

背景（2026-10-09 双端撕裂事故）：淘汰词散落各处、各自写入互不对齐——飞书卡片归档写入
「已淘汰」后全库无任何读取方认识它，快照兜底把它画成「评估中」幽灵卡。本模块收敛全部
raw_jobs.process_status 取值，写入方与读取方一律从这里取词，禁止在业务代码里重新内联。

注意：飞书「跟进状态」字段是另一套词表（如「清洗淘汰」也会出现在跟进状态上），两者同名
不同列，不要混用本模块去校验飞书跟进状态（飞书侧终态见 app/core/feishu_utils.TERMINAL_FOLLOW_STATUSES）。
"""

# ---- 淘汰终态（新增淘汰类状态必须同步登记进 REJECTED_STATUSES）----
REJECT_RULE = "清洗淘汰" # 清洗流水线 Tier1 硬规则拦截
REJECT_AI = "ai清洗淘汰" # 清洗流水线 Tier2 AI 侦察兵拦截
REJECT_CONFIRMED = "已确认淘汰" # 人工确认归档（桌面端回收站与飞书卡片「确认淘汰」统一写这个词）
REJECT_ARCHIVED_LEGACY = "已淘汰" # [存量兼容] 2026-10-09 前飞书卡片归档写入的旧词——只允许读取兼容，禁止再写入

REJECTED_STATUSES = frozenset({REJECT_RULE, REJECT_AI, REJECT_CONFIRMED, REJECT_ARCHIVED_LEGACY})

# ---- 流转态 ----
STORED = "已存入数据" # 抓取入库，待清洗
CLEANING = "清洗中" # 清洗流水线处理中
PENDING_AI = "待AI初筛" # 待 AI 侦察兵排雷
PENDING_AI_LEGACY = "待AI清洗" # [存量兼容] 旧统计口径变体
SCORED = "已进行打分" # AI 打分完成（旧链路遗留中间态）
PUSH_PENDING = "待推送至飞书" # 每日同步的捞取条件（step2_sync_feishu）
PUSH_PENDING_LEGACY = "待推送飞书" # [存量兼容] 旧版缺「至」变体
SYNCED = "已同步" # 已推送飞书建档（此后流转真源=飞书跟进状态，raw 仅作数据源存档）
RECALL_PENDING_EVAL = "召回待初评" # 飞书卡片误杀召回后、复评完成前的门牌
READY_TO_DELIVER = "待投递" # 已过投递安检，等发射波次
ABANDONED = "已放弃" # 用户主动放弃

# 活跃中间态：出现在快照/看板上时应显示为「处理中」而非终态
ACTIVE_STATUSES = frozenset({STORED, CLEANING, PENDING_AI, PUSH_PENDING, PUSH_PENDING_LEGACY, SYNCED, RECALL_PENDING_EVAL, READY_TO_DELIVER})


def is_rejected(p_status: str) -> bool:
    """判断 process_status 是否为淘汰终态（含存量旧词）。"""
    return (p_status or "").strip() in REJECTED_STATUSES


def normalize_legacy(p_status: str) -> str:
    """把存量旧变体归一到现行词表（读取侧兼容用，不改写库）。"""
    mapping = {PUSH_PENDING_LEGACY: PUSH_PENDING}
    return mapping.get((p_status or "").strip(), (p_status or "").strip())
