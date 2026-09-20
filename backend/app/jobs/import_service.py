import logging
import os
import re
import sqlite3
import sys
import time
from datetime import datetime
from typing import Any

from app.core.cache import JobCache
from app.core.config import PROJECT_ROOT, settings
from app.core.feishu_client import feishu_client
from app.core.feishu_utils import extract_feishu_text
from app.jobs.import_parser import (
    _meaningful,
    normalize_job_url,
    parse_job_from_sources,
)
from app.session.registry import canonicalize_platform_name

logger = logging.getLogger(__name__)


# =========================================================================
# 🌟 极速录入共享管线：parse（分流解析）→ assess（质量评估）→ dedup（查重）→ confirm（落库）
# Web 确认页在 parse 与 confirm 之间插入人工补全；聊天/ChatOps 直连两步走。
# =========================================================================

class DuplicateJobError(Exception):
    """查重命中：携带已有记录摘要（record_id/公司名称/岗位名称/跟进状态），调用方决定警示话术。"""
    def __init__(self, existing: dict[str, Any]):
        self.existing = existing
        super().__init__(f"疑似重复岗位：{existing.get('公司名称', '')} - {existing.get('岗位名称', '')}")


class InvalidJobFieldsError(Exception):
    """P0 字段硬缺失（公司名称/岗位名称/岗位详情为占位值），不允许建档，弹回补料。"""
    def __init__(self, missing: list[str]):
        self.missing = missing
        super().__init__(f"必须提供的字段缺失: {', '.join(missing)}")


# 落库白名单：与飞书岗位总表字段一一对应，防止表单/LLM 混入未知键导致 create_record 报 FieldNameNotFound
_IMPORT_WRITE_KEYS = (
    "公司名称", "岗位名称", "城市", "工作地址", "公司规模", "所属行业",
    "薪资", "经验要求", "学历要求", "岗位详情", "招聘平台", "发布日期", "岗位链接",
)


def assess_parse_quality(fields: dict[str, Any]) -> dict[str, Any]:
    """解析质量评估：硬缺失（阻断建档，Web 确认页标红弹回）/ 软缺失（评级区分度受损）/ 链接缺失。"""
    hard_missing = [key for key in ("公司名称", "岗位名称", "岗位详情") if not _meaningful(fields.get(key))]
    soft_missing = [key for key in ("薪资", "城市", "经验要求", "学历要求") if not _meaningful(fields.get(key))]
    return {
        "hard_missing": hard_missing,
        "soft_missing": soft_missing,
        "link_missing": not _meaningful(fields.get("岗位链接")),
    }


def _normalize_dup_key(value: Any) -> str:
    """查重比较键：去空白、转小写、剥掉猎头标识前缀（[猎头] XX人力 与 XX人力 视为同一来源）。"""
    raw = re.sub(r'\s+', '', str(value if value is not None else ''))
    raw = re.sub(r'^[\[（(【]?\s*猎头\s*[\]）)】]?[:：]?', '', raw)
    return raw.lower()


def _normalize_dup_link(value: Any) -> str:
    raw = str(value if value is not None else '').strip()
    raw = normalize_job_url(raw)
    return raw.lower().rstrip('/')


