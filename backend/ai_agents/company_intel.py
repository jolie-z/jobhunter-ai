"""公司外部情报统一入口：博查（国内直连，主引擎）+ Serper + Tavily（境外网络，降级备用）。

三个引擎共用同一套 4 路并发侦察 + LLM 结构化汇总流程
（核心业务 / 竞品地位 / AI 布局 / 近一月融资裁员财报新闻）。

引擎优先级：
- 博查 = 国内直连、注册送 1000 次：默认主引擎，无需 VPN；
- Serper = Google 搜索管道：真实 SERP/新闻结果 + 时间窗过滤，需要境外网络；
- Tavily = LLM 检索管道：抓网页全文切片，无时间过滤，易混入工商信息类档案页噪声，仅作兜底。

不跨仓库直接 import 的原因：外部模块 `from common.config import ...` 会与本项目
backend/common 包撞名，在 backend 进程内必然 ImportError（此前面试情报链路即因此静默断链）。
"""
import concurrent.futures
import json
import os
import threading
import time
from pathlib import Path

import requests

from app.core.config import settings
from app.core.db_paths import writable_path
from app.core.llm_client import get_openai_client
from common.config import get_bocha_api_key, get_serper_api_key

from .ai_scorer import search_company_info_tavily

SERPER_TIMEOUT = 10
BOCHA_TIMEOUT = 12
BOCHA_ENDPOINT = "https://api.bochaai.com/v1/web-search"

# 🌟 429 限流治理（2026-11-01 波次复盘）：Wave1 并发初评 5 公司 × 4 路侦察 = 20 个请求
# 同一秒全部打出，单次波次实测 16 条 429（"You have reached the request limit"），
# 只能靠 Serper 兜底、情报质量受损。429 成簇出现在扇出瞬间、全天其余时段为零 —— 是
# 瞬时并发撞限流而非配额耗尽，治理三件套：
# 1) 全局匀速节流：相邻请求发起间隔 ≥ _BOCHA_MIN_INTERVAL，把突发摊平成匀速队列；
# 2) 429 指数退避重试：瞬时限流等一下就能过，避免白扔请求；
# 3) 重试耗尽共享熔断：连续退避仍 429（疑似配额真耗尽）时打开全进程冷却窗，
#    同批其余请求快速失败走 Serper，不再排队撞墙徒耗等待。
_BOCHA_MIN_INTERVAL = 1.0        # 相邻请求最小间隔（秒），≈ 博查常见档位的 QPS 上限
_BOCHA_429_RETRIES = 2           # 429 退避重试次数（首次请求之外）
_BOCHA_429_BACKOFF = (2.0, 5.0)  # 每次重试前的等待秒数
_BOCHA_429_COOLDOWN = 60.0       # 重试耗尽后的全进程冷却窗（秒）

_bocha_pace_lock = threading.Lock()
_bocha_next_slot_ts = 0.0        # 下一个可发起请求的时间槽
_bocha_429_lock = threading.Lock()
_bocha_429_cooldown_until = 0.0


def _bocha_429_cooldown_active() -> bool:
    with _bocha_429_lock:
        return time.time() < _bocha_429_cooldown_until


def _bocha_throttle() -> None:
    """全局匀速节流：锁内预约时间槽、锁外睡眠，保证相邻请求发起间隔 ≥ _BOCHA_MIN_INTERVAL。"""
    global _bocha_next_slot_ts
    with _bocha_pace_lock:
        start = max(time.time(), _bocha_next_slot_ts)
        _bocha_next_slot_ts = start + _BOCHA_MIN_INTERVAL
    wait = start - time.time()
    if wait > 0:
        time.sleep(wait)

# 🌟 同公司多岗位共享一份情报：14 天内同公司只搜一次，避免重复消耗 Google Serper 调用与算力
_SERPER_CACHE_TTL = 14 * 86400
# db_paths 阀门：缓存写盘禁止落安装目录（resources 内），否则自动更新即清空
_SERPER_CACHE_PATH = writable_path(
    Path(__file__).resolve().parent.parent / "data" / "serper_company_cache.json",
    "serper_company_cache.json",
)
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

