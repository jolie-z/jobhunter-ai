import asyncio
import json
import logging
import os
import sqlite3
import sys
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any

import httpx
import requests
from fastapi import HTTPException

from app.core.config import settings
from app.core.feishu_client import feishu_client
from app.core.feishu_utils import get_tenant_access_token
from app.strategy.schemas import (
    ActiveStrategyResponse,
    DeleteStrategyRequest,
    PreferenceUpsertRequest,
    SaveConfigRequest,
    UpdateStrategyRequest,
)

logger = logging.getLogger("strategy_config_service")
logger.setLevel(logging.INFO)

# Q-M4-3：偏好类型白名单——前端下拉仅提供核心加分/职业愿景/自动化阈值三类，
# 服务端同口径拒绝任意字符串，防止脏 type 直接入库污染评估链路
PREFERENCE_TYPE_WHITELIST = {"核心加分", "职业愿景", "自动化阈值"}

CONTENT_TYPE_JSON = "application/json"
RESUME_SAVE_FIELD_WHITELIST = {"简历版本", "简历内容", "个人信息", "当前状态", "结构化数据"}


def _get_svc():
    return sys.modules.get("app.strategy.service")


def _safe_extract_text(field_val: Any) -> str:
    """内部辅助函数：安全提取纯文本"""
    if not field_val:
        return ""
    if isinstance(field_val, list):
        return "".join([str(item.get("text", "")) if isinstance(item, dict) else str(item) for item in field_val])
    return str(field_val)


def _safe_extract_avatar_url(field_val: Any) -> str:
    """提取飞书附件字段的图片临时URL"""
    if not field_val:
        return ""
    if isinstance(field_val, list) and len(field_val) > 0:
        first_item = field_val[0]
        if isinstance(first_item, dict):
            file_token = first_item.get("file_token")
            if file_token:
                return f"{settings.BACKEND_BASE_URL.rstrip('/')}/api/strategy/avatar/{file_token}"
    return ""


def _process_single_resume(r: dict) -> dict:
    fields = r.get("fields", {})
    personal_info = _safe_extract_text(fields.get("个人信息", ""))
    resume_content = _safe_extract_text(fields.get("简历内容", ""))

    full_content = resume_content
    if personal_info:
        full_content = f"{personal_info}\n\n{resume_content}".strip()

    structured_json_str = _safe_extract_text(fields.get("结构化数据", "{}"))
    try:
        structured_json = json.loads(structured_json_str) if structured_json_str else {}
    except json.JSONDecodeError:
        structured_json = {}

    return {
        "record_id": r.get("record_id"),
        "version_name": _safe_extract_text(fields.get("简历版本", "")),
        "content": full_content,
        "status": _safe_extract_text(fields.get("当前状态", "停用")),
        "avatar_url": _safe_extract_avatar_url(fields.get("照片")),
        "structured_json": structured_json,
    }


def _resume_status_is_active(status: Any) -> bool:
    """兼容「启用」的三种飞书字段形态：单选字符串 / 字符串列表 / 富文本 [{text: 启用}] 列表。"""
    if status == "启用":
        return True
    if isinstance(status, list):
        for item in status:
            if item == "启用" or (isinstance(item, dict) and item.get("text") == "启用"):
                return True
    return False