async def find_duplicate_job(fields: dict[str, Any]) -> dict[str, Any] | None:
    """极速录入查重（警示级，零 token）：已有记录与本次录入「归一后公司+岗位相等」或「岗位链接相等」即命中。

    优先在本地 JobCache（内存/快照）比对，毫秒级响应且零飞书 API 消耗；
    若缓存未命中则降级请求飞书 Bitable records/search 检索。检索失败时放行（fail-open）。
    """
    new_company = _normalize_dup_key(fields.get("公司名称"))
    new_title = _normalize_dup_key(fields.get("岗位名称"))
    if not new_company or not new_title:
        return None
    new_link = _normalize_dup_link(fields.get("岗位链接"))

    # 1. 优先查本地 JobCache
    cached_jobs = JobCache.get_stale()
    if cached_jobs:
        for job in cached_jobs:
            c_name = _normalize_dup_key(job.get("company_name"))
            j_title = _normalize_dup_key(job.get("job_name"))
            j_link = _normalize_dup_link(job.get("job_link"))
            rid = str(job.get("record_id") or "")
            if new_link and j_link and j_link == new_link:
                return {
                    "record_id": rid,
                    "公司名称": job.get("company_name") or "",
                    "岗位名称": job.get("job_name") or "",
                    "跟进状态": job.get("follow_status") or "",
                    "review_url": build_job_review_url(rid),
                }
            if new_company == c_name and new_title == j_title:
                return {
                    "record_id": rid,
                    "公司名称": job.get("company_name") or "",
                    "岗位名称": job.get("job_name") or "",
                    "跟进状态": job.get("follow_status") or "",
                    "review_url": build_job_review_url(rid),
                }

    # 2. 缓存未命中时降级走飞书 API
    try:
        items = await feishu_client.search_bitable_records(
            settings.FEISHU_TABLE_ID_JOBS,
            field_names=["公司名称", "岗位名称", "岗位链接", "跟进状态"],
        )
        for item in items:
            f = item.get("fields", {})
            if new_link:
                dup_link = _normalize_dup_link(extract_feishu_text(f.get("岗位链接", "")))
                if dup_link and dup_link == new_link:
                    return _dup_summary(item, f)
            if new_company == _normalize_dup_key(f.get("公司名称")) and new_title == _normalize_dup_key(f.get("岗位名称")):
                return _dup_summary(item, f)
    except Exception as e:
        logger.warning(f"⚠️ [极速录入查重] 飞书检索失败，默认放行: {e}")
        return None

    return None


def _dup_summary(item: dict[str, Any], f: dict[str, Any]) -> dict[str, Any]:
    record_id = item.get("record_id", "")
    return {
        "record_id": record_id,
        "公司名称": extract_feishu_text(f.get("公司名称", "")),
        "岗位名称": extract_feishu_text(f.get("岗位名称", "")),
        "跟进状态": extract_feishu_text(f.get("跟进状态", "")),
        "review_url": build_job_review_url(record_id),
    }


