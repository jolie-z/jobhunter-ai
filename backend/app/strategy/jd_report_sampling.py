"""JD 画像岗位池取样（2026-10-11 从 jd_report_service 拆出，守单文件 500 行红线）。

职责：飞书岗位表分页拉取（含轻量计数）、8 维代理排序、公司+岗位名去重、
三阶段选样（成熟精选/成长全取/冷启动 B 补位）、样本文本组装。
飞书通信只依赖调用方传入的 token（httpx），同步读/migration 留在 jd_report_service。

排序代理说明：飞书岗位表没有单一数值总分字段（总分只存在于 SSE/日志），
8 维分数各占一字段（1-5 分，真源 ai_agents/ai_evaluator.py 初评 update_data），
按 8 维求和降序是确定性可复现的近似 ai_score 排序。
新鲜度用「抓取时间」字段（app/jobs/import_service.py 写入、snapshot_service 读取的既存字段），
不用记录 last_modified_time（任何字段编辑都会动它，语义不符）。
"""

import asyncio
import logging
from datetime import datetime, timedelta

import httpx

from app.core.config import settings

logger = logging.getLogger("strategy_jd_report")

CONTENT_TYPE_JSON = "application/json"

# 8 维评分字段（与 ai_evaluator.py 初评 update_data 键一字不差；改动需两处同步）
RANK_DIM_FIELDS = (
    "核心-角色匹配", "核心-技能重合",
    "高权-职级资历", "高权-薪资契合", "高权-面试概率",
    "中权-公司阶段", "中权-赛道前景", "中权-成长空间",
)
FIELD_RATING = "综合评级 (A-F)"
FIELD_NAME = "岗位名称"
FIELD_DETAIL = "岗位详情"
FIELD_COMPANY = "公司名称"
FIELD_CRAWL_TIME = "抓取时间"

# 单次飞书 search 封顶：A 池通常 < 数百，500 足够；防异常大表拖爆内存
_MAX_RECORDS = 500
# 拉取失败重试次数（含首次）
_SEARCH_ATTEMPTS = 3
# 单条 JD 截断（20 条 ≈ 8 万字符输入，画像生成要求模型上下文 ≥128k，见 prompts 模块 docstring）
PER_JD_CHARS = 4000


def _feishu_jobs_search_url() -> str:
    return (
        f"https://open.feishu.cn/open-apis/bitable/v1/apps/{settings.FEISHU_APP_TOKEN}"
        f"/tables/{settings.FEISHU_TABLE_ID_JOBS}/records/search"
    )


async def search_job_records(token: str, grade: str, field_names: list[str]) -> tuple[list[dict], int]:
    """按综合评级分页拉取岗位记录（grade 传 "A"/"B"），返回 (items, total)。

    total 取响应 data.total（该评级总数，含未拉全部分页），generate 直接用作
    total_a_in_pool，省一次轻量计数请求；失败重试共 _SEARCH_ATTEMPTS 次。
    """
    url = _feishu_jobs_search_url()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": CONTENT_TYPE_JSON}
    payload = {
        "filter": {
            "conjunction": "and",
            "conditions": [{"field_name": FIELD_RATING, "operator": "is", "value": [grade]}],
        },
        "field_names": field_names,
        "page_size": 100,
    }
    last_err: Exception | None = None
    for attempt in range(1, _SEARCH_ATTEMPTS + 1):
        try:
            items: list[dict] = []
            total = 0
            page_token = ""
            async with httpx.AsyncClient() as client:
                while True:
                    body = dict(payload)
                    if page_token:
                        body["page_token"] = page_token
                    resp = await client.post(url, headers=headers, json=body, timeout=15)
                    resp.raise_for_status()  # 非 JSON 错误页（HTML 网关 5xx）先暴露 HTTP 状态码
                    data = resp.json()
                    if data.get("code") != 0:
                        raise RuntimeError(f"飞书返回错误: {data.get('msg')}")
                    data_part = data.get("data") or {}
                    total = int(data_part.get("total") or 0) or total
                    items.extend(data_part.get("items") or [])
                    if not data_part.get("has_more") or len(items) >= _MAX_RECORDS:
                        break
                    page_token = data_part.get("page_token") or ""
            return items[:_MAX_RECORDS], total
        except Exception as e:
            last_err = e
            logger.warning(f"[jd_report_sampling] 拉取 {grade} 级岗位第 {attempt}/{_SEARCH_ATTEMPTS} 次失败: {e}")
            if attempt < _SEARCH_ATTEMPTS:
                await asyncio.sleep(attempt)  # 1s / 2s
    raise ValueError(f"无法读取岗位评级数据（飞书岗位表查询 {grade} 级连续 {_SEARCH_ATTEMPTS} 次失败）: {last_err}")