async def _ensure_single_resume_active(
    resumes: list[dict[str, Any]] | None = None,
    only_record_id: str | None = None,
) -> None:
    """单份简历自动生效（新手指引第二步硬前提：库里必须有「已生效」简历）。

    仅当简历库恰好一份简历且当前没有任何「启用」记录时，把它排他性启用；
    多份简历仍由用户显式点「设为生效」，绝不擅自替用户挑底稿。
    resumes 不传时自行拉取一次（用于保存后/体检接口的自愈入口）；
    传入时若命中自愈，会把该记录的「当前状态」就地改写为启用，调用方随后
    process 出的列表即为生效后的最新状态，同一次响应无需二次刷新。
    only_record_id：保存链路传入刚创建的 record_id；若拉到的全量列表里唯一记录
    与之不符（读后写延迟下的陈旧视图），宁可跳过自愈也不把别的简历错设为生效。
    自愈语义：幂等，任何失败（含自行拉取失败）只告警不抛，绝不影响已成功的
    创建/读取主流程。
    """
    try:
        if resumes is None:
            resumes = await feishu_client.fetch_bitable_records(settings.FEISHU_TABLE_ID_RESUMES)
        if len(resumes) != 1:
            return
        record = resumes[0] or {}
        record_id = record.get("record_id")
        if only_record_id and record_id != only_record_id:
            logger.info(f"[简历库] 自愈目标不匹配（陈旧视图），跳过 expected={only_record_id} got={record_id}")
            return
        if not record_id or _resume_status_is_active((record.get("fields") or {}).get("当前状态")):
            # 已有生效简历：状态未变，这里不做失效（读路径不该每次清缓存）；
            # setup-status 自愈钩子在调用本函数后会自行失效再重判
            return
        logger.info(f"[简历库] 仅一份简历且未生效，自动设为生效 record={record_id}")
        await asyncio.to_thread(activate_target_resume, record_id)
        # 就地改写：让本次响应直接呈现生效状态（读取自愈路径免二次刷新）
        fields = record.get("fields") or {}
        record["fields"] = fields
        fields["当前状态"] = "启用"
        _invalidate_active_resume_meta_cache()
    except Exception as e:
        logger.warning(f"[简历库] 单份简历自动生效失败（忽略，不阻塞主流程）: {e}")


async def get_all_strategy_configs() -> dict[str, list[dict[str, Any]]]:
    """拉取简历配置并进行清洗"""
    resumes = await feishu_client.fetch_bitable_records(settings.FEISHU_TABLE_ID_RESUMES)
    # 单份简历自动生效自愈：新用户上传第一份简历保存后无需手动点「设为生效」。
    # 先自愈再清洗：命中时 resumes[0] 已被就地改为启用，同一次响应即为最新状态
    await _ensure_single_resume_active(resumes)
    resume_list = [_process_single_resume(r) for r in resumes]
    return {"resumes": resume_list}


def activate_target_resume(target_record_id: str) -> None:
    """排他性启用简历。

    顺序很关键：先验证目标存在 → 先启用目标 → 再停用其它。
    旧实现先把其它简历全部停用再启用目标，一旦目标不存在/启用失败，
    全库会落入「0 生效简历」的清零态，下游改写/投递会静默拿到空简历。
    现在最坏情况只是短暂双生效，绝不会清零。
    """
    svc = _get_svc()
    token_getter = getattr(svc, "get_tenant_access_token", get_tenant_access_token) if svc else get_tenant_access_token
    token = token_getter()
    req = getattr(svc, "requests", requests) if svc else requests

    headers = {"Authorization": f"Bearer {token}", "Content-Type": CONTENT_TYPE_JSON}
    base_url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{settings.FEISHU_APP_TOKEN}/tables/{settings.FEISHU_TABLE_ID_RESUMES}/records"

    # ① 目标必须真实存在
    try:
        resp = req.get(f"{base_url}/{target_record_id}", headers=headers, timeout=15)
        resp.raise_for_status()
        body = resp.json()
    except Exception as e:
        logger.exception(f"Feishu fetch target resume failed: {e}")
        raise
    if body.get("code") != 0 or not (body.get("data") or {}).get("record"):
        raise ValueError("目标简历不存在或已被删除，无法设为生效")

    # ② 先启用目标：失败立即抛错，此时其它简历未被改动
    try:
        resp_a = req.put(
            f"{base_url}/{target_record_id}",
            headers=headers,
            json={"fields": {"当前状态": "启用"}},
            timeout=15,
        )
        resp_a.raise_for_status()
    except Exception as e:
        logger.exception(f"Feishu activate failed: {e}")
        raise
    if resp_a.json().get("code") != 0:
        raise ValueError(f"启用目标简历失败: {resp_a.json().get('msg')}")

    # ③ 再停用其它仍在生效的简历（逐条校验结果，失败仅告警）
    try:
        resp = req.post(
            f"{base_url}/search",
            headers=headers,
            json={
                "filter": {
                    "conjunction": "and",
                    "conditions": [{"field_name": "当前状态", "operator": "is", "value": ["启用"]}],
                }
            },
            timeout=15,
        )
        resp.raise_for_status()
        if resp.json().get("code") != 0:
            raise ValueError(f"Feishu search returned error: {resp.json().get('msg')}")
    except Exception as e:
        logger.exception(f"Feishu search failed: {e}")
        raise

    for r in (resp.json().get("data") or {}).get("items") or []:
        rid = r.get("record_id")
        if not rid or rid == target_record_id:
            continue
        de = req.put(
            f"{base_url}/{rid}",
            headers=headers,
            json={"fields": {"当前状态": "停用"}},
            timeout=15,
        )
        if de.status_code != 200 or de.json().get("code") != 0:
            logger.error(f"停用旧生效简历失败 record={rid}: {de.text[:200]}")

    _invalidate_active_resume_meta_cache()