def _build_write_fields(fields: dict[str, Any]) -> dict[str, Any]:
    """落库前规整：白名单键 + 平台归一 + 链接仅 http 才写入（避免 URLFieldConvFail）+ 固定新线索/抓取时间。"""
    write: dict[str, Any] = {}
    for key in _IMPORT_WRITE_KEYS:
        val = str(fields.get(key) if fields.get(key) is not None else "").strip()
        if val:
            write[key] = val

    write["招聘平台"] = canonicalize_platform_name(write.get("招聘平台"))
    url = write.pop("岗位链接", "")
    if url.startswith("http"):
        write["岗位链接"] = {"link": normalize_job_url(url), "text": "点击查看"}
    write.setdefault("跟进状态", "新线索")
    write["抓取时间"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return write


def _sync_to_raw_jobs(fields: dict[str, Any], record_id: str) -> None:
    """极速录入岗位落库 SQLite raw_jobs（补齐第一层采集指纹与第三层去重闸门的母本池）。"""
    if not record_id:
        return
    svc = sys.modules.get("app.jobs.service")
    proj_root = getattr(svc, "PROJECT_ROOT", PROJECT_ROOT) if svc else PROJECT_ROOT
    db_path = os.path.join(proj_root, "data", "job_hunter.db")
    if not os.path.exists(db_path):
        logger.warning(f"⚠️ [极速录入] 未找到 SQLite 数据库: {db_path}")
        return

    raw_url = str(fields.get("岗位链接") or "").strip()
    if isinstance(fields.get("岗位链接"), dict):
        raw_url = str(fields.get("岗位链接", {}).get("link") or "").strip()
    raw_url = normalize_job_url(raw_url)
    job_link = raw_url if (raw_url and raw_url.startswith("http")) else f"feishu://{record_id}"

    sql = """
    INSERT OR REPLACE INTO raw_jobs (
        job_link, job_title, company_name, city, jd_text, salary,
        work_address, company_size, industry, education_req, experience_req,
        publish_date, platform, crawl_time, process_status, is_synced, feishu_record_id
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '已同步', 1, ?)
    """
    args = (
        job_link,
        fields.get("岗位名称", "-"),
        fields.get("公司名称", "-"),
        fields.get("城市", "-"),
        fields.get("岗位详情", "-"),
        fields.get("薪资", "-"),
        fields.get("工作地址", "-"),
        fields.get("公司规模", "-"),
        fields.get("所属行业", "-"),
        fields.get("学历要求", "-"),
        fields.get("经验要求", "-"),
        fields.get("发布日期", "-"),
        fields.get("招聘平台", "其他"),
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        record_id,
    )

    max_retries = 3
    for attempt in range(max_retries):
        try:
            with sqlite3.connect(db_path, timeout=10.0) as conn:
                conn.execute("PRAGMA journal_mode=WAL;")
                conn.execute("""
                CREATE TABLE IF NOT EXISTS raw_jobs (
                    job_link TEXT PRIMARY KEY,
                    job_title TEXT,
                    company_name TEXT,
                    city TEXT,
                    jd_text TEXT,
                    salary TEXT,
                    work_address TEXT,
                    company_size TEXT,
                    industry TEXT,
                    education_req TEXT,
                    experience_req TEXT,
                    publish_date TEXT,
                    platform TEXT,
                    crawl_time TEXT,
                    process_status TEXT,
                    is_synced INTEGER DEFAULT 0,
                    feishu_record_id TEXT
                )
                """)
                conn.execute(sql, args)
                conn.commit()
            logger.info(f"✅ [SQLite] 极速录入同步母本池成功 (feishu_record_id={record_id})")
            return
        except sqlite3.OperationalError as e:
            if "locked" in str(e) and attempt < max_retries - 1:
                time.sleep(0.5)
                continue
            logger.warning(f"⚠️ [SQLite] 极速录入同步母本池锁定异常: {e}")
            break
        except Exception as e:
            logger.warning(f"⚠️ [SQLite] 极速录入同步母本池失败: {e}")
            break


def ensure_raw_jobs_indices(conn: sqlite3.Connection | None = None, db_path: str | None = None) -> None:
    """幂等创建 raw_jobs 表及相关表的核心二级索引，消除全表扫描与锁冲突隐患。"""
    ddls = [
        "CREATE INDEX IF NOT EXISTS idx_raw_jobs_status ON raw_jobs(process_status, is_synced)",
        "CREATE INDEX IF NOT EXISTS idx_raw_jobs_platform ON raw_jobs(platform, process_status)",
        "CREATE INDEX IF NOT EXISTS idx_raw_jobs_feishu_rid ON raw_jobs(feishu_record_id)",
        "CREATE INDEX IF NOT EXISTS idx_raw_jobs_company_title_city ON raw_jobs(company_name, job_title, city)",
    ]
    if conn is not None:
        for ddl in ddls:
            conn.execute(ddl)
        try:
            conn.execute("CREATE INDEX IF NOT EXISTS idx_xhs_raw_posts_clean_status ON xhs_raw_posts(clean_status)")
        except sqlite3.OperationalError:
            pass
        return

    path = db_path or os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "data", "job_hunter.db"
    )
    if not os.path.exists(path):
        return
    try:
        with sqlite3.connect(path, timeout=10.0) as local_conn:
            for ddl in ddls:
                local_conn.execute(ddl)
            try:
                local_conn.execute("CREATE INDEX IF NOT EXISTS idx_xhs_raw_posts_clean_status ON xhs_raw_posts(clean_status)")
            except sqlite3.OperationalError:
                pass
            local_conn.commit()
            logger.info("⚡ [SQLite] raw_jobs & xhs_raw_posts 二级索引已就绪 (status, platform, feishu_rid, company_title_city, xhs_clean_status)")
    except Exception as e:
        logger.warning(f"⚠️ [SQLite] 索引初始化失败: {e}")


def _extract_new_record_id(create_resp: dict[str, Any]) -> str:
    """从 create_record 的响应里取新记录 ID（供回执拼多维表格详情链接）。"""
    try:
        return (create_resp.get("data", {}).get("record", {}) or {}).get("record_id", "")
    except Exception:
        return ""