def _field_int(val) -> int:
    try:
        return int(float(val or 0))  # float 中转：兼容 "4.0" 等浮点字符串
    except (TypeError, ValueError):
        return 0


def dim_sum(fields: dict) -> int:
    """8 维求和：ai_score 的确定性代理（各维缺省/非数值按 0）。"""
    return sum(_field_int(fields.get(f)) for f in RANK_DIM_FIELDS)


def parse_crawl_time(fields: dict) -> datetime | None:
    raw = str(fields.get(FIELD_CRAWL_TIME) or "").strip()
    if not raw:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


# 新鲜度三档位（_rank_key 排序键，小者优先）
TIER_FRESH = 0    # 抓取时间在窗口内
TIER_STALE = 1    # 有时间戳但在窗口外
TIER_UNKNOWN = 2  # 无/无法解析抓取时间（垫底）


def _rank_key(crawl: datetime | None, recency_days: int, now: datetime) -> tuple:
    """三档位：新鲜 > 陈旧 > 未知（垫底），其次 8 维求和降序。

    未知时间垫底：新鲜度排序的意义在「画像跟市场走」，无法判定年龄的样本
    不应挤掉任何已知年龄的样本。
    """
    if crawl is None:
        return (TIER_UNKNOWN,)
    return (TIER_FRESH if crawl >= now - timedelta(days=recency_days) else TIER_STALE,)


def _job_key(fields: dict) -> tuple[str, str]:
    """去重键：(公司名称, 岗位名称) 归一化二元组。"""
    return (
        extract_text(fields.get(FIELD_COMPANY)).strip(),
        extract_text(fields.get(FIELD_NAME)).strip(),
    )


def extract_text(field_val) -> str:
    """飞书字段值解包（文本段 list / 标量 / None → str）。"""
    if not field_val:
        return ""
    if isinstance(field_val, list):
        return "".join(
            str(item.get("text", "")) if isinstance(item, dict) else str(item) for item in field_val
        )
    return str(field_val)


def _dedup_rank(items: list[dict], recency_days: int, now: datetime,
                exclude_keys: set[tuple[str, str]] | None = None) -> list[dict]:
    """排序（三档新鲜度 → 8 维求和降序）后按 (公司名称, 岗位名称) 去重取 1。

    去重目标：同质化 JD 会把「按频率提炼公约数」带偏成单一岗位类型的需求。
    排序先行保证去重保留的是同组中分数最高/最新鲜的一条。
    exclude_keys：跨池去重（B 池补位时排除 A 池已选键，防同岗位 A/B 双份入样）。
    """

    def _sort_key(item: dict) -> tuple:
        fields = item.get("fields") or {}
        crawl = parse_crawl_time(fields)
        return (*_rank_key(crawl, recency_days, now), -dim_sum(fields))

    ranked = sorted(items, key=_sort_key)
    seen: set[tuple[str, str]] = set(exclude_keys or set())
    out: list[dict] = []
    for item in ranked:
        key = _job_key(item.get("fields") or {})
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


