# backend/app/services/job_service.py
import json

import requests

from app.core.config import settings
from app.core.feishu_utils import extract_feishu_text, get_tenant_access_token

# 统一使用配置中的主表 ID（动态读取，配置页保存即生效）

def get_pending_apply_jobs():
    """(apply_assistant 使用) 获取状态为【简历AI改写】的待处理岗位"""
    token = get_tenant_access_token()
    if not token:
        return []

    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{settings.FEISHU_APP_TOKEN}/tables/{settings.FEISHU_TABLE_ID_JOBS}/records/search"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {
        "filter": {"conjunction": "and", "conditions": [{"field_name": "跟进状态", "operator": "is", "value": ["简历AI改写"]}]},
        "page_size": 100
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=15, proxies={"http": None, "https": None})  # type: ignore[dict-item]  # requests stub 过严：None 值运行时合法
        data = resp.json()
        jobs = []
        for record in data.get("data", {}).get("items", []):
            fields = record.get("fields", {})
            jobs.append({
                "record_id": record.get("record_id"),
                "company": extract_feishu_text(fields.get("公司名称", "")),
                "job_title": extract_feishu_text(fields.get("岗位名称", "")),
                "jd_text": extract_feishu_text(fields.get("岗位详情", ""))
            })
        return jobs
    except Exception as e:
        print(f"❌ 拉取待处理岗位异常: {e}")
        return []

def get_existing_jobs() -> set:
    """(auto_patrol 使用) 获取飞书上已经存在的岗位去重 Key 集合"""
    token = get_tenant_access_token()
    if not token:
        return set()

    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{settings.FEISHU_APP_TOKEN}/tables/{settings.FEISHU_TABLE_ID_JOBS}/records/search"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    seen = set()
    page_token = None
    try:
        while True:
            payload = {"page_size": 500}
            if page_token:
                payload["page_token"] = page_token
            resp = requests.post(url, headers=headers, json=payload, timeout=20, proxies={"http": None, "https": None})  # type: ignore[dict-item]  # requests stub 过严：None 值运行时合法
            data = resp.json()
            for item in data.get("data", {}).get("items", []):
                fields = item.get("fields", {})
                comp = extract_feishu_text(fields.get("公司名称", ""))
                city = extract_feishu_text(fields.get("城市", ""))
                sal = extract_feishu_text(fields.get("薪资", ""))
                seen.add(f"{comp}###{city}###{sal}")
            if not data.get("data", {}).get("has_more"):
                break
            page_token = data.get("data", {}).get("page_token")
        return seen
    except Exception as e:
        print(f"⚠️ 拉取去重数据异常: {e}")
        return set()

def push_job_to_feishu(feishu_data: dict) -> bool:
    """(auto_patrol 使用) 全量写入新爬取的岗位到飞书"""
    token = get_tenant_access_token()
    if not token:
        return False

    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{settings.FEISHU_APP_TOKEN}/tables/{settings.FEISHU_TABLE_ID_JOBS}/records"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        resp = requests.post(url, headers=headers, json={"fields": feishu_data}, timeout=15, proxies={"http": None, "https": None})  # type: ignore[dict-item]  # requests stub 过严：None 值运行时合法
        return resp.json().get("code") == 0
    except Exception:
        return False

def normalize_ai_rewrite_json_payload(json_str: str) -> str:
    """清洗 AI 改写的 JSON 字符串"""
    if not json_str:
        return ""
    try:
        data = json.loads(json_str)
        return json.dumps(data, ensure_ascii=False)
    except Exception:
        return str(json_str)

def extract_rationales_from_json(json_str: str) -> str:
    """从 JSON 中提取改写理由"""
    if not json_str:
        return ""
    try:
        data = json.loads(json_str)
        rationale = data.get("rewrite_rationale", {})
        if isinstance(rationale, dict):
            return "\n".join([f"[{k}] {v}" for k, v in rationale.items()])
        return str(rationale)
    except Exception:
        return ""