async def confirm_job_import(fields: dict[str, Any], force_duplicate: bool = False) -> dict[str, Any]:
    """极速录入落库（唯一写入口）：硬校验 → 查重（可 force 放行）→ 规整 → 写飞书 → 同步 SQLite raw_jobs → 打脏缓存。

    返回写入的完整字段（含 record_id）；硬缺失抛 InvalidJobFieldsError、查重命中抛 DuplicateJobError。
    """
    svc = sys.modules.get("app.jobs.service")
    assess_fn = getattr(svc, "assess_parse_quality", assess_parse_quality) if svc else assess_parse_quality
    find_dup_fn = getattr(svc, "find_duplicate_job", find_duplicate_job) if svc else find_duplicate_job

    quality = assess_fn(fields)
    if quality["hard_missing"]:
        raise InvalidJobFieldsError(quality["hard_missing"])

    if not force_duplicate:
        dup = await find_dup_fn(fields)
        if dup:
            raise DuplicateJobError(dup)

    write_fields = _build_write_fields(fields)
    logger.info(f">>> 确认落库: 公司={write_fields.get('公司名称')} | 岗位={write_fields.get('岗位名称')} | 平台={write_fields.get('招聘平台')}")
    create_resp = await feishu_client.create_record(
        table_id=settings.FEISHU_TABLE_ID_JOBS,
        fields=write_fields,
    )
    if not create_resp:
        raise ValueError("解析成功，但写入飞书时失败")
    record_id = _extract_new_record_id(create_resp)
    write_fields["record_id"] = record_id

    # 1. 同步写入 SQLite raw_jobs 充当后续爬虫采集查重与自动化评估闸门的母本池
    sync_fn = getattr(svc, "_sync_to_raw_jobs", _sync_to_raw_jobs) if svc else _sync_to_raw_jobs
    sync_fn(write_fields, record_id)

    # 2. 标记岗位缓存为脏，确保前端与各消费方立即感知最新数据
    JobCache.mark_dirty()

    return write_fields


async def import_job_from_text_service(raw_text: str) -> dict[str, Any]:
    """极速录入（文本）：解析 → 质量硬校验 → 查重 → 落库。聊天/ChatOps/Web 旧接口共用。"""
    logger.info("\n====== 📡 收到【极速录入】请求 ======")
    logger.info(f"--> 收到文本长度: {len(raw_text)} 字符")
    fields = await parse_job_from_sources(raw_text=raw_text)
    return await confirm_job_import(fields)


async def import_job_from_images_service(images_base64: list[str]) -> dict[str, Any]:
    """极速录入（多图）：解析 → 质量硬校验 → 查重 → 落库。聊天/Web 旧接口共用。"""
    logger.info(f"\n====== 📡 收到【极速多图录入】请求，共 {len(images_base64)} 张图片 ======")
    fields = await parse_job_from_sources(images_base64=images_base64)
    return await confirm_job_import(fields)


def build_job_review_url(record_id: str) -> str:
    """拼多维表格岗位详情复核链接（极速录入回执/聊天卡片共用口径）。"""
    record_id = str(record_id or "")
    app_token = settings.FEISHU_APP_TOKEN or ""
    table_id = settings.FEISHU_TABLE_ID_JOBS or ""
    if not (record_id and app_token and table_id):
        return ""
    return f"https://feishu.cn/base/{app_token}?table={table_id}&record={record_id}"


# 录入回执摘要展示的字段（岗位详情等大字段不进聊天回执）
_IMPORT_SUMMARY_FIELDS = (
    ("公司名称", "公司"),
    ("岗位名称", "岗位"),
    ("薪资", "薪资"),
    ("城市", "城市"),
    ("招聘平台", "平台"),
)


def format_job_import_summary(data: dict[str, Any]) -> str:
    """把极速录入解析出的岗位字段格式化成聊天框回执摘要（极速录入 API / ChatOps 工具 / 飞书图片录入共用）。"""
    lines = ["✅ 岗位已识别并录入飞书表格："]
    for key, label in _IMPORT_SUMMARY_FIELDS:
        val = str(data.get(key) or "").strip()
        if val and val not in ("未知", "-"):
            lines.append(f"• {label}：{val}")
    lines.append("• 跟进状态：新线索")
    review_url = build_job_review_url(str(data.get("record_id") or ""))
    if review_url:
        lines.append(f"👉 复核多维表格岗位详情：{review_url}")
    return "\n".join(lines)
