import os
import sys
import json
import re
import time
import threading
import requests
from pathlib import Path
from typing import List, Dict

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from app.core.config import settings
from app.core.llm_client import get_openai_client

# 🌟 配置统一走 settings 动态读取（sync_settings_to_runtime 原地更新单例，配置页保存即生效）；
# 不在模块级冻结快照。注：飞书偏好表已废弃（偏好数据走本地 SQLite job_preferences）


def get_tavily_api_key():
    return getattr(settings, "TAVILY_API_KEY", "")

# ==========================================
# 🌟 全局新增：大模型幻觉清洗兜底引擎
# ==========================================
def sanitize_llm_output(raw_text: str) -> dict:
    """专门把大模型拉偏的格式强行捏成前端认识的 JSON"""
    result = {
        "rewritten_resume": "",
        "rewrite_rationale": {},
        "missing_data_requests": []
    }
    
    cleaned_text = raw_text.strip()
    
    # 绕过各种奇怪的解析Bug
    prefix_pattern = r"^`{3}(?:json)?\s*"
    suffix_pattern = r"\s*`{3}$"
    cleaned_text = re.sub(prefix_pattern, "", cleaned_text, flags=re.IGNORECASE)
    cleaned_text = re.sub(suffix_pattern, "", cleaned_text)
    
    try:
        data = json.loads(cleaned_text)
        
        resume_data = data.get("rewritten_resume", "")
        if isinstance(resume_data, dict):
            md_lines = []
            for k, v in resume_data.items():
                if not k.startswith("#"):
                    k = f"# {k}"
                md_lines.append(k)
                if isinstance(v, dict):
                    for sub_k, sub_v in v.items():
                        md_lines.append(f"**{sub_k}**: {sub_v}")
                elif isinstance(v, list):
                    for item in v:
                        md_lines.append(f"- {item}")
                else:
                    md_lines.append(str(v))
                md_lines.append("")
            result["rewritten_resume"] = "\n".join(md_lines)
            
        elif isinstance(resume_data, str):
            result["rewritten_resume"] = resume_data.replace('\\n', '\n')
            
        result["rewrite_rationale"] = data.get("rewrite_rationale", {})
        result["missing_data_requests"] = data.get("missing_data_requests", [])
        
    except json.JSONDecodeError:
        result["rewritten_resume"] = raw_text
        
    return result


# ==========================================
# 实时拉取飞书偏好表中的求职底线
# ==========================================
def get_user_preferences() -> str:
    import sqlite3
    import os
    # 🌟 改为直连本地 SQLite 数据库，避免每次调用请求飞书造成严重延迟和限流
    db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "job_hunter.db")
    if not os.path.exists(db_path):
        return ""
        
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # 检查表是否存在
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='job_preferences'")
        if not cursor.fetchone():
            return ""
            
        cursor.execute("SELECT type, rule FROM job_preferences WHERE status = '启用'")
        rows = cursor.fetchall()
        conn.close()
        
        bonuses, visions = [], []
        for r in rows:
            p_type = r["type"]
            rule = r["rule"]
            if not rule:
                continue
            if p_type == "核心加分":
                bonuses.append(rule)
            elif p_type == "职业愿景":
                visions.append(rule)
                
        if not (bonuses or visions):
            return ""

        pref_str = "【⚠️ 候选人核心求职偏好（最高优先级规则）】\n"
        if bonuses:
            pref_str += "📈 [核心加分项]（若JD命中以下特质，请在对应维度给予高分倾斜）：\n- " + "\n- ".join(bonuses) + "\n"
        if visions:
            pref_str += "🎯 [职业愿景匹配]（评估该岗位是否符合候选人的长远发展）：\n- " + "\n- ".join(visions) + "\n"

        return pref_str
    except Exception as e:
        print(f"⚠️ 拉取偏好数据失败: {e}")
        return ""






# ==========================================
_DEEP_EVAL_ROLE_PROMPT = "你是一位严谨资深的技术面试官与简历合规审计专家，专注于真实性核验与技能差距诊断。"