def _invalidate_active_resume_meta_cache() -> None:
    """失效指挥中心 60s 活跃简历缓存的统一入口。

    手动「设为生效」与自动生效共用此咽喉点，保证新手指引 setup-status 第二步、
    config_status 改写判定等消费方下一次读取立刻看到最新生效简历，而非等 60s TTL。
    懒加载 + 告警兜底：pipeline 路由模块不可用时绝不影响切换主流程，但留下日志可查。
    """
    try:
        from app.pipeline.routes.feishu_status_router import (
            invalidate_active_resume_meta_cache,
        )
        invalidate_active_resume_meta_cache()
    except Exception as e:
        logger.warning(f"[简历库] 活跃简历缓存失效失败（不阻塞主流程）: {e}")


def get_db_path() -> str:
    backend_dir = Path(__file__).resolve().parent.parent.parent
    return str(backend_dir / "data" / "job_hunter.db")


def _fetch_active_strategy_sync() -> ActiveStrategyResponse | None:
    db_path = get_db_path()
    if not os.path.exists(db_path):
        raise HTTPException(status_code=500, detail=f"Database file not found at {db_path}")
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT min_salary_k, max_salary_k, experience_years_max, exclude_education, allowed_cities, safe_phrases, keyword_rules, ai_scout_rules "
            "FROM job_strategies WHERE is_active = 1 LIMIT 1"
        )
        row = cursor.fetchone()
        if not row:
            return None

        ai_rules = "[]"
        if len(row) > 7 and row[7]:
            ai_rules = row[7]

        return ActiveStrategyResponse(
            min_salary_k=row[0],
            max_salary_k=row[1],
            experience_years_max=row[2],
            exclude_education=json.loads(row[3] or "[]"),
            allowed_cities=json.loads(row[4] or "[]"),
            safe_phrases=json.loads(row[5] or "[]"),
            keyword_rules=json.loads(row[6] or "[]"),
            ai_scout_rules=json.loads(ai_rules),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


async def get_active_strategy() -> ActiveStrategyResponse:
    result = await asyncio.to_thread(_fetch_active_strategy_sync)
    if not result:
        raise HTTPException(status_code=404, detail="No active strategy found")
    return result


def _update_active_strategy_sync(data: UpdateStrategyRequest) -> None:
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE job_strategies
            SET min_salary_k = ?, max_salary_k = ?, experience_years_max = ?,
                exclude_education = ?, allowed_cities = ?, safe_phrases = ?, keyword_rules = ?, ai_scout_rules = ?, updated_at = CURRENT_TIMESTAMP
            WHERE is_active = 1
        """,
            (
                data.min_salary_k,
                data.max_salary_k,
                data.experience_years_max,
                json.dumps(data.exclude_education, ensure_ascii=False),
                json.dumps(data.allowed_cities, ensure_ascii=False),
                json.dumps(data.safe_phrases, ensure_ascii=False),
                json.dumps(data.keyword_rules, ensure_ascii=False),
                json.dumps(data.ai_scout_rules, ensure_ascii=False),
            ),
        )
        conn.commit()
    finally:
        conn.close()


async def update_active_strategy_in_db(data: UpdateStrategyRequest) -> None:
    await asyncio.to_thread(_update_active_strategy_sync, data)


async def get_active_resume_text_async() -> str:
    """获取当前启用的简历全文，供沙盒测试组装 Prompt 使用"""
    token = await feishu_client.get_tenant_access_token()
    search_url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{settings.FEISHU_APP_TOKEN}/tables/{settings.FEISHU_TABLE_ID_RESUMES}/records/search"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": CONTENT_TYPE_JSON}
    payload = {
        "filter": {
            "conjunction": "and",
            "conditions": [{"field_name": "当前状态", "operator": "is", "value": ["启用"]}],
        }
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(search_url, headers=headers, json=payload, timeout=15)
        resp.raise_for_status()
        resp_data = resp.json()
        if resp_data.get("code") != 0:
            logger.error(f"Feishu search active resume failed: {resp_data.get('msg')}")
            return ""
        items = resp_data.get("data", {}).get("items", [])
        if not items:
            return ""

        raw_text = _safe_extract_text(items[0].get("fields", {}).get("结构化数据", ""))
        try:
            data_dict = json.loads(raw_text)
            data_dict.pop("personalInfo", None)
            return json.dumps(data_dict, ensure_ascii=False)
        except json.JSONDecodeError:
            return raw_text


async def save_strategy_config_service(payload: SaveConfigRequest) -> str:
    token = await feishu_client.get_tenant_access_token()
    table_id = settings.FEISHU_TABLE_ID_RESUMES
    headers = {"Authorization": f"Bearer {token}", "Content-Type": CONTENT_TYPE_JSON}

    fields = payload.fields
    if payload.table_type == "resume":
        fields = {k: v for k, v in fields.items() if k in RESUME_SAVE_FIELD_WHITELIST}
        if not fields:
            raise ValueError("没有可保存的简历字段（字段名不在白名单内）")

    async with httpx.AsyncClient() as client:
        if payload.record_id:
            url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{settings.FEISHU_APP_TOKEN}/tables/{table_id}/records/{payload.record_id}"
            resp = await client.put(url, headers=headers, json={"fields": fields}, timeout=15)
        else:
            url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{settings.FEISHU_APP_TOKEN}/tables/{table_id}/records"
            resp = await client.post(url, headers=headers, json={"fields": fields}, timeout=15)

        data = resp.json()
        if resp.status_code == 200 and data.get("code") == 0:
            record_id = data.get("data", {}).get("record", {}).get("record_id")
            # 新建简历后自愈：库里仅此一份时自动设为生效。自愈内部自拉取且全 try/except——
            # 记录已创建成功，这里任何抖动都绝不把它变成「保存失败」（否则用户重试会产生重复简历）。
            # only_record_id 锁定目标：防飞书读后写延迟下拉到旧列表、把别的简历错设为生效
            if payload.table_type == "resume" and not payload.record_id:
                await _ensure_single_resume_active(only_record_id=record_id)
            return record_id
        raise ValueError(f"保存失败: {data.get('msg')}")


async def delete_strategy_service(payload: DeleteStrategyRequest) -> bool:
    token = await feishu_client.get_tenant_access_token()
    table_id = settings.FEISHU_TABLE_ID_RESUMES

    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{settings.FEISHU_APP_TOKEN}/tables/{table_id}/records/{payload.record_id}"
    headers = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient() as client:
        # 护栏：生效中的简历禁止删除，防止投递/改写链路静默拿到空简历
        check = await client.get(url, headers=headers, timeout=15)
        check_data = check.json()
        if check.status_code == 200 and check_data.get("code") == 0:
            fields = (check_data.get("data") or {}).get("record", {}).get("fields") or {}
            status = fields.get("当前状态")
            if status == "启用" or (isinstance(status, list) and "启用" in status):
                raise ValueError("该简历当前为生效底稿，请先将其它简历设为生效后再删除")

        resp = await client.delete(url, headers=headers, timeout=15)
        data = resp.json()
        if resp.status_code == 200 and data.get("code") == 0:
            return True
        raise ValueError(f"飞书 API 删除请求失败: {data.get('msg')}")


async def get_preferences_service() -> list[dict[str, Any]]:
    """拉取求职偏好数据 (从本地 SQLite)"""
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS job_preferences (
            record_id TEXT PRIMARY KEY,
            type TEXT,
            rule TEXT,
            status TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS evaluation_weights (
            dimension TEXT PRIMARY KEY,
            weight REAL
        )
    """)

    cursor.execute("SELECT record_id, type, rule, status FROM job_preferences")
    rows = cursor.fetchall()
    conn.close()

    formatted = []
    for r in rows:
        formatted.append({
            "record_id": r["record_id"],
            "type": r["type"],
            "rule": r["rule"],
            "status": r["status"],
        })
    return formatted


