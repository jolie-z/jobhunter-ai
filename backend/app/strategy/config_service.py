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

# upsert 首条策略时的默认名称（R1 P2：提取常量）
DEFAULT_STRATEGY_NAME = "默认策略"

# 2026-10-06：Tier2 AI 侦察兵内置示例规则（新装系统 ai_scout_rules 为空时回填展示，不落库）。
# 选材口径：通用红线（用工形式/岗位性质/作息），不含个人行业偏好；desc 为"关键词判定
# 边界+近义词+伪表述"三段式范例，供用户照此格式增删改。来源=开发机实测调优过的规则库。
DEFAULT_AI_SCOUT_EXAMPLES: list[dict[str, str]] = [
    {
        "keyword": "单休",
        "condition": "never",
        "desc": "“单休”在招聘JD中通常指每周固定工作六天、休息一天的制度。近义词包括：单休制、一周一休、每周一天休息。不符合的伪表述：如轮休、调休或名义上单休但实际无固定休息日、工时超标的情况。大小周、单休、5天半工作制、每周工作6天、单双休、月休4+1天、月休4天、月休6天均为单休描述",
    },
    {
        "keyword": "外包",
        "condition": "never",
        "desc": "关键特征：指非本公司直接雇佣的用工形式，如劳务派遣、项目外包、驻场服务、外派至甲方等。近义词包括“派遣”“驻场”“人力外包”“项目外派”。\n伪表述：公司内部岗位描述中包含“与XX公司合作”但未明确非直接雇佣关系，或虽提及“外包”但属于公司内部团队名称（如“XX外包部”），或是与外包团队合作，此类情况不符合。",
    },
    {
        "keyword": "销售",
        "condition": "never",
        "desc": "销售指的是岗位性质是销售，如岗位title/JD表述里包含：销售、客户代表、电销、BD、客户经理、客户成功经理、拓展市场、电话回访、电话销售、网销、面销、销售顾问、产品销售等描述均表示该岗位可能是个销售性质的岗位",
    },
    {
        "keyword": "实习",
        "condition": "never",
        "desc": "“实习”在招聘JD中通常指面向在校生或应届生的短期实践岗位，相关表述包括“实习岗位”“实习生”“实习期”等。\n近义/扩展表述：兼职实习、带薪实习、实习培训生。\n不符合的伪表述：\n1. 要求“有实习经历”但未明确招聘实习岗位；\n2. “实习证明”“实习经验”等仅作为经验要求而非岗位类型；\n3. “无实习要求”或“实习非必须”等否定性描述。",
    },
    {
        "keyword": "兼职",
        "condition": "never",
        "desc": "“兼职”通常指非全职、非固定雇佣形式，包括短期合同、按小时计酬、项目制等。相关表述：临时工、小时工、弹性工作、非全日制。不符合的情况：招聘JD中实际要求全职工作时间，或将实习、志愿者等非典型雇佣关系包装为“兼职”。",
    },
]

# 2026-10-06：AI 初评「求职偏好与核心加分项」内置示例（job_preferences 表空时回填展示，
# 不落库）。选材口径：通用 AI 技术岗加分项范例，展示"类型+一条具体可判定的规则"格式。
DEFAULT_PREFERENCE_EXAMPLES: list[dict[str, Any]] = [
    {
        "type": "核心加分",
        "rule": "核心技术栈：深度应用大语言模型（LLM）、智能体架构（Agent/LangGraph）、RAG（检索增强生成）、工作流自动化平台（Dify/Coze/n8n）等；具备 Python + SQL 数据处理能力的岗位优先。",
    },
    {
        "type": "核心加分",
        "rule": "角色与自主权：提供“从 0 到 1 端到端交付”机会、允许独立负责完整模块、注重数据驱动与业务指标（如转化率、留存）的岗位优先。",
    },
    {
        "type": "核心加分",
        "rule": "理想薪资范围落在目标区间内（按自身定位填写，如 12K-25K）即视为匹配信号。",
    },
]

CONTENT_TYPE_JSON = "application/json"
# 原文快照两字段（自动建字段，见 resume_snapshot_service.ensure_resume_snapshot_fields）
RESUME_SNAPSHOT_FIELD_ID = "原件快照ID"
RESUME_SNAPSHOT_FIELD_FILE = "原件附件"
RESUME_SAVE_FIELD_WHITELIST = {"简历版本", "简历内容", "个人信息", "当前状态", "结构化数据", RESUME_SNAPSHOT_FIELD_ID, RESUME_SNAPSHOT_FIELD_FILE}