_DEEP_EVAL_BODY_FORMAT = """
【输出格式要求（最高优先级）】
必须、严格、仅输出一个纯净的 JSON 对象，不含任何 Markdown 代码块标记。
请以 JSON 格式输出，JSON 必须包含且仅包含以下字段：
- "extracted_skills": 字符串数组，提取 JD 明确要求的硬技能和工具
- "ats_ability_analysis": 字符串。01·JD分析，必须包含以下结构：
    1) 岗位类型识别（主类型/子类型/级别信号）
    2) Must-Have硬性要求（逗号分隔的技能词列表）
    3) Nice-to-Have加分项（逗号分隔）
    4) 软技能/综合素质
    5) 行业/业务高频术语
    6) 词汇重合度分析：简历与JD关键词的重合情况，明确指出哪些已体现、哪些缺失
    7) ⚠️缺失项硬约束：列出简历中完全不存在的技能，并标注"以上缺失项严禁在改写中以任何形式（包括了解/熟悉）注入"
    8) JD关键词提取（ATS锚定用）：扁平逗号分隔的关键词列表
- "resume_audit": 字符串。02·简历逐行审计，必须包含以下结构：
    按简历实际模块分段（如【个人总结】【专业技能】【项目经历：XXX】【工作经历：XXX】等，标题随简历内容动态变化），每段输出审计表：
    每条格式为：原文主张 | 证据核验 | 风险等级(✅安全/⚠️谨慎/❌高风险)
    对于⚠️谨慎级主张，必须附带安全措辞替换建议（如：精通→熟练掌握，100%→99%+，主导→负责）
    对于❌高风险级主张，标注"改写时必须删除或彻底重构"
    审计铁律：只审计简历中实际写了的内容；量化数据无评估方法说明的一律标⚠️谨慎；绝对化表述(100%/零失误/彻底)一律标⚠️谨慎
- "dream_picture": 字符串。理想画像与能力信号总结
- "strong_fit_assessment": 字符串。高杠杆匹配点。格式要求：按1）2）3）编号分行输出，每个匹配点独占一段，先写匹配点标题再加粗，后跟具体分析
- "risk_red_flags": 字符串。致命硬伤与后果推演。格式要求：按1、2、3、4编号分行输出，每个硬伤独占一段，先用【】标注硬伤类型再加粗标题，后跟后果推演
- "deep_action_plan": 字符串。破局行动计划，必须包含以下结构：
    1) 简历修改策略（针对本岗位的具体改写方向）
    2) 关键信息索取（向候选人追问缺失的技术细节）
    3) 技能/项目补强建议（按时间线分级，每个任务必须标注四要素）：
       格式：[时间桶] 具体任务 → 产出证据 → 解锁简历主张
       时间桶分为：半天/1天/3天/1周
       示例：[半天] 给RAG检索加10条query的eval set，记录recall@5 → 产出评估日志截图 → 解锁"具备RAG效果评估经验"
       每个时间桶至少给出1-2个具体可执行任务，禁止写"深入学习XX"等模糊建议
    4) 匹配度诊断收尾：列出各维度当前匹配百分比和补证据后预期百分比

【极度重要】：必须严格使用上述英文作为 JSON 的 Key。绝对禁止使用中文标题（如"核心能力词典"、"致命硬伤"、"破局行动计划"等）作为 Key，否则系统将崩溃！
"""

_DEEP_EVAL_SYSTEM_PROMPT = f"{_DEEP_EVAL_ROLE_PROMPT}\n\n{_DEEP_EVAL_BODY_FORMAT}"