async def upsert_preference_service(payload: PreferenceUpsertRequest) -> str:
    """新增或修改求职偏好 (存入本地 SQLite)"""
    if payload.type not in PREFERENCE_TYPE_WHITELIST:
        raise ValueError(f"不支持的偏好类型: {payload.type!r}（仅允许 核心加分 / 职业愿景 / 自动化阈值）")
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    if payload.record_id:
        cursor.execute(
            "UPDATE job_preferences SET type=?, rule=?, status=? WHERE record_id=?",
            (payload.type, payload.rule, payload.status, payload.record_id),
        )
    else:
        rec_id = str(uuid.uuid4())
        cursor.execute(
            "INSERT INTO job_preferences (record_id, type, rule, status) VALUES (?, ?, ?, ?)",
            (rec_id, payload.type, payload.rule, payload.status),
        )

    conn.commit()
    conn.close()
    return payload.record_id or rec_id


async def get_weights_service() -> dict[str, float]:
    """拉取 AI 评估权重"""
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS evaluation_weights (
            dimension TEXT PRIMARY KEY,
            weight REAL
        )
    """)
    cursor.execute("SELECT dimension, weight FROM evaluation_weights")
    rows = cursor.fetchall()
    conn.close()

    weights = {
        "role_match": 1.0,
        "skills_align": 1.0,
        "seniority": 0.8,
        "interview_prob": 0.8,
        "compensation": 0.8,
        "market_fit": 0.5,
        "growth": 0.5,
        "company_stage": 0.2,
    }

    for r in rows:
        weights[r["dimension"]] = float(r["weight"])

    return weights


async def update_weights_service(new_weights: dict[str, float]) -> None:
    """更新 AI 评估权重（仅接受 0~2 的数值权重，非法维度/数值直接丢弃防污染评估表）"""
    sanitized = {
        str(dim).strip(): float(w)
        for dim, w in (new_weights or {}).items()
        if isinstance(dim, str) and dim.strip()
        and isinstance(w, (int, float))
        and 0 <= float(w) <= 2
    }
    if not sanitized:
        return
    db_path = get_db_path()
    with closing(sqlite3.connect(db_path)) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS evaluation_weights (
                dimension TEXT PRIMARY KEY,
                weight REAL
            )
        """)
        for dimension, weight in sanitized.items():
            cursor.execute(
                "INSERT INTO evaluation_weights (dimension, weight) VALUES (?, ?) ON CONFLICT(dimension) DO UPDATE SET weight=?",
                (dimension, weight, weight),
            )
        conn.commit()


async def delete_preference_service(record_id: str) -> str:
    """删除指定的偏好规则 (从本地 SQLite)"""
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM job_preferences WHERE record_id=?", (record_id,))
    conn.commit()
    conn.close()
    return "本地记录已彻底抹除!"
