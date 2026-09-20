# app/services/feishu_jobs_fetcher.py
"""
飞书招聘岗位数据读取与底座缓存服务。
优先读取本地 JobCache 极速直出，未命中时加互斥锁直连飞书开放平台裁剪字段拉取，防并发惊群。
同时提供状态归一化判断与招聘渠道名清洗工具。
"""
import asyncio
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

# 飞书字段名常量
FIELD_STATUS = "跟进状态"
FIELD_PLATFORM = "招聘平台"
FIELD_GRADE = "综合评级 (A-F)"
FIELD_CRAWL_TIME = "抓取时间"

# 状态分类规则与归一化
INTERVIEW_KEYWORDS = ("一面", "二面", "三面", "终面", "面试")
OFFER_KEYWORDS = ("offer", "已获offer")
STATUS_NORMALIZE = {"已完成深度评估": "已深度初步评估"}
PENDING_STATUSES = ("新线索", "已完成初步评估", "已深度初步评估", "已完成深度评估", "简历人工复核", "疑似重复", "待投递")

# 缓存与锁
_feishu_cache: dict[str, Any] = {"data": None, "ts": 0}
_FEISHU_CACHE_TTL = 300
_feishu_lock = asyncio.Lock()

_FIELD_TO_NORMALIZED_KEY = {
    "跟进状态": "follow_status",
    "抓取时间": "fetch_time",
    "综合评级 (A-F)": "grade",
    "招聘平台": "platform",
}


def extract_field(record: dict[str, Any], name: str) -> str:
    """安全提取字段值，兼容本地 JobCache 归一化结构与飞书原生 fields 字典结构。"""
    if not record:
        return ""
    if "fields" in record and isinstance(record["fields"], dict):
        val = record["fields"].get(name)
    else:
        norm_key = _FIELD_TO_NORMALIZED_KEY.get(name, name)
        val = record.get(norm_key) if norm_key in record else record.get(name)

    if val is None:
        return ""
    if isinstance(val, str):
        return val
    if isinstance(val, list):
        return "".join(item.get("text", "") if isinstance(item, dict) else str(item) for item in val)
    if isinstance(val, dict):
        return val.get("text", str(val))
    return str(val)


def is_interview_status(status: str) -> bool:
    return any(kw in status for kw in INTERVIEW_KEYWORDS)


def is_offer_status(status: str) -> bool:
    return any(kw in (status or "").lower() for kw in OFFER_KEYWORDS)


def is_delivered_status(status: str) -> bool:
    return status == "已投递" or is_interview_status(status) or is_offer_status(status)


def normalize_platform_name(name: str) -> str:
    """规范化招聘平台名称，将大小写、别名及杂项脏数据归一化。"""
    if not name or str(name).strip() in ("", "未知", "unknown", "None", "-", "null", "其他"):
        return "其他平台"
    n = str(name).strip()
    n_lower = n.lower()
    if "boss" in n_lower or "直聘" in n:
        return "BOSS直聘"
    if "51" in n_lower or "前程" in n:
        return "51job"
    if "猎聘" in n or "liepin" in n_lower:
        return "猎聘"
    if "智联" in n or "zhilian" in n_lower or "zhaopin" in n_lower:
        return "智联招聘"
    if "红书" in n or "xhs" in n_lower or "小红书" in n:
        return "小红书"
    if "拉勾" in n or "lagou" in n_lower:
        return "拉勾招聘"
    return "其他平台"


async def fetch_feishu_jobs() -> list[dict[str, Any]]:
    """获取飞书岗位记录（优先读取本地 JobCache，0.02s 直出；降级直连飞书）"""
    global _feishu_cache
    now = time.time()
    if _feishu_cache["data"] is not None and (now - _feishu_cache["ts"]) < _FEISHU_CACHE_TTL:
        return _feishu_cache["data"]

    # 1. 优先命中本地 JobCache
    try:
        from app.core.cache import JobCache
        cached = JobCache.get() or JobCache.get_stale()
        if cached:
            logger.info(f"⚡ [feishu_jobs_fetcher] 命中本地 JobCache，直出 {len(cached)} 条岗位快照")
            _feishu_cache = {"data": cached, "ts": now}
            return cached
    except Exception as e:
        logger.warning(f"⚠️ [feishu_jobs_fetcher] JobCache 读取异常，降级直连飞书: {e}")

    # 2. 本地无缓存时，加互斥锁防并发惊群
    async with _feishu_lock:
        if _feishu_cache["data"] is not None and (now - _feishu_cache["ts"]) < _FEISHU_CACHE_TTL:
            return _feishu_cache["data"]
        try:
            from app.core.config import settings
            from app.core.feishu_client import feishu_client
            if not settings.FEISHU_APP_TOKEN or not settings.FEISHU_TABLE_ID_JOBS:
                logger.warning("⚠️ [feishu_jobs_fetcher] 未配置 FEISHU_APP_TOKEN 或 FEISHU_TABLE_ID_JOBS")
                return []
            logger.info(f"🌐 [feishu_jobs_fetcher] 本地无快照，向飞书拉取 table={settings.FEISHU_TABLE_ID_JOBS}...")
            records = await feishu_client.search_bitable_records(
                settings.FEISHU_TABLE_ID_JOBS,
                field_names=["跟进状态", "招聘平台", "综合评级 (A-F)", "抓取时间"]
            )
            logger.info(f"✅ [feishu_jobs_fetcher] 飞书精简字段拉取成功，获得 {len(records)} 条记录")
            _feishu_cache = {"data": records, "ts": now}
            return records
        except Exception as e:
            logger.error(f"❌ [feishu_jobs_fetcher] 飞书数据拉取失败: {e}")
            if _feishu_cache["data"] is not None:
                return _feishu_cache["data"]
            return []


def invalidate_feishu_cache() -> None:
    """清理飞书数据缓存状态"""
    global _feishu_cache
    _feishu_cache = {"data": None, "ts": 0}