async def select_samples(
    a_items: list[dict],
    total_a_in_pool: int,
    *,
    max_jobs: int,
    recency_days: int,
    now: datetime | None = None,
    b_items: list[dict] | None = None,
    b_fetch=None,
) -> dict:
    """两级选样（用户 2026-10-12 拍板，取代三阶段）：

    - mature (A ≥ max_jobs)：纯 A 精选 top max_jobs（窗口+分数），不拉 B 池
    - mixed  (A < max_jobs)：A 全取 + B 补位至 max_jobs（A=6 也补；A=0 时全 B）

    B 池按需获取：b_items 直传（测试用）；否则调 b_fetch（生产懒拉取，mature 不发
    这次请求）。返回 {"a_selected","b_selected","stage","total_a_in_pool"}；
    样本全空时两列表均为空，由调用方决定报错文案。
    """
    now = now or datetime.now()
    a_ranked = _dedup_rank(a_items, recency_days, now)

    if len(a_ranked) >= max_jobs:
        return {
            "a_selected": a_ranked[:max_jobs], "b_selected": [],
            "stage": "mature", "total_a_in_pool": total_a_in_pool,
        }
    if b_items is None:
        b_items = await b_fetch() if b_fetch else []
    # 跨池去重：B 池排除 A 池已选键（同公司同名岗位 A/B 评级并存时防双份入样）
    a_keys = {_job_key(it.get("fields") or {}) for it in a_ranked}
    b_ranked = _dedup_rank(b_items, recency_days, now, exclude_keys=a_keys)
    fill = max_jobs - len(a_ranked)
    return {
        "a_selected": a_ranked, "b_selected": b_ranked[:fill],
        "stage": "mixed", "total_a_in_pool": total_a_in_pool,
    }


def _iter_sample_items(selection: dict):
    """样本扁平化（A 先 B 后）：产出 (全局编号 idx, grade, fields, item)，编号 1 起连续。

    build_sample_text 与 build_sample_jobs 共用，保证两处编号与提取逻辑单点收口。
    """
    idx = 0
    for grade_label, items in (("A级岗位", selection["a_selected"]), ("B级岗位", selection["b_selected"])):
        for item in items:
            idx += 1
            yield idx, grade_label[:1], item.get("fields") or {}, item


def build_sample_text(selection: dict) -> str:
    """组装喂给 LLM 的大文本：层级显式标注 + 全局连续编号 + 公司名 + 单条 JD 截断。

    标题模板：A级 `【A级岗位 N：公司·岗位名】` / B级 `【B级岗位 N：公司·岗位名】`——
    N 全局连续自增（1..20，A 先 B 后），与 meta.sample_jobs.idx 精确同序
    （来源标记〔来源:N〕据此映射回岗位）；公司缺失退化为岗位名。
    """
    parts: list[str] = []
    for idx, grade, fields, _ in _iter_sample_items(selection):
        company = extract_text(fields.get(FIELD_COMPANY)).strip()
        title = extract_text(fields.get(FIELD_NAME)) or "未命名岗位"
        heading = f"{company}·{title}" if company else title
        jd = extract_text(fields.get(FIELD_DETAIL))
        parts.append(f"【{grade}级岗位 {idx}：{heading}】\n{jd[:PER_JD_CHARS]}\n")
    return "\n".join(parts)


def build_sample_jobs(selection: dict) -> list[dict]:
    """来源映射（写进 meta.sample_jobs，前端 HoverCard 据此渲染可点击岗位链接）。

    idx 与 build_sample_text 的全局编号同序（A 先 B 后，1 起）。
    """
    out: list[dict] = []
    for idx, grade, fields, item in _iter_sample_items(selection):
        out.append({
            "idx": idx,
            "grade": grade,
            "company": extract_text(fields.get(FIELD_COMPANY)).strip(),
            "title": extract_text(fields.get(FIELD_NAME)).strip() or "未命名岗位",
            "record_id": item.get("record_id") or "",
        })
    return out


def sample_field_names() -> list[str]:
    """取样拉取的字段清单（含排序/去重/新鲜度所需）。"""
    return [FIELD_NAME, FIELD_DETAIL, FIELD_COMPANY, FIELD_CRAWL_TIME, *RANK_DIM_FIELDS]