def _final_structured_for_corrections(fields: dict) -> dict:
    """从保存 fields 里解出最终结构化 JSON，供修正回流比对；解析失败返回空 dict。"""
    try:
        raw = fields.get("结构化数据")
        data = json.loads(raw) if isinstance(raw, str) else raw
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


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
    from app.core.db_paths import job_hunter_db_path
    backend_dir = Path(__file__).resolve().parent.parent.parent
    return str(job_hunter_db_path(backend_dir / "data" / "job_hunter.db"))


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

        # 真实语义（空即空）：示例规则禁止在此回填——本函数是核心生效策略读取口，
        # 回填会让自动化清洗/初筛把示例当真实红线执行（R1 P1 修正：示例注入已上移
        # 至 rules_router /active 端点的展示层）
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


async def get_active_strategy_or_default() -> "ActiveStrategyResponse":
    """前端配置面板专用（R1 P2：默认兜底装配收口至 service 层）。

    无 active 行时返回"未配置"默认对象（数值 0/空数组 → 前端显示未配置态）
    + 内置示例侦察兵规则；自动化清洗/初筛不经过此函数（它们走 get_active_strategy
    的真实语义，空即空），示例不会被当真实红线执行。
    """
    try:
        result = await asyncio.to_thread(_fetch_active_strategy_sync)
    except HTTPException as e:
        if e.status_code != 404:
            raise
        result = None
    if result is None:
        result = ActiveStrategyResponse(
            min_salary_k=0,
            max_salary_k=0,
            experience_years_max=0,
            exclude_education=[],
            allowed_cities=[],
            safe_phrases=[],
            keyword_rules=[],
        )
    if not result.ai_scout_rules:
        # 空规则统一收口：真实空配置与新建默认对象在此回填示例（展示层）
        result.ai_scout_rules = [dict(r) for r in DEFAULT_AI_SCOUT_EXAMPLES]
        result.ai_scout_rules_is_example = True
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
        # 2026-10-07 修保存静默丢失：新装系统 job_strategies 无行时 UPDATE 影响 0 行，
        # 此前仍返回"策略更新成功"→ 前端保存后再打开依旧空配置（Windows 真机实测）。
        # 改为 upsert：UPDATE 未命中任何行时 INSERT 首条 active 策略。
        if cursor.rowcount == 0:
            cursor.execute(
                """
                INSERT INTO job_strategies (
                    strategy_name, is_active, min_salary_k, max_salary_k, experience_years_max,
                    exclude_education, allowed_cities, safe_phrases, keyword_rules, ai_scout_rules
                ) VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    DEFAULT_STRATEGY_NAME,
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
            logger.info("[策略] job_strategies 为空，已 INSERT 首条 active 策略（此前静默丢失）")
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

        # 原文快照（底稿）：解析任务留存的原件随简历记录绑定。
        # 建字段/取附件 token/修正记录任何失败都只降级告警，绝不阻塞简历保存本体
        if payload.snapshot_id:
            try:
                from app.services.resume_snapshot_service import (
                    ensure_resume_snapshot_fields,
                    ensure_snapshot_feishu_token,
                )

                # 建字段失败（权限/网络）时绝不写快照字段——未知字段会让飞书拒绝整条记录
                if await ensure_resume_snapshot_fields():
                    file_token = await ensure_snapshot_feishu_token(payload.snapshot_id)
                    fields[RESUME_SNAPSHOT_FIELD_ID] = payload.snapshot_id
                    # 附件字段写列表形态（与 render_router._update_record_attachments 同构）
                    if file_token:
                        fields[RESUME_SNAPSHOT_FIELD_FILE] = [{"file_token": file_token}]
            except Exception:
                logger.exception(f"快照字段写入准备失败（降级跳过）snapshot={payload.snapshot_id}")

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
            # 修正回流（错题本旁路）：对比初始解析与本次保存，差异模块落本地 SQLite
            if payload.table_type == "resume" and payload.snapshot_id:
                try:
                    from app.services.resume_snapshot_service import record_corrections

                    record_corrections(payload.snapshot_id, _final_structured_for_corrections(fields))
                except Exception:
                    logger.exception("修正回流记录失败（忽略）")
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
    # 2026-10-07 修回填条件过窄：此前"formatted 全空"才回填——但表里常见仅一条
    # 「自动化阈值」行（评估配置保存即写入），会被 bonus 过滤后前端仍见 0 条且无示例。
    # 改为"无 核心加分/职业愿景 条目"即回填（仅展示层，不落库；is_example 供前端
    # 显示提示条，用户增删改后按其真实配置展示）
    if not any(f["type"] in ("核心加分", "职业愿景") for f in formatted):
        for i, ex in enumerate(DEFAULT_PREFERENCE_EXAMPLES):
            formatted.append({
                "record_id": f"__example_{i + 1}",
                "type": ex["type"],
                "rule": ex["rule"],
                "status": "启用",
                "is_example": True,
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