# （查询词, 博查 freshness 时间窗）：语义同上，新闻只看近一个月
_BOCHA_QUERIES = [
    ('"{company}" 核心业务 OR 战略 OR 主打产品', "oneYear"),
    ('"{company}" 竞品 OR 市场地位 OR 行业排名', "oneYear"),
    ('"{company}" AI布局 OR 大模型架构 OR 技术栈', "oneYear"),
    ('{company} 融资 OR 裁员 OR 财报 OR 高管', "oneMonth"),
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


def _fetch_bocha(api_key: str, query: str, freshness: str = "oneYear") -> dict | None:
    """单次博查请求的原子函数。失败返回 None（区别于「请求成功但无结果」的空 dict）。

    429 限流自动退避重试；重试耗尽则打开全进程冷却窗并返回 None，冷却窗内的
    后续请求直接快速失败，不再发网络请求。其余失败（鉴权/网络/解析）保持原契约：
    打日志、立即返回 None、不重试。
    """
    global _bocha_429_cooldown_until
    for attempt in range(_BOCHA_429_RETRIES + 1):
        if _bocha_429_cooldown_active():
            print(f"  [⏳] 博查 429 冷却窗生效中，跳过本次请求: {query[:40]}")
            return None
        _bocha_throttle()
        try:
            resp = requests.post(
                BOCHA_ENDPOINT,
                json={"query": query, "freshness": freshness, "summary": True, "count": 5},
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                timeout=BOCHA_TIMEOUT,
                proxies={"http": None, "https": None},
            )
            if resp.status_code == 429:
                if attempt < _BOCHA_429_RETRIES:
                    wait = _BOCHA_429_BACKOFF[min(attempt, len(_BOCHA_429_BACKOFF) - 1)]
                    print(f"  [⏳] 博查限流 (429)，{wait:.0f}s 后重试 ({attempt + 1}/{_BOCHA_429_RETRIES})...")
                    time.sleep(wait)
                    continue
                with _bocha_429_lock:
                    _bocha_429_cooldown_until = time.time() + _BOCHA_429_COOLDOWN
                print(f"  [❌] 博查请求失败 (429): {resp.text[:120]}")
                return None
            if resp.status_code != 200:
                print(f"  [❌] 博查请求失败 ({resp.status_code}): {resp.text[:120]}")
                return None
            payload = resp.json()
            # 成功响应有两种形态：
            # 1) 线上实际返回：{code: 200, msg: null, data: {webPages: {value: [...]}}}
            # 2) 官网示例/旧版：顶层 {webPages: {value: [...]}}
            # 统一归一化为「含 webPages 的那一层」，避免真实响应被误判为无结果。
            body = payload.get("data") if isinstance(payload.get("data"), dict) else None
            effective = body if body is not None and "webPages" in body else payload
            # 业务错误也可能以 200 + code/message 返回；无 webPages 且 code 非成功值 → 视为失败
            if not effective.get("webPages") and payload.get("code") not in (None, 0, 200, "0", "200"):
                print(f"  [❌] 博查业务错误 ({payload.get('code')}): {str(payload.get('message') or payload.get('msg') or '')[:120]}")
                return None
            return effective
        except Exception as e:
            print(f"  [❌] 博查请求异常 ({query}): {e}")
            return None
    return None  # pragma: no cover — 循环必经 continue/return，此处仅为类型收窄


def _summarize_fragments(company_name: str, raw_results: list[str]) -> tuple[str, bool]:
    """LLM 结构化汇总。返回 (简报文本, 是否来自 LLM)；失败降级原始碎片，绝不抛出。"""
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
            return report, True
    except Exception as e:
        print(f"  [⚠️] LLM 汇总失败，降级返回原始碎片数据: {e}")

    return f"【{company_name} 基础情报】\n" + "\n".join(raw_results[:5]), False


def _cached_intel(company_name: str) -> tuple[str | None, str, float]:
    """读取 14 天公司情报缓存。返回 (命中文本 | None, 缓存键, 当前时间)。"""
    cache_key = _serper_cache_key(company_name)
    now = time.time()
    with _serper_cache_lock:
        _load_serper_cache()
        hit = _serper_cache_lookup(cache_key, now)
        if hit:
            print(f"   📦 命中公司情报缓存: {company_name}")
            return hit["intel"], cache_key, now
    return None, cache_key, now


def _save_intel_cache(cache_key: str, intel: str, now: float) -> None:
    with _serper_cache_lock:
        _serper_cache[cache_key] = {"intel": intel, "ts": now}
        _save_serper_cache()


def search_company_bocha(company_name: str) -> str:
    """博查 4 路并发侦察 + LLM 结构化汇总（国内直连，共享 14 天磁盘缓存）。"""
    api_key = get_bocha_api_key()
    if not api_key:
        raise RuntimeError("BOCHA_NOT_CONFIGURED")

    cached, cache_key, now = _cached_intel(company_name)
    if cached:
        return cached

    # 429 冷却窗快速失败：冷却期内直接降级 Serper，不再发起 4 路扇出白撞限流
    # （缓存仍可用——上面 _cached_intel 命中时已提前返回）
    if _bocha_429_cooldown_active():
        print(f"  [⏳] 博查 429 冷却窗生效中，【{company_name}】直接降级 Serper 引擎")
        raise RuntimeError("BOCHA_REQUEST_FAILED")

    print(f"  [🕵️‍♂️] 启动博查并发侦察引擎，多维度搜索【{company_name}】...")

    raw_results: list[str] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [
            executor.submit(_fetch_bocha, api_key, q.format(company=company_name), freshness)
            for q, freshness in _BOCHA_QUERIES
        ]
        responses = [future.result() for future in futures]
        for data in responses:
            if not data:
                continue
            for item in (data.get("webPages") or {}).get("value", [])[:3]:
                title = item.get("name") or item.get("title") or ""
                snippet = item.get("summary") or item.get("snippet") or ""
                if title or snippet:
                    raw_results.append(f"- [网页] {title}: {snippet}")

    # 失败分层：全部失败（鉴权/网络/余额）或部分失败且零结果 → 抛出让调度器降级 Serper/Tavily。
    # 否则「2 路超时 + 2 路无结果」会被误判为真·无情报，且 truthy 文案会阻断后续引擎。
    failed_count = sum(1 for r in responses if r is None)
    if responses and failed_count == len(responses):
        raise RuntimeError("BOCHA_REQUEST_FAILED")
    if not raw_results and failed_count > 0:
        raise RuntimeError("BOCHA_PARTIAL_FAILED")

    # 全部请求成功且确实没有结果，才是「该公司暂无公开情报」
    if not raw_results:
        return "未检索到该公司近期的公开重大业务动态。建议直接与候选人探讨其认知。"

    print(f"  [✅] 情报搜集完成！共抓取到 {len(raw_results)} 条碎片情报。正在呼叫 LLM 进行深度汇总...")

    report, from_llm = _summarize_fragments(company_name, raw_results)
    if from_llm:
        _save_intel_cache(cache_key, report, now)
    return report


def search_company_ai_news(company_name: str) -> str:
    """Serper 4 路并发侦察 + LLM 结构化汇总（支持 14 天磁盘缓存）。"""
    api_key = get_serper_api_key()
    if not api_key:
        raise RuntimeError("SERPER_NOT_CONFIGURED")

    cached, cache_key, now = _cached_intel(company_name)
    if cached:
        return cached

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

    report, from_llm = _summarize_fragments(company_name, raw_results)
    if from_llm:
        _save_intel_cache(cache_key, report, now)
    return report


def fetch_company_intel(company_name: str) -> str:
    """统一调度器：博查（国内直连）→ Serper → Tavily，逐级降级。

    返回约定与既有链路一致：以 "⚠️" 开头表示无有效情报（调用方不会回写飞书）。
    """
    if _is_anonymous(company_name):
        return "⚠️ 匿名或未知公司，跳过外部背调"

    try:
        bocha_intel = search_company_bocha(company_name)
        if bocha_intel:
            return bocha_intel
    except RuntimeError as e:
        if str(e) == "BOCHA_NOT_CONFIGURED":
            print("  [⏬] 未配置 BOCHA_API_KEY，公司情报尝试 Serper 引擎...")
        else:
            print(f"  [⏬] 博查引擎请求失败（{str(e)[:60]}），公司情报尝试 Serper 引擎...")
    except Exception as e:
        print(f"  [⏬] 博查引擎异常（{str(e)[:60]}），公司情报尝试 Serper 引擎...")

    try:
        serper_intel = search_company_ai_news(company_name)
        if serper_intel:
            return serper_intel
    except RuntimeError:
        print("  [⏬] 未配置 SERPER_API_KEY，公司情报降级到 Tavily 引擎...")
    except Exception as e:
        print(f"  [⏬] Serper 引擎异常（{str(e)[:60]}），公司情报降级到 Tavily 引擎...")

    return search_company_info_tavily(company_name)
