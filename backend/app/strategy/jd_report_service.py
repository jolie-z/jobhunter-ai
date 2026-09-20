import asyncio
import logging
import sys

import httpx
import requests

import common.config as _ccfg
from app.core.config import settings
from app.core.feishu_client import feishu_client
from app.core.feishu_utils import get_tenant_access_token
from common.config import get_openai_client

logger = logging.getLogger("strategy_jd_report")
logger.setLevel(logging.INFO)

CONTENT_TYPE_JSON = "application/json"


def _get_svc():
    return sys.modules.get("app.strategy.service")


def _safe_extract_text(field_val) -> str:
    if not field_val:
        return ""
    if isinstance(field_val, list):
        return "".join([str(item.get("text", "")) if isinstance(item, dict) else str(item) for item in field_val])
    return str(field_val)


async def generate_jd_report_service() -> str:
    """生成全局A级岗位能力要求报告"""
    svc = _get_svc()
    feishu = getattr(svc, "feishu_client", feishu_client) if svc else feishu_client
    token = await feishu.get_tenant_access_token()

    # 1. 抓取综合评级为 A 的最多 10 个岗位的 JD
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{settings.FEISHU_APP_TOKEN}/tables/{settings.FEISHU_TABLE_ID_JOBS}/records/search"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": CONTENT_TYPE_JSON}
    payload = {
        "filter": {
            "conjunction": "and",
            "conditions": [
                {"field_name": "综合评级 (A-F)", "operator": "is", "value": ["A"]}
            ],
        },
        "field_names": ["岗位名称", "岗位详情"],
        "page_size": 10,
    }

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(url, headers=headers, json=payload, timeout=15)
            resp_data = resp.json()
            items = resp_data.get("data", {}).get("items", [])
        except Exception as e:
            raise ValueError(f"拉取飞书 A 级岗位失败: {e}")

    if not items:
        raise ValueError("未找到任何综合评级包含 A 的岗位。请先在飞书『岗位数据汇总表』中给一些优质岗位打上 A 级评级。")

    combined_jd_text = ""
    for idx, item in enumerate(items):
        fields = item.get("fields", {})
        job_title = _safe_extract_text(fields.get("岗位名称", ""))
        jd_text = _safe_extract_text(fields.get("岗位详情", ""))
        combined_jd_text += f"【岗位 {idx+1}：{job_title}】\n{jd_text}\n\n"

    # 2. 调用 LLM 生成报告
    openai_getter = getattr(svc, "get_openai_client", get_openai_client) if svc else get_openai_client
    llm_client = openai_getter()
    system_prompt = (
        "你是一个顶级的互联网大厂人才招聘专家。你的任务是从以下多个顶级A类候选岗位的JD（职位描述）中，提炼出它们【反复出现】的最大公约数能力要求。\n"
        "请按出现频率降序排列，并严格将岗位要求拆分为以下四类：\n"
        "1. 硬技能 (Hard Skills)\n"
        "2. 软技能 (Soft Skills)\n"
        "3. 业务经验 (Business Experience)\n"
        "4. 加分项 (Bonus Points)\n"
        "请使用优雅的 Markdown 格式输出，排版清晰美观，重点词加粗。"
    )

    def call_llm():
        response = llm_client.chat.completions.create(
            model=_ccfg.OPENAI_MODEL if _ccfg.OPENAI_MODEL else "gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": combined_jd_text},
            ],
            temperature=0.3,
        )
        return response.choices[0].message.content or ""

    logger.info("[File: jd_report_service.py -> Func: generate_jd_report_service] 🚀 开始调用 LLM 生成能力要求报告")
    report_text = await asyncio.to_thread(call_llm)

    # 3. 将报告保存到飞书简历库的指定字段中
    success = await update_global_jd_report(report_text)
    if not success:
        logger.warning("[File: jd_report_service.py -> Func: generate_jd_report_service] 报告生成成功，但回写飞书简历库『全局A级JD能力画像』字段失败。请检查该字段是否存在。")
    return report_text


async def get_global_jd_report() -> str | None:
    """从飞书简历库读取『全局A级JD能力画像』字段值。"""
    svc = _get_svc()
    token_getter = getattr(svc, "get_tenant_access_token", get_tenant_access_token) if svc else get_tenant_access_token
    token = token_getter()
    req = getattr(svc, "requests", requests) if svc else requests

    headers = {"Authorization": f"Bearer {token}", "Content-Type": CONTENT_TYPE_JSON}
    search_url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{settings.FEISHU_APP_TOKEN}/tables/{settings.FEISHU_TABLE_ID_RESUMES}/records/search"
    payload = {
        "filter": {
            "conjunction": "and",
            "conditions": [
                {"field_name": "全局A级JD能力画像", "operator": "isNotEmpty", "value": []}
            ],
        },
        "page_size": 1,
    }
    try:
        resp = req.post(search_url, headers=headers, json=payload, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            logger.warning(f"[get_global_jd_report] 飞书返回错误: {data.get('msg')}")
            return None
        items = (data.get("data") or {}).get("items") or []
        if not items:
            return None
        fields = items[0].get("fields") or {}
        value = fields.get("全局A级JD能力画像")
        if isinstance(value, list):
            value = "".join(seg.get("text", "") for seg in value if isinstance(seg, dict))
        return value if value else None
    except Exception as e:
        logger.exception(f"[get_global_jd_report] 读取失败: {e}")
        return None


async def update_global_jd_report(report_text: str) -> bool:
    """将能力画像报告回写到飞书简历库的『全局A级JD能力画像』字段（写入当前启用的简历记录）。"""
    svc = _get_svc()
    token_getter = getattr(svc, "get_tenant_access_token", get_tenant_access_token) if svc else get_tenant_access_token
    token = token_getter()
    req = getattr(svc, "requests", requests) if svc else requests

    headers = {"Authorization": f"Bearer {token}", "Content-Type": CONTENT_TYPE_JSON}
    search_url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{settings.FEISHU_APP_TOKEN}/tables/{settings.FEISHU_TABLE_ID_RESUMES}/records/search"
    payload = {
        "filter": {
            "conjunction": "and",
            "conditions": [
                {"field_name": "当前状态", "operator": "is", "value": ["启用"]}
            ],
        },
        "page_size": 1,
    }
    try:
        resp = req.post(search_url, headers=headers, json=payload, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            logger.warning(f"[update_global_jd_report] 搜索启用简历失败: {data.get('msg')}")
            return False
        items = (data.get("data") or {}).get("items") or []
        if not items:
            logger.warning("[update_global_jd_report] 未找到启用的简历记录")
            return False
        record_id = items[0].get("record_id")
        update_url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{settings.FEISHU_APP_TOKEN}/tables/{settings.FEISHU_TABLE_ID_RESUMES}/records/{record_id}"
        update_resp = req.put(update_url, headers=headers, json={"fields": {"全局A级JD能力画像": report_text}}, timeout=30)
        update_resp.raise_for_status()
        if update_resp.json().get("code") != 0:
            logger.warning(f"[update_global_jd_report] 回写失败: {update_resp.json().get('msg')}")
            return False
        logger.info("[update_global_jd_report] ✅ 能力画像已回写飞书简历库")
        return True
    except Exception as e:
        logger.exception(f"[update_global_jd_report] 回写异常: {e}")
        return False
