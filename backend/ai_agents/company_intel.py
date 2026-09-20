"""公司外部情报统一入口：Serper 多维并发搜索（主引擎）+ Tavily 降级（备用引擎）。

Serper 引擎移植自外部仓库 interview_scraper/company_searcher.py 的 search_company_ai_news：
4 路并发（核心业务 / 竞品地位 / AI 布局 / 近一月融资裁员财报新闻）+ LLM 结构化汇总。
不跨仓库直接 import 的原因：外部模块 `from common.config import ...` 会与本项目
backend/common 包撞名，在 backend 进程内必然 ImportError（此前面试情报链路即因此静默断链）。

两个引擎的区别：
- Serper = Google 搜索管道：真实 SERP/新闻结果 + 时间窗过滤，只取干净摘要，适合查"近期动态"；
- Tavily = LLM 检索管道：抓网页全文切片，无时间过滤，易混入工商信息类档案页噪声，仅作降级。
"""
import concurrent.futures
import json
import os
import threading
import time
from pathlib import Path

import requests

from common.config import get_serper_api_key
from app.core.config import settings
from app.core.llm_client import get_openai_client

from .ai_scorer import search_company_info_tavily

SERPER_TIMEOUT = 10

# 🌟 同公司多岗位共享一份情报：14 天内同公司只搜一次，避免重复消耗 Google Serper 调用与算力
_SERPER_CACHE_TTL = 14 * 86400
_SERPER_CACHE_PATH = Path(__file__).resolve().parent.parent / "data" / "serper_company_cache.json"
_serper_cache_lock = threading.Lock()
_serper_cache: dict = {}


def _load_serper_cache() -> None:
    global _serper_cache
    if _serper_cache:
        return
    try:
        if _SERPER_CACHE_PATH.exists():
            with open(_SERPER_CACHE_PATH, encoding="utf-8") as f:
                _serper_cache = json.load(f) or {}
    except Exception:
        _serper_cache = {}


def _save_serper_cache() -> None:
    try:
        _SERPER_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = f"{_SERPER_CACHE_PATH}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_serper_cache, f, ensure_ascii=False)
        os.replace(tmp, _SERPER_CACHE_PATH)
    except Exception as e:
        print(f"   ⚠️ [Serper] 缓存写盘失败: {e}")


def _serper_cache_key(company_name: str) -> str:
    try:
        from job_processor.job_dedup import normalize_company
        return normalize_company(company_name) or str(company_name).strip().lower()
    except Exception:
        return str(company_name).strip().lower()


def _serper_cache_lookup(key: str, now: float):
    """同公司 14 天内直接复用；模糊匹配 ≥4 字符（华为 vs 华为技术）"""
    hit = _serper_cache.get(key)
    if hit and now - float(hit.get("ts", 0)) < _SERPER_CACHE_TTL and str(hit.get("intel", "")).startswith("###"):
        return hit
    if len(key) >= 4:
        for k, v in _serper_cache.items():
            if not k or len(k) < 4 or k == key:
                continue
            if (key in k or k in key) and now - float(v.get("ts", 0)) < _SERPER_CACHE_TTL and str(v.get("intel", "")).startswith("###"):
                return v
    return None


# （查询词, 检索类型, Google 时间窗）：新闻只看近一个月，避免过期八卦
_SERPER_QUERIES = [
    ('"{company}" 核心业务 OR 战略 OR 主打产品', "search", "qdr:y"),
    ('"{company}" 竞品 OR 市场地位 OR 行业排名', "search", "qdr:y"),
    ('"{company}" AI布局 OR 大模型架构 OR 技术栈', "search", "qdr:y"),
    ('{company} 融资 OR 裁员 OR 财报 OR 高管', "news", "qdr:m"),
]

_INTEL_SUMMARY_PROMPT = """你是一个资深的商业分析师。请根据以下我通过搜索引擎抓取的关于【{company}】的碎片化情报，整理出一份结构化、极具商业洞察的情报简报（字数控制在 400 字左右）。

碎片情报池：
{fragments}

请严格按照以下 Markdown 格式输出（不要任何解释性废话）：
### 🏢 【{company}】商业情报简报
**1. 核心业务与市场地位**
(提炼其主要赚钱业务、护城河或竞品对比)

**2. 技术栈与 AI 布局**
(提炼其在 AI、大模型、底层架构方面的动作，没提就不写)

**3. 资本动态与近期舆情**
(提炼近期的融资、财报、组织架构调整、裁员等，没提就不写)

注意：如果在某一方面情报完全空白，请写"暂无公开情报"，绝对不能凭空捏造。"""