# ==========================================
# 任务 4：第二阶段深度评估（双阶段漏斗架构）
# ==========================================
def deep_evaluate_resume(resume_text: str, jd_text: str, ai_result: dict = None) -> tuple:
    # 🌟 极简高能 Prompt 架构：剔除冗余偏好与初评分数，聚焦客观深度体检
    system_prompt = _DEEP_EVAL_SYSTEM_PROMPT
    _empty_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    _fallback = {
        "extracted_skills": [],
        "dream_picture": "深度评估失败",
        "ats_ability_analysis": "深度评估失败",
        "resume_audit": "深度评估失败",
        "strong_fit_assessment": "深度评估失败",
        "risk_red_flags": "深度评估失败",
        "deep_action_plan": "深度评估失败",
    }

    try:
        response = get_openai_client().chat.completions.create(
            model=settings.OPENAI_MODEL,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": (
                        f"【候选人全局不可变简历档案】:\n{resume_text}\n\n"
                        f"【目标岗位 JD】:\n{jd_text}\n\n"
                        f"请严格按照 System 规则，对上述候选人与目标岗位进行深度审计画像，仅输出纯净 JSON 对象。"
                    ),
                },
            ],
            temperature=0.2,
        )
        raw = response.choices[0].message.content.strip()
        usage = response.usage
        cached = 0
        if hasattr(usage, "prompt_tokens_details") and usage.prompt_tokens_details:
            cached = getattr(usage.prompt_tokens_details, "cached_tokens", 0) or 0
        elif isinstance(usage, dict):
            details = usage.get("prompt_tokens_details") or {}
            cached = details.get("cached_tokens", 0) if isinstance(details, dict) else 0
        usage_dict = {
            "prompt_tokens": getattr(usage, "prompt_tokens", 0),
            "completion_tokens": getattr(usage, "completion_tokens", 0),
            "total_tokens": getattr(usage, "total_tokens", 0),
            "cached_tokens": cached,
        } if usage else _empty_usage
        
        _prefix_json = "`" * 3 + "json"
        _suffix = "`" * 3
        if raw.startswith(_prefix_json): raw = raw[7:]
        elif raw.startswith(_suffix): raw = raw[3:]
        if raw.endswith(_suffix): raw = raw[:-3]
        raw = raw.strip()
        parsed = json.loads(raw)

        # ── Wave 2 深度画像白盒透视与独立 Token 终端打印 ──
        pt = usage_dict.get("prompt_tokens", 0)
        ct = usage_dict.get("completion_tokens", 0)
        tot = usage_dict.get("total_tokens", 0)
        cached_hint = f" (🔥命中缓存: {cached})" if cached > 0 else " (未命中缓存)"

        print("\n\033[95m" + "="*60 + "\033[0m")
        print("\033[95m🔬 [Wave 2 AI 深度画像白盒透视]\033[0m")
        dream = str(parsed.get("dream_picture", "") or "").strip()
        ats = str(parsed.get("ats_ability_analysis", "") or "").strip()
        flags = str(parsed.get("risk_red_flags", "") or "").strip()
        strong = str(parsed.get("strong_fit_assessment", "") or "").strip()
        plan = str(parsed.get("deep_action_plan", "") or "").strip()
        if dream:
            print(f"\033[96m🎯 [岗位理想画像]:\033[0m {dream[:150]}..." if len(dream) > 150 else f"\033[96m🎯 [岗位理想画像]:\033[0m {dream}")
        if ats:
            print(f"\033[93m🏷️ [ATS 必备词典]:\033[0m {ats[:150]}..." if len(ats) > 150 else f"\033[93m🏷️ [ATS 必备词典]:\033[0m {ats}")
        if flags:
            print(f"\033[91m🚩 [致命毒点预警]:\033[0m {flags[:150]}..." if len(flags) > 150 else f"\033[91m🚩 [致命毒点预警]:\033[0m {flags}")
        if strong:
            print(f"\033[92m⚡ [高杠杆匹配点]:\033[0m {strong[:150]}..." if len(strong) > 150 else f"\033[92m⚡ [高杠杆匹配点]:\033[0m {strong}")
        if plan:
            print(f"\033[94m🛠️ [破局行动计划]:\033[0m {plan[:150]}..." if len(plan) > 150 else f"\033[94m🛠️ [破局行动计划]:\033[0m {plan}")
        print(f"\033[95m📈 [Wave 2 深度画像] Token 消耗 → 提示: {pt}{cached_hint} / 补全: {ct} / 总计: {tot}\033[0m")
        print("\033[95m" + "="*60 + "\033[0m\n")

        return parsed, usage_dict
    except Exception as e:
        print(f"\n❌ [deep_evaluate_resume] API 调用失败: {e}")
        return _fallback, _empty_usage


def warmup_deep_eval_cache(resume_text: str) -> dict:
    """为批量深度画像执行 1-token 点火预热，将不可变母本简历前缀写入 GPU Prefix Cache (用于 N>=3 大批量)"""
    system_prompt = _DEEP_EVAL_SYSTEM_PROMPT
    user_prompt = (
        f"【候选人全局不可变简历档案】:\n{resume_text}\n\n"
        f"【目标岗位 JD】:\n预热占位\n\n"
        f"请严格按照 System 规则，对上述候选人与目标岗位进行深度审计画像，仅输出纯净 JSON 对象。"
    )
    try:
        response = get_openai_client().chat.completions.create(
            model=settings.OPENAI_MODEL,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=1,
            temperature=0.0,
        )
        usage = response.usage
        cached = 0
        if hasattr(usage, "prompt_tokens_details") and usage.prompt_tokens_details:
            cached = getattr(usage.prompt_tokens_details, "cached_tokens", 0) or 0
        elif isinstance(usage, dict):
            details = usage.get("prompt_tokens_details") or {}
            cached = details.get("cached_tokens", 0) if isinstance(details, dict) else 0
        return {
            "success": True,
            "prompt": getattr(usage, "prompt_tokens", 0) if usage else 0,
            "cached": cached,
        }
    except Exception as e:
        print(f"⚠️ [warmup_deep_eval_cache] 深度画像点火预热异常 (不影响主流程继续): {e}")
        return {"success": False, "error": str(e)}


