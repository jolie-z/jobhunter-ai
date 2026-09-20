"""面经 RAG：单篇面经情报库检索 + 面经高频题库聚合缓存。

收编自旧项目 Auto-Job-Hunter-OpenSource/interview_scraper/ai_interview_rag.py（2026-09-04），
逻辑保持一致，配置从外部项目 env 硬依赖改为本仓库 common.config._cfg 动态读取
（.env 与配置页 settings.json 双源，保存即生效）。

数据流：
  单篇面经情报库（INTERVIEW_REPORTS）--按岗位群内存模糊匹配--> LLM 聚合
  --> 面经高频题库（INTERVIEW_SUMMARY，联合主键缓存，单篇数量变动自动失效）
"""

import datetime
import json

import requests
from openai import OpenAI

from app.core.llm_tracker import make_tracked_client
from common.config import _cfg

API_BASE = "https://open.feishu.cn/open-apis"


def _feishu_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def get_feishu_token() -> str:
    res = requests.post(
        f"{API_BASE}/auth/v3/tenant_access_token/internal",
        json={"app_id": _cfg("FEISHU_APP_ID"), "app_secret": _cfg("FEISHU_APP_SECRET")},
        proxies={"http": None, "https": None},  # type: ignore[dict-item]  # requests stub 过严：None 值运行时合法
    ).json()
    return res.get("tenant_access_token")


def _reports_table_id() -> str:
    return _cfg("FEISHU_TABLE_ID_INTERVIEW_REPORTS")


def _summary_table_id() -> str:
    return _cfg("FEISHU_TABLE_ID_INTERVIEW_SUMMARY")


def fetch_single_reports_by_tags(token: str, job_group: str, business_track: str = None) -> list:
    """从「单篇面经情报库」中拉取符合标签的所有面经 (支持动态条件)"""
    url = f"{API_BASE}/bitable/v1/apps/{_cfg('FEISHU_APP_TOKEN')}/tables/{_reports_table_id()}/records/search"

    # 飞书 API 对「多选/单选标签」字段的过滤过死，改用 Python 内存级子串模糊匹配；
    # 仅业务赛道保留服务端过滤（文本字段），岗位群全量拉回本地匹配
    conditions = []
    if business_track:
        conditions.append({"field_name": "细分业务赛道", "operator": "contains", "value": [business_track]})

    payload = {
        "sort": [{"field_name": "热度分", "desc": True}],
        "page_size": 500,
    }
    if conditions:
        payload["filter"] = {"conjunction": "and", "conditions": conditions}

    try:
        res = requests.post(url, headers=_feishu_headers(token), json=payload, proxies={"http": None, "https": None}).json()  # type: ignore[dict-item]  # requests stub 过严：None 值运行时合法
        raw_items = res.get("data", {}).get("items", [])
    except Exception as e:
        print(f"❌ 飞书 API 请求异常: {e}")
        return []

    matched_items = []
    for item in raw_items:
        fields = item.get("fields", {})
        # 多选标签格式是 ["智能客服/运营", "其他"]，单选是纯字符串——统一转小写字符串后做子串匹配
        job_field_str = str(fields.get("目标岗位群", "")).lower()
        if job_group.lower() in job_field_str:
            matched_items.append(item)

    return matched_items


def check_cache_summary(token: str, composite_key: str):
    url = f"{API_BASE}/bitable/v1/apps/{_cfg('FEISHU_APP_TOKEN')}/tables/{_summary_table_id()}/records/search"
    payload = {
        "filter": {
            "conjunction": "and",
            "conditions": [{"field_name": "联合主键", "operator": "is", "value": [composite_key]}],
        }
    }
    res = requests.post(url, headers=_feishu_headers(token), json=payload, proxies={"http": None, "https": None}).json()  # type: ignore[dict-item]  # requests stub 过严：None 值运行时合法
    items = res.get("data", {}).get("items", [])
    if items:
        return items[0]["record_id"], items[0]["fields"]
    return None, None


def _cleaner_llm_config():
    """清洗 LLM 通道（与 job_processor.step1_rule_filter 同策略）：专属通道优先，未配置回落主通道。"""
    use_main = (_cfg("USE_MAIN_LLM_FOR_CLEANER") or "").strip().lower() in ("1", "true", "yes")
    if not use_main:
        key = _cfg("CLEANER_LLM_API_KEY")
        url = _cfg("CLEANER_LLM_BASE_URL")
        model = _cfg("CLEANER_LLM_MODEL")
        if key and url:
            return key, url, (model or _cfg("OPENAI_MODEL") or "qwen-turbo")
    return (
        _cfg("OPENAI_API_KEY"),
        _cfg("OPENAI_BASE_URL"),
        _cfg("OPENAI_MODEL") or "qwen-turbo",
    )


def generate_summary_via_llm(job_group: str, business_track: str, raw_records: list) -> str:
    print(f"  [🤖] 正在唤醒大模型，阅读 {len(raw_records)} 篇单篇面经进行高频题库聚合...")

    knowledge_context = ""
    for idx, rec in enumerate(raw_records):
        fields = rec.get("fields", {})
        knowledge_context += f"--- 第 {idx+1} 篇 (热度:{fields.get('热度分', 0)}) ---\n"
        knowledge_context += f"问题清单：\n{fields.get('面试问题清单', '无')}\n"
        knowledge_context += f"黄金回答：\n{fields.get('黄金回答思路', '无')}\n\n"

    track_display = business_track if business_track else "所有/通用"

    system_prompt = f"""
    你是一个资深的 AI 猎头。现在有 {len(raw_records)} 篇关于【{track_display}】赛道【{job_group}】岗位的真实面经。
    请阅读这些面经，进行语义去重，提取出出现频次最高的核心面试题。

    请严格按照以下 Markdown 格式输出总结报告：
    ## 一、 高频核心面试题 Top 5 (标注出现频次)
    ## 二、 黄金答题框架与套路总结
    ## 三、 避坑指南
    """

    key, url, model = _cleaner_llm_config()
    client = make_tracked_client(OpenAI(api_key=key, base_url=url), caller="interview_rag")
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"以下是参考的面经原料：\n{knowledge_context}"},
        ],
        temperature=0.3,
    )
    return response.choices[0].message.content


def save_or_update_summary(token: str, record_id: str, composite_key: str, job_group: str, business_track: str, count: int, content: str):
    headers = _feishu_headers(token)
    fields = {
        "联合主键": composite_key,
        "目标岗位群": job_group,
        "细分业务赛道": [business_track],
        "收录单篇数量": count,
        "面经总内容": content,
        "最后更新时间": int(datetime.datetime.now().timestamp() * 1000),
    }

    base = f"{API_BASE}/bitable/v1/apps/{_cfg('FEISHU_APP_TOKEN')}/tables/{_summary_table_id()}"
    if record_id:
        res = requests.put(f"{base}/records/{record_id}", headers=headers, json={"fields": fields}, proxies={"http": None, "https": None}).json()  # type: ignore[dict-item]  # requests stub 过严：None 值运行时合法
        action_name = "更新"
    else:
        res = requests.post(f"{base}/records", headers=headers, json={"fields": fields}, proxies={"http": None, "https": None}).json()  # type: ignore[dict-item]  # requests stub 过严：None 值运行时合法
        action_name = "新增"

    # 只有飞书明确返回 code=0 才算真成功，否则把真实报错打出来
    if res.get("code") == 0:
        print(f"  [✅] 飞书写入成功！(操作: {action_name})")
    else:
        print("  [❌] 飞书写入失败！！！请严格检查表字段设置，真实报错信息如下:")
        print(f"       {json.dumps(res, ensure_ascii=False)}")


def ask_for_interview_summary(job_group: str, business_track: str = None, force_refresh: bool = False):
    """主流程：检索单篇面经 → 按联合主键命中缓存（数量不变即免费）→ 否则 LLM 聚合并回写题库。

    返回 (面经总内容, 单篇面经记录列表)；库中无相关面经时返回 (None, [])。
    """
    track_display = business_track if business_track else "全部赛道"
    print(f"\n🎯 发起查询: 请求【{track_display}】领域的【{job_group}】面经")
    token = get_feishu_token()

    composite_key = f"{job_group}_{track_display}"

    single_records = fetch_single_reports_by_tags(token, job_group, business_track)
    current_count = len(single_records)
    print(f"  [🔍] 底层情报库中共找到 {current_count} 篇相关单篇面经。")

    if current_count == 0:
        print("  [📭] 库里暂时没有该方向的面经，去多刷点小红书吧！")
        return None, []

    record_id, cache_fields = check_cache_summary(token, composite_key)
    cached_count = cache_fields.get("收录单篇数量", 0) if cache_fields else 0

    # 未强制刷新且单篇数量没变 → 直接吃缓存（0 Token）
    if not force_refresh and cache_fields and cached_count == current_count:
        print(f"  [⚡ 命中缓存] 数量未变 ({current_count}篇)，直接返回已生成的面经总！(消耗 0 Token)")
        final_summary = cache_fields.get("面经总内容", "")
    else:
        if force_refresh:
            print("  [🔄 强制刷新] 用户主动点击刷新按钮，准备无视缓存重算...")
        elif cache_fields:
            print(f"  [⚠️ 缓存失效] 单篇数量从 {cached_count} 变动为 {current_count}，准备触发重算...")
        else:
            print("  [🔨 初次构建] 库中无缓存，准备首次生成...")

        final_summary = generate_summary_via_llm(job_group, business_track, single_records)
        save_or_update_summary(token, record_id, composite_key, job_group, track_display, current_count, final_summary)

    # 飞书富文本字段可能返回 list，强行提取文本转字符串
    if isinstance(final_summary, list):
        final_summary = "".join([str(item.get("text", "")) if isinstance(item, dict) else str(item) for item in final_summary])
    elif not isinstance(final_summary, str):
        final_summary = str(final_summary)

    return final_summary, single_records