def _is_anonymous(company_name: str) -> bool:
    if not company_name:
        return True
    return "某" in company_name or company_name in ("未知公司", "保密", "匿名")


def _fetch_serper(api_key: str, query: str, search_type: str = "search", tbs: str = "qdr:y") -> dict:
    """单次 Serper 请求的原子函数，失败返回空 dict 不抛出。"""
    try:
        resp = requests.post(
            "https://google.serper.dev/search" if search_type == "search" else f"https://google.serper.dev/{search_type}",
            data=json.dumps({"q": query, "num": 5, "tbs": tbs, "gl": "cn", "hl": "zh-cn"}),
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            timeout=SERPER_TIMEOUT,
            proxies={"http": None, "https": None},
        )
        return resp.json()
    except Exception as e:
        print(f"  [❌] Serper 请求失败 ({query}): {e}")
        return {}


def search_company_ai_news(company_name: str) -> str:
    """Serper 4 路并发侦察 + LLM 结构化汇总（支持 14 天磁盘缓存）。"""
    api_key = get_serper_api_key()
    if not api_key:
        raise RuntimeError("SERPER_NOT_CONFIGURED")

    # 缓存命中：同公司 14 天内直接复用
    cache_key = _serper_cache_key(company_name)
    now = time.time()
    with _serper_cache_lock:
        _load_serper_cache()
        hit = _serper_cache_lookup(cache_key, now)
        if hit:
            print(f"   📦 [Serper] 命中公司情报缓存: {company_name}")
            return hit["intel"]

    print(f"  [🕵️‍♂️] 启动 Serper 并发侦察引擎，多维度搜索【{company_name}】...")

    raw_results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [
            executor.submit(_fetch_serper, api_key, q.format(company=company_name), st, tbs)
            for q, st, tbs in _SERPER_QUERIES
        ]
        for future, (q, st, _tbs) in zip(futures, _SERPER_QUERIES):
            data = future.result()
            items = data.get("organic" if st == "search" else "news", [])[:3]
            tag = "网页" if st == "search" else "新闻"
            for item in items:
                title = item.get("title", "")
                snippet = item.get("snippet", "")
                if title or snippet:
                    raw_results.append(f"- [{tag}] {title}: {snippet}")

    if not raw_results:
        return "未检索到该公司近期的公开重大业务动态。建议直接与候选人探讨其认知。"

    print(f"  [✅] 情报搜集完成！共抓取到 {len(raw_results)} 条碎片情报。正在呼叫 LLM 进行深度汇总...")

    # LLM 汇总失败时降级返回清洗后的原始碎片，绝不让程序挂掉
    try:
        prompt = _INTEL_SUMMARY_PROMPT.format(
            company=company_name, fragments="\n".join(raw_results)
        )
        response = get_openai_client().chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            timeout=20,
        )
        report = (response.choices[0].message.content or "").strip()
        if report:
            print("  [✅] LLM 深度情报汇总完成！")
            with _serper_cache_lock:
                _serper_cache[cache_key] = {"intel": report, "ts": now}
                _save_serper_cache()
            return report
    except Exception as e:
        print(f"  [⚠️] LLM 汇总失败，降级返回原始碎片数据: {e}")


    return f"【{company_name} 基础情报】\n" + "\n".join(raw_results[:5])


def fetch_company_intel(company_name: str) -> str:
    """统一调度器：Serper 主引擎，未配置/异常时降级 Tavily。

    返回约定与既有链路一致：以 "⚠️" 开头表示无有效情报（调用方不会回写飞书）。
    """
    if _is_anonymous(company_name):
        return "⚠️ 匿名或未知公司，跳过外部背调"

    try:
        serper_intel = search_company_ai_news(company_name)
        if serper_intel:
            return serper_intel
    except RuntimeError:
        print("  [⏬] 未配置 SERPER_API_KEY，公司情报降级到 Tavily 引擎...")
    except Exception as e:
        print(f"  [⏬] Serper 引擎异常（{str(e)[:60]}），公司情报降级到 Tavily 引擎...")

    return search_company_info_tavily(company_name)