# ==========================================
# 工具函数：Markdown 简历解析器
# ==========================================
def parse_resume_markdown(md_text: str) -> List[Dict]:
    md_text = re.sub(r'^```[a-z]*\n?', '', md_text, flags=re.MULTILINE)
    md_text = re.sub(r'\n?```$', '', md_text, flags=re.MULTILINE)
    md_text = md_text.strip()

    sections: List[Dict] = []
    current_title: str | None = None
    current_lines: List[str] = []

    for line in md_text.splitlines():
        if line.startswith("# "):
            if current_title is not None:
                sections.append({
                    "title": current_title,
                    "content": "\n".join(current_lines).strip(),
                })
            current_title = line[2:].strip()
            current_lines = []
        else:
            current_lines.append(line)

    if current_title is not None:
        sections.append({
            "title": current_title,
            "content": "\n".join(current_lines).strip(),
        })
    return sections


# ==========================================
# 工具函数：Tavily 公司情报搜索（带按归一化公司名的磁盘缓存）
# ==========================================
# 同公司多岗位（改名重发/多平台）共享一份情报：14 天内同公司只搜一次，省 API 调用
_TAVILY_CACHE_TTL = 14 * 86400
_TAVILY_CACHE_PATH = Path(__file__).resolve().parent.parent / "data" / "tavily_company_cache.json"
_tavily_cache_lock = threading.Lock()
_tavily_cache: dict = {}


def _load_tavily_cache() -> None:
    global _tavily_cache
    if _tavily_cache:
        return
    try:
        with open(_TAVILY_CACHE_PATH, encoding="utf-8") as f:
            _tavily_cache = json.load(f) or {}
    except Exception:
        _tavily_cache = {}


def _save_tavily_cache() -> None:
    try:
        tmp = f"{_TAVILY_CACHE_PATH}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_tavily_cache, f, ensure_ascii=False)
        os.replace(tmp, _TAVILY_CACHE_PATH)
    except Exception as e:
        print(f"   ⚠️ [Tavily] 缓存写盘失败: {e}")


def _tavily_cache_key(company_name: str) -> str:
    from job_processor.job_dedup import normalize_company
    return normalize_company(company_name) or str(company_name).strip().lower()


def _tavily_cache_lookup(key: str, now: float):
    """缓存命中：键相等，或一方包含另一方（≥4 字，与岗位去重的同公司口径一致）。

    兜住「华为」vs「华为技术」这类公司名变体——情报是公司级的，够用。
    """
    hit = _tavily_cache.get(key)
    if hit and now - float(hit.get("ts", 0)) < _TAVILY_CACHE_TTL and str(hit.get("intel", "")).startswith("【"):
        return hit
    if len(key) >= 4:
        for k, v in _tavily_cache.items():
            if not k or len(k) < 4 or k == key:
                continue
            if (key in k or k in key) and now - float(v.get("ts", 0)) < _TAVILY_CACHE_TTL \
                    and str(v.get("intel", "")).startswith("【"):
                return v
    return None


def search_company_info_tavily(company_name: str) -> str:
    if not company_name or "某" in company_name or company_name == "未知公司":
        return "⚠️ 匿名或未知公司，跳过外部背调"

    api_key = get_tavily_api_key()
    if not api_key:
        return "⚠️ 情报获取失败，降级评估（未配置 TAVILY_API_KEY）"

    # 缓存命中：同公司（归一化 + 包含匹配）14 天内直接复用
    cache_key = _tavily_cache_key(company_name)
    now = time.time()
    with _tavily_cache_lock:
        _load_tavily_cache()
        hit = _tavily_cache_lookup(cache_key, now)
        if hit:
            print(f"   📦 [Tavily] 命中公司情报缓存: {company_name}")
            return hit["intel"]

    try:
        url = "https://api.tavily.com/search"
        headers = {"Content-Type": "application/json"}
        payload = {
            "api_key": api_key,
            "query": f"{company_name} 公司介绍 核心业务 融资 规模",
            "search_depth": "basic",
            "include_answer": False
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=15, proxies={"http": None, "https": None})
        data = resp.json()

        snippets = []
        for item in data.get("results", [])[:5]:
            snippet = item.get("content", "").strip()
            if snippet:
                snippets.append(snippet)

        if not snippets:
            return "⚠️ 情报获取失败，降级评估"

        intel = f"【{company_name} 公司情报】\n" + "\n".join(f"· {s}" for s in snippets[:3])
        intel = intel[:600]

        # 只缓存成功结果（失败可能是网络抖动，不缓存以免长时间降级）
        with _tavily_cache_lock:
            _tavily_cache[cache_key] = {"intel": intel, "ts": now}
            _save_tavily_cache()
        return intel
    except Exception as e:
        print(f"   ❌ [Tavily] 请求异常: {type(e).__name__}: {e}")
        return f"⚠️ 情报获取失败，降级评估（{str(e)[:60]})"