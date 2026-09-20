#!/usr/bin/env python3
"""
AI 评估引擎 - 独立的岗位智能评估模块

功能：
1. 从飞书拉取所有"新线索"状态的岗位
2. 使用大模型进行深度评估（打分、画像分析、匹配度等）
3. 根据评级自动分流：
   - 评级达到配置阈值: 生成简历改写 + 打招呼语，状态设为"待人工复核"
   - 评级未达到配置阈值: 仅保存评估结果，状态设为"待人工评估"
4. 将评估结果回写到飞书多维表格总表
"""

import os
import sys
import json
import time
import random
import argparse
import requests # 🌟 新增 requests 用于拉取云端简历
# 🌟 引入 Python 结构化粗筛引擎（双保险）
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
from job_processor.structural_filter import StructuralFilterEngine
# 🌟 引入外部搜索函数
# 🌟 引入外部搜索函数
from .ai_scorer import deep_evaluate_resume, get_user_preferences
from app.core.feishu_utils import grade_meets_threshold
from .company_intel import fetch_company_intel  # 公司情报统一入口：Serper 主引擎 + Tavily 降级
from .engine_facade import process_resume_rewrite, process_greeting_generation
from app.core.feishu_utils import extract_feishu_text, get_tenant_access_token
from app.services.feishu_service import update_feishu_record, get_new_leads_from_feishu
from app.core.config import settings
from app.core.llm_client import get_openai_client

# 🌟 配置统一走 settings 动态读取：sync_settings_to_runtime() 会原地更新 settings 单例，
# 配置页保存后即时生效；不再在模块级冻结快照（旧快照会让 UI 配置永远读不到）

# 🌟 初始化结构化粗筛引擎（调用大模型前的双保险拦截）
_filter_engine = StructuralFilterEngine()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 🌟 修改 2：彻底重构简历读取逻辑，废弃本地 txt，拥抱飞书云端
def load_resume():
    """
    从飞书配置中心动态读取【启用】状态的简历内容
    
    Returns:
        str: 简历文本内容，失败返回 None
    """
    print("☁️ 正在从飞书云端寻找【启用】状态的简历...")
    try:
        token = get_tenant_access_token()
        if not token:
            print("❌ 获取飞书 Token 失败，无法读取云端简历")
            return None
            
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{settings.FEISHU_APP_TOKEN}/tables/{settings.FEISHU_TABLE_ID_RESUMES}/records/search"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        payload = {
            "filter": {
                "conjunction": "and",
                "conditions": [{"field_name": "当前状态", "operator": "is", "value": ["启用"]}]
            }
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=10, proxies={"http": None, "https": None})
        items = resp.json().get("data", {}).get("items", [])
        
        if items:
            import json
            raw_text = extract_feishu_text(items[0].get("fields", {}).get("结构化数据", ""))
            try:
                data_dict = json.loads(raw_text)
                data_dict.pop("personalInfo", None)
                resume_text = json.dumps(data_dict, ensure_ascii=False)
            except json.JSONDecodeError:
                resume_text = raw_text
                
            if resume_text.strip():
                print(f"✅ 云端简历读取成功，共 {len(resume_text)} 字符")
                return resume_text
            else:
                print("❌ 启用的简历内容为空！")
                return None
        else:
            print("❌ 未在飞书中找到处于【启用】状态的简历！请前往控制台设置。")
            return None
            
    except Exception as e:
        print(f"❌ 读取云端简历出错: {e}")
        return None

# 8维度 A-F 评估提示词（后端锁死格式约束）
_DIM_LABELS = [
    ("role_match",     "角色匹配"),
    ("skills_align",   "技能重合"),
    ("seniority",      "职级资历"),
    ("compensation",   "薪资契合"),
    ("interview_prob", "面试概率"),
    ("company_stage",  "公司阶段"),
    ("market_fit",     "赛道前景"),
    ("growth",         "成长空间"),
]


def _format_rationales_text(scores: dict, rationales: dict) -> str:
    """将8维度打分依据格式化为结构化 Markdown 长文本"""
    lines = []
    for key, label in _DIM_LABELS:
        score = scores.get(key, "?")
        reason = rationales.get(key, "")
        if reason:
            lines.append(f"**【{label}】** {score}/5\n{reason}")
    return "\n\n".join(lines)


_EVAL_FORMAT = """
【输出格式要求（最高优先级）】
必须、严格、仅输出一个纯净的 JSON 对象，不含任何 Markdown 代码块标记。
JSON 必须包含且仅包含以下字段：

- "grade": 字符串，综合评级，必须是 A/B/C/D/F 之一（A=顶级匹配，B=良好，C=一般，D=较差，F=完全不匹配）
  🚫 严禁基于猜测判定 F 或 D。信息不足时按中性处理，不得主动扣分。

- "scores": JSON 对象，包含以下 8 个键，每个值为 1-5 的整数：
    【评分校准基准】3分=信息缺失或中性；4分=JD 中有明确正面证据；5分=远超预期且高度契合候选人目标，极为罕见
    "role_match"（核心：角色与目标岗位匹配程度，对口行业经验加分），
    "skills_align"（核心：技能重合度，对比硬技能要求），
    "seniority"（高权：职级资历匹配，重点看项目复杂度、独立带盘子能力及管理经验是否匹配，严禁因无大厂经验盲目打低分），
    "compensation"（高权：薪资期望契合度），
    "interview_prob"（高权：面试通过概率），
    "company_stage"（公司发展阶段契合度），
    "market_fit"（中权：赛道市场前景），
    "growth"（中权：个人成长空间）

  ⚠️【薪资与城市强制读取规则 - 必须执行】：传入文本包含【岗位基本信息】和【岗位详情】两个区块。在评估 "compensation" 等维度时，必须优先读取【岗位基本信息】中明确标出的薪资范围（如 15-25k），绝对禁止回答"未披露"！若【岗位基本信息】已有薪资数据，则 compensation 必须基于该数据打分，不得给出中性 3 分。

  ⚠️【外部情报强制读取规则 - 必须执行】：在评估 "company_stage"（公司阶段）、"market_fit"（赛道前景）和 "growth" 时，必须优先参考【公司外部情报（来自网络搜索）】给出的融资历程、规模、主营业务等数据作为打分依据。

  ⚠️【中性维度强制规则 - 必须执行】："company_stage" 维度采用【中性/奖励】逻辑：
    - 默认给 3 分，除非搜索出来有明确正面证据（如"A 轮融资后高速增长期"等）才可给 4-5 分。
    - 绝对禁止给出 1-2 分。若信息缺失或无法判断，必须给 3 分，严禁基于猜测扣分。

  ⚠️【能力溢出（Overqualified）满分规则 - 必须执行】：如果候选人的学历、经验、技能或资历**超出（Overqualified）**岗位的要求，**绝对禁止打低分**。只要满足或高于岗位要求，就应视为完全匹配，直接给予 5 分满分。只有在候选人能力**不足**或**低于**岗位要求时，才允许打低分。

- "score_rationales": JSON 对象，与 scores 包含相同的 8 个键，每个值为该维度的打分依据（严格限 1 句话，必须直接引用 JD、情报或简历中的具体信息作为证据，严禁废话和主观猜测）
"""

# 采用「中性/奖励」逻辑的维度（信息缺失时默认 3 分，不扣分）
_NEUTRAL_DIMS = ("company_stage",)

def get_dynamic_weights() -> dict:
    import sqlite3
    import os
    db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "job_hunter.db")
    # 默认权重
    weights = {
        "role_match":     1.0,
        "skills_align":   1.0,
        "seniority":      0.8,
        "interview_prob": 0.8,
        "compensation":   0.8,
        "market_fit":     0.5,
        "growth":         0.5,
        "company_stage":  0.2,
    }
    if not os.path.exists(db_path):
        return weights
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='evaluation_weights'")
        if not cursor.fetchone():
            return weights
        cursor.execute("SELECT dimension, weight FROM evaluation_weights")
        rows = cursor.fetchall()
        for r in rows:
            if r[0] in weights:
                weights[r[0]] = float(r[1])
        conn.close()
    except Exception as e:
        print(f"⚠️ 读取权重配置失败: {e}")
    return weights

def get_auto_eval_threshold() -> str:
    import sqlite3
    import os
    db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "job_hunter.db")
    if not os.path.exists(db_path):
        return "A"
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT rule FROM job_preferences WHERE type='自动化阈值' AND status='启用' LIMIT 1")
        row = cursor.fetchone()
        conn.close()
        if row and row[0]:
            return row[0].strip().upper()
    except Exception as e:
        print(f"⚠️ 读取自动化阈值失败: {e}")
    return "A"

# 采用「中性/奖励」逻辑的维度（信息缺失时默认 3 分，不扣分）
_NEUTRAL_DIMS = ("company_stage",)


def _call_10dim_evaluation(resume_text: str, jd_text: str, company_intel: str = "", preferences_text: str = "") -> dict:
    """直接调用大模型，返回 8 维度 A-F 评估结果 dict，支持注入公司情报与个人偏好"""
    soul_prompt = "你是一名顶级猎头与职业规划专家，请对候选人与目标岗位的匹配度进行专家级深度评估。"
    system_prompt = f"{soul_prompt}\n\n{_EVAL_FORMAT}"

    # 🌟 KV Cache 前缀对齐：将全量不可变母本经历档案与底线偏好前置，岗位 JD 与情报后置
    parts = [
        f"【候选人全局不可变简历档案】\n{resume_text}",
    ]
    if preferences_text:
        parts.append(f"【候选人求职偏好与绝对底线】\n{preferences_text}")
    parts.append(f"【目标岗位 JD】\n{jd_text}")
    if company_intel and not company_intel.startswith("⚠️"):
        parts.append(f"【公司外部情报（来自网络搜索）】\n{company_intel}")
    parts.append("请严格按照 System 规则对上述候选人与目标岗位进行 8 维度客观深度评估，输出标准 JSON。")
    user_prompt = "\n\n".join(parts)

    _SCORE_KEYS = ["role_match","skills_align","seniority","compensation",
                   "interview_prob","company_stage","market_fit","growth"]
    _empty_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    try:
        response = get_openai_client().chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
        )
        raw = (response.choices[0].message.content or "").strip()
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
        _prefix_json = "```json"
        _suffix = "```"
        if raw.startswith(_prefix_json):
            raw = raw[7:]
        elif raw.startswith(_suffix):
            raw = raw[3:]
        if raw.endswith(_suffix):
            raw = raw[:-3]
        raw = raw.strip()
        try:
            return json.loads(raw), usage_dict
        except json.JSONDecodeError:
            print(f"⚠️ 8维评估解析失败，原始文本:\n{raw}")
            return {
                "grade": "F",
                "scores": {k: 1 for k in _SCORE_KEYS},
                "score_rationales": {k: "AI解析失败" for k in _SCORE_KEYS},
            }, usage_dict
    except Exception as e:
        print(f"\n❌ [_call_10dim_evaluation] API 调用失败，完整错误详情：")
        print(f"错误类型: {type(e).__name__}")
        print(f"错误内容: {e}")
        import traceback
        traceback.print_exc()
        return {
            "grade": "F",
            "scores": {k: 1 for k in _SCORE_KEYS},
            "score_rationales": {k: "AI解析失败" for k in _SCORE_KEYS},
        }, _empty_usage


def warmup_eval_cache(resume_text: str, preferences_text: str = "") -> dict:
    """为批量初评执行 1-token 点火预热，将不可变母本简历与偏好前缀写入 GPU Prefix Cache (用于 N>=3 大批量)"""
    soul_prompt = "你是一名顶级猎头与职业规划专家，请对候选人与目标岗位的匹配度进行专家级深度评估。"
    system_prompt = f"{soul_prompt}\n\n{_EVAL_FORMAT}"
    parts = [
        f"【候选人全局不可变简历档案】\n{resume_text}",
    ]
    if preferences_text:
        parts.append(f"【候选人求职偏好与绝对底线】\n{preferences_text}")
    parts.append("【目标岗位 JD】\n预热占位")
    parts.append("请严格按照 System 规则对上述候选人与目标岗位进行 8 维度客观深度评估，输出标准 JSON。")
    user_prompt = "\n\n".join(parts)

    try:
        response = get_openai_client().chat.completions.create(
            model=settings.OPENAI_MODEL,
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
        print(f"⚠️ [warmup_eval_cache] 点火预热异常 (不影响主流程继续): {e}")
        return {"success": False, "error": str(e)}


def evaluate_single_job(job_data, resume_text, company_intel: str = "", preferences_text: str = "", task_mode: str = "auto", progress_callback=None):
    """
    评估单个岗位（8维度 A-F 架构），支持注入公司情报与个人偏好底线
    """
    record_id = job_data.get("record_id")
    company = job_data.get("company", "未知公司")
    job_title = job_data.get("job_title", "未知岗位")
    platform = job_data.get("platform", "未知渠道")
    jd_text = job_data.get("jd_text", "")
    salary = job_data.get("salary", "未知")
    city = job_data.get("city", "未知")
    experience = job_data.get("experience", "未知")
    education = job_data.get("education", "未知")

    def _report_progress(stage: int, total_stages: int, title: str, message: str):
        if progress_callback and callable(progress_callback):
            try:
                progress_callback({
                    "stage": stage,
                    "total_stages": total_stages,
                    "title": title,
                    "message": message,
                    "job_id": record_id,
                })
            except Exception:
                pass

    # 组装全景 JD 上下文（让 LLM 看到所有基础字段）
    full_jd_info = (
        f"【岗位基本信息】\n"
        f"薪资范围: {salary} | 工作城市: {city} | 经验要求: {experience} | 学历要求: {education}\n\n"
        f"【岗位详情】\n{jd_text}"
    )

    print(f"\n{'='*60}")
    print(f"📋 正在评估: [{platform}] {company} - {job_title}")
    print(f"🆔 Record ID: {record_id}")
    print(f"💰 薪资: {salary} | 📍 城市: {city} | 📚 学历: {education} | 🏷️ 经验: {experience}")

    try:
        # 步骤 0: Python 结构化粗筛（双保险拦截，避免浪费 LLM 调用）
        is_garbage, reason = _filter_engine.is_obvious_garbage(
            job_title=job_title, experience_req=experience, education_req=education
        )
        if is_garbage:
            print(f"   🛑 [Python粗筛拦截] 命中规则: {reason}")
            _report_progress(1, 1, "粗筛淘汰", f"🛑 [Python粗筛拦截] 命中规则: {reason}")
            return {
                "success": True,
                "record_id": record_id,
                "update_data": {
                    "跟进状态": "清洗淘汰",
                    "综合评级 (A-F)": "F",
                    "核心-角色匹配": 0,
                    "核心-技能重合": 0,
                    "高权-职级资历": 0,
                    "高权-薪资契合": 0,
                    "高权-面试概率": 0,
                    "中权-公司阶段": 0,
                    "中权-赛道前景": 0,
                    "中权-成长空间": 0,
                },
                "ai_score": 0,
                "grade": "F",
                "status": "清洗淘汰",
            }

        # 步骤 0.5: 动态获取公司外部情报（Serper 多维联网背调探针，Tavily 降级备用）
        if not company_intel or company_intel.startswith("⚠️"):
            try:
                from app.automation.db import get_autopilot_config
                enable_search = bool(get_autopilot_config().get("enable_company_search", True))
            except Exception:
                enable_search = True

            if enable_search and company and company != "未知公司" and "某" not in company:
                print(f"   📡 正在抓取公司外部情报: {company}...")
                _report_progress(1, 4, "背调情报中", f"📡 正在抓取公司外部情报: {company}...")
                fetched_intel = fetch_company_intel(company)
                if fetched_intel:
                    company_intel = fetched_intel

        # 步骤 1: 8维度大模型评估（注入公司情报 + 个人偏好）
        intel_label = "有情报" if company_intel and not company_intel.startswith("⚠️") else "无情报"
        pref_label = "有偏好" if preferences_text else "无偏好"
        _report_progress(1, 4, "8维度初评中", f"🧠 [1/4] 正在呼叫 AI 进行 8维度深度评估... [{intel_label} | {pref_label}]")
        print(f"   🧠 [1/4] 正在呼叫 AI 进行 8维度深度评估... [{intel_label} | {pref_label}]")
        ai_result, eval_usage = _call_10dim_evaluation(resume_text, full_jd_info, company_intel, preferences_text)

        # 初始化 Token 累计器
        total_usage = {
            "prompt_tokens": eval_usage.get("prompt_tokens", 0),
            "completion_tokens": eval_usage.get("completion_tokens", 0),
            "total_tokens": eval_usage.get("total_tokens", 0),
            "cached_tokens": eval_usage.get("cached_tokens", 0),
        }

        grade = ai_result.get("grade", "F")
        scores = ai_result.get("scores", {})
        rationales = ai_result.get("score_rationales", {})
        try:
            rationales_text = _format_rationales_text(scores, rationales)
        except Exception:
            rationales_text = ""

        # 强制纠偏：中性维度不得低于 3（仅加分不扣分策略）
        _clamped_count = 0
        for k in _NEUTRAL_DIMS:
            if int(scores.get(k, 3)) < 3:
                scores[k] = 3
                _clamped_count += 1
        if _clamped_count:
            print(f"   🔧 [纠偏] {_clamped_count} 个中性维度低于3分，已强制修正为3分")

        # 获取动态权重
        current_weights = get_dynamic_weights()

        # 加权总分计算
        weighted_sum = sum(int(scores.get(k, 1)) * current_weights.get(k, 1.0) for k in current_weights)
        max_weighted = sum(5 * current_weights.get(k, 1.0) for k in current_weights)
        raw_total = sum(int(scores.get(k, 1)) for k in current_weights)
        ai_total = int(weighted_sum / max_weighted * 100)
        raw_pct = int(raw_total / 40 * 100)
        
        print(f"\n   ---------------- [AI 诊断白盒透视] ----------------")
        print(f"   {rationales_text}")
        print(f"   -------------------------------------------------")
        print(f"   📊 [2/3] 第一阶段诊断完毕！评级: {grade}，加权总分: {ai_total}分（等权参考: {raw_pct}分）")
        _report_progress(2, 4, f"初评完成 ({ai_total}分/{grade}级)", f"📊 [2/4] 第一阶段诊断完毕！评级: {grade}，加权总分: {ai_total}分")

        # ── 第一阶段 update_data：仅写入 12 个已确认的安全字段 ──
        target_status = ""
        update_data = {
            "综合评级 (A-F)": grade,
            "AI评估详情": rationales_text,
            "核心-角色匹配": int(scores.get("role_match", 0)),
            "核心-技能重合": int(scores.get("skills_align", 0)),
            "高权-职级资历": int(scores.get("seniority", 0)),
            "高权-薪资契合": int(scores.get("compensation", 0)),
            "高权-面试概率": int(scores.get("interview_prob", 0)),
            "中权-公司阶段": int(scores.get("company_stage", 0)),
            "中权-赛道前景": int(scores.get("market_fit", 0)),
            "中权-成长空间": int(scores.get("growth", 0)),
            "跟进状态": "已完成初步评估",  # 占位，高分轨会覆盖
        }
        if company_intel and not company_intel.startswith("⚠️"):
            update_data["公司业务情报"] = company_intel

        # ── 步骤 2: 高分轨/低分轨分流 ──
        threshold = get_auto_eval_threshold()
        trigger_deep_eval = False
        
        if task_mode == "eval_only":
            print(f"   🌊 [初评模式] 单岗位 8 维初评完毕: {grade}级 ({ai_total}分)，交由流水线漏斗统一门禁分流")
        else:
            trigger_deep_eval = grade_meets_threshold(grade, threshold)

            if trigger_deep_eval:
                print(f"   🔥 [3/3] 触发【高分轨】(当前配置: {threshold}级及以上触发)！正在自动进行深度评估与简历定制...")
                _report_progress(3, 4, "高分轨·画像与定制简历", f"🔥 [3/4] 触发【高分轨】({threshold}级及以上)！正在自动进行深度画像与简历定制 (预估30s)...")

                deep_result, deep_usage = deep_evaluate_resume(resume_text, full_jd_info, ai_result)
                total_usage["prompt_tokens"] += deep_usage.get("prompt_tokens", 0)
                total_usage["completion_tokens"] += deep_usage.get("completion_tokens", 0)
                total_usage["total_tokens"] += deep_usage.get("total_tokens", 0)
                total_usage["cached_tokens"] += deep_usage.get("cached_tokens", 0)

                extracted_skills = deep_result.get("extracted_skills", [])
                skills_str = "、".join(extracted_skills) if extracted_skills else ""
                ats_base = deep_result.get("ats_ability_analysis", "")
                ats_final = deep_result.get("ats_ability_analysis", "")

                update_data["理想画像与能力信号"] = deep_result.get("dream_picture", "")
                update_data["核心能力词典"] = ats_final
                update_data["简历逐行审计"] = deep_result.get("resume_audit", "")
                update_data["高杠杆匹配点"] = deep_result.get("strong_fit_assessment", "")
                update_data["致命硬伤与毒点"] = deep_result.get("risk_red_flags", "")
                update_data["破局行动计划"] = deep_result.get("deep_action_plan", "")

                # 动态判断是多Agent还是Skill模式
                current_mode = "multi" if "multi" in task_mode else "skill"
                print(f"[{job_title}] -> 开始通过 Engine Facade 进行 {current_mode.upper()} 模式简历定制改写...")
                
                rewrite_result, rewrite_usage = process_resume_rewrite(
                    jd_text=full_jd_info, 
                    diagnosis_dict=deep_result, 
                    job_name=job_title, 
                    rewrite_mode=current_mode
                )
                total_usage["prompt_tokens"] += rewrite_usage.get("prompt_tokens", 0)
                total_usage["completion_tokens"] += rewrite_usage.get("completion_tokens", 0)
                total_usage["total_tokens"] += rewrite_usage.get("total_tokens", 0)
                total_usage["cached_tokens"] += rewrite_usage.get("cached_tokens", 0)
                from ai_agents.markdown_to_json import convert_and_stitch_resume
                update_data["AI改写JSON"] = convert_and_stitch_resume(rewrite_result)

                from app.core.utils import is_greeting_supported_platform
                target_platform = platform or job_data.get("platform", "未知渠道")
                if is_greeting_supported_platform(target_platform):
                    _report_progress(4, 4, "高分轨·打招呼语", "💬 [4/4] 正在构思高情商打招呼语...")
                    greeting_result, greeting_usage = process_greeting_generation(full_jd_info, deep_result, resume_text, job_title)
                    total_usage["prompt_tokens"] += greeting_usage.get("prompt_tokens", 0)
                    total_usage["completion_tokens"] += greeting_usage.get("completion_tokens", 0)
                    total_usage["total_tokens"] += greeting_usage.get("total_tokens", 0)
                    total_usage["cached_tokens"] += greeting_usage.get("cached_tokens", 0)
                    update_data["打招呼语"] = greeting_result
                else:
                    print(f"   ℹ️ [{target_platform}] 不支持微聊打招呼外发，跳过打招呼语生成并显式置空")
                    _report_progress(4, 4, "初评归档", f"ℹ️ [{target_platform}] 纯附件投递平台，跳过打招呼语生成")
                    update_data["打招呼语"] = ""

                update_data["跟进状态"] = "简历人工复核"
                target_status = "简历人工复核"
            else:
                print(f"   ⏸️ [3/3] 触发【低分轨】({grade}级，{ai_total}分)，未达到高分门槛({threshold}级)，跳过深度评估")
                _report_progress(4, 4, "初评归档", f"⏸️ [3/3] 触发【低分轨】({grade}级，{ai_total}分)，已完成初步评估")
                update_data["跟进状态"] = "已完成初步评估"
                target_status = "已完成初步评估"

        cached_cnt = total_usage.get("cached_tokens", 0)
        cached_hint = f" (🔥命中缓存: {cached_cnt})" if cached_cnt > 0 else ""
        print(f"   📈 Token 消耗 → 提示: {total_usage['prompt_tokens']}{cached_hint} / 补全: {total_usage['completion_tokens']} / 总计: {total_usage['total_tokens']}")
        return {
            "success": True,
            "record_id": record_id,
            "update_data": update_data,
            "ai_score": ai_total,
            "grade": grade,
            "status": target_status,
            "usage": total_usage,
            "rationales_text": rationales_text,
            "company_intel": company_intel if company_intel and not company_intel.startswith("⚠️") else "",
        }

    except Exception as e:
        print(f"   ❌ 评估过程出错: {e}")
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "record_id": record_id,
            "error": str(e)
        }

def run_smart_evaluation(target_records=None, task_mode="auto"):
    """统一智能评估入口。
    - 不传 target_records → 走原有 get_new_leads_from_feishu() 全量拉【新线索】兜底
    - 传入 target_records → 来自 main.py ChatOps 定向筛选的原始飞书 items（含 record_id + fields），
      内部归一化为 job_data 字典再喂给 evaluate_single_job
    返回包含 total / platforms / grades / manual_review 四维度的 stats 统计字典。
    """
    print("🚀 启动 AI 评估引擎...\n")
    print(f"🎛️ [任务模式] task_mode = {task_mode}")

    # 🌟 白盒统计探针
    stats = {
        "total": 0,
        "platforms": {},
        "grades": {"A": 0, "B": 0, "C": 0, "D": 0, "F": 0},
        "manual_review": 0,
        "details": [],
    }

    resume_text = load_resume()
    if not resume_text:
        print("❌ 无法读取云端简历，评估任务终止")
        return stats

    # 🌟 一次性拉取飞书偏好底线，全批次共享（避免 N 次飞书往返）
    user_preferences = get_user_preferences()
    if user_preferences:
        print(f"🛡️ 已加载用户求职偏好底线（{len(user_preferences)} 字符），将注入 8 维度评估 Prompt")
    else:
        print("ℹ️ 未检测到用户偏好底线，本次评估走通用规则")

    # 数据源分发：ChatOps 路径走传入参数，独立运行走飞书拉取
    if target_records is not None:
        print(f"📦 收到 ChatOps 定向投递的 {len(target_records)} 条原始飞书记录，开始归一化...")
        leads = []
        for r in target_records:
            fields = r.get("fields", {}) or {}
            leads.append({
                "record_id": r.get("record_id"),
                "company": extract_feishu_text(fields.get("公司名称", "")) or "未知公司",
                "job_title": extract_feishu_text(fields.get("岗位名称", "")) or "未知岗位",
                "jd_text": extract_feishu_text(fields.get("岗位详情", "")),
                "salary": extract_feishu_text(fields.get("薪资", "")) or "未知",
                "city": extract_feishu_text(fields.get("城市", "")) or "未知",
                "experience": extract_feishu_text(fields.get("经验要求", "")) or "未知",
                "education": extract_feishu_text(fields.get("学历要求", "")) or "未知",
                "platform": extract_feishu_text(fields.get("招聘平台", "")) or "未知渠道",
                # 保留原始 fields 引用，方便白盒探针读取真实「招聘平台」
                "_raw_fields": fields,
            })
    else:
        print("\n📡 正在从飞书总表拉取【新线索】状态的岗位...")
        print("="*60)
        leads = get_new_leads_from_feishu()
        print("="*60)

    if not leads:
        print("✅ 没有待评估的目标岗位，任务完成！")
        return stats

    print(f"✅ 成功载入 {len(leads)} 个待评估岗位\n")
    print("="*60)

    success_count = 0
    fail_count = 0

    for idx, job_data in enumerate(leads):
        print(f"\n进度: [{idx+1}/{len(leads)}]")

        # 🚀 在调用评估前，先调用外部 API 抓取情报
        company_name = job_data.get("company", "")
        company_intel = ""
        if company_name and company_name != "未知公司":
            print(f"📡 正在抓取公司外部情报: {company_name}...")
            company_intel = fetch_company_intel(company_name)

        # 🚀 根据任务模式进行物理分流
        if task_mode.startswith("rewrite"):
            job_title = job_data.get("job_title", "未知")
            print(f"🎯 [强制改写模式] 正在为 {job_data.get('company', '未知')} - {job_title} 执行深度改写...")

            # Step 1：组装完整 JD 信息（与 deep_evaluate 分支保持一致）
            full_jd_info = (
                f"公司: {job_data.get('company', '未知')}\n"
                f"岗位: {job_title}\n"
                f"城市: {job_data.get('city', '未知')}\n"
                f"薪资: {job_data.get('salary', '未知')}\n"
                f"经验要求: {job_data.get('experience', '未知')}\n"
                f"学历要求: {job_data.get('education', '未知')}\n"
                f"岗位详情:\n{job_data.get('jd_text', '无')}"
            )
            if company_intel and not company_intel.startswith("⚠️"):
                full_jd_info += f"\n\n公司外部情报:\n{company_intel}"

            # Step 2：获取诊断报告作为改写的上下文依据（优先从飞书读取历史数据，省去 Token 开销）
            raw_fields = job_data.get("_raw_fields", {}) or {}
            existing_ats = extract_feishu_text(raw_fields.get("核心能力词典", ""))
            
            if existing_ats:
                print("   🔍 检测到飞书已存在深度评估结果，直接复用其作为改写上下文...")
                deep_result = {
                    "dream_picture": extract_feishu_text(raw_fields.get("理想画像与能力信号", "")),
                    "ats_ability_analysis": existing_ats,
                    "resume_audit": extract_feishu_text(raw_fields.get("简历逐行审计", "")),
                    "strong_fit_assessment": extract_feishu_text(raw_fields.get("高杠杆匹配点", "")),
                    "risk_red_flags": extract_feishu_text(raw_fields.get("致命硬伤与毒点", "")),
                    "deep_action_plan": extract_feishu_text(raw_fields.get("破局行动计划", ""))
                }
            else:
                print("   🧠 未检测到深度评估数据，正在临时呼叫 AI 补齐诊断报告...")
                try:
                    deep_result, _ = deep_evaluate_resume(resume_text, full_jd_info, ai_result={})
                except Exception as deep_err:
                    print(f"   ❌ 改写前的深度诊断调用失败: {deep_err}")
                    fail_count += 1
                    if idx < len(leads) - 1:
                        time.sleep(random.randint(3, 8))
                    continue

            # Step 3：用诊断报告驱动简历改写
            current_mode = "multi" if "multi" in task_mode else "skill"
            print(f"[{job_title}] -> 开始通过 Engine Facade 进行 {current_mode.upper()} 模式简历定制改写...")
            
            rewrite_res, _ = process_resume_rewrite(
                jd_text=full_jd_info, 
                diagnosis_dict=deep_result, 
                job_name=job_title, 
                rewrite_mode=current_mode
            )

            raw_fields = job_data.get("_raw_fields", {}) or {}
            platform = (
                extract_feishu_text(raw_fields.get("招聘平台", ""))
                or job_data.get("platform")
                or "未知渠道"
            )
            from app.core.utils import is_greeting_supported_platform
            if is_greeting_supported_platform(platform):
                # Step 4：生成打招呼语
                greeting_res, _ = process_greeting_generation(full_jd_info, deep_result, resume_text, job_title)
                greeting_val = str(greeting_res)
            else:
                greeting_val = ""
            
            # 如果大模型返回的是字典，必须用 dumps 转为带双引号的合法 JSON，否则转为纯字符串
            final_rewrite = json.dumps(rewrite_res, ensure_ascii=False) if isinstance(rewrite_res, dict) else str(rewrite_res)
            from ai_agents.markdown_to_json import convert_and_stitch_resume
            stitched_json_str = convert_and_stitch_resume(rewrite_res)

            # 直接组装回写数据
            update_data = {
                "AI改写JSON": stitched_json_str,
                "打招呼语": greeting_val,
                "跟进状态": "简历人工复核"  # 直接推送到人工复核状态
            }
            record_id = job_data.get("record_id")
            is_updated = update_feishu_record(record_id, update_data)

            # 强制记录统计
            stats["total"] += 1
            stats["manual_review"] += 1
            stats["platforms"][platform] = stats["platforms"].get(platform, 0) + 1

            if is_updated:
                print(f"   ✅ 强制改写成功并已推入人工复核！")
                success_count += 1
            else:
                print(f"   ❌ 强制改写回写飞书失败")
                fail_count += 1

            if idx < len(leads) - 1:
                sleep_time = random.randint(3, 8)
                print(f"   ⏳ 等待 {sleep_time} 秒后处理下一个岗位...")
                time.sleep(sleep_time)
            continue  # 跳过下方的常规 evaluate_single_job

        elif task_mode == "deep_evaluate":
            print(f"🔬 [深度评估模式] 正在为 {job_data['company']} - {job_data['job_title']} 执行深度评估...")

            # 组装完整 JD 信息
            full_jd_info = (
                f"公司: {job_data.get('company', '未知')}\n"
                f"岗位: {job_data.get('job_title', '未知')}\n"
                f"城市: {job_data.get('city', '未知')}\n"
                f"薪资: {job_data.get('salary', '未知')}\n"
                f"经验要求: {job_data.get('experience', '未知')}\n"
                f"学历要求: {job_data.get('education', '未知')}\n"
                f"岗位详情:\n{job_data.get('jd_text', '无')}"
            )
            if company_intel and not company_intel.startswith("⚠️"):
                full_jd_info += f"\n\n公司外部情报:\n{company_intel}"

            # 调用 ai_scorer 深度评估（传空 dict 作为 first_stage_scores）
            try:
                deep_result, deep_usage = deep_evaluate_resume(resume_text, full_jd_info, ai_result={})
            except Exception as deep_err:
                print(f"   ❌ 深度评估调用失败: {deep_err}")
                fail_count += 1
                if idx < len(leads) - 1:
                    time.sleep(random.randint(3, 8))
                continue

            # 组装回写数据（Key 严格对齐飞书真实列名）
            record_id = job_data.get("record_id")
            skills_str = "、".join(deep_result.get("extracted_skills", []))
            ats_base = deep_result.get("ats_ability_analysis", "")
            ats_final = ats_base

            update_data = {
                "理想画像与能力信号": deep_result.get("dream_picture", ""),
                "核心能力词典": ats_final,
                "简历逐行审计": deep_result.get("resume_audit", ""),
                "高杠杆匹配点": deep_result.get("strong_fit_assessment", ""),
                "致命硬伤与毒点": deep_result.get("risk_red_flags", ""),
                "破局行动计划": deep_result.get("deep_action_plan", ""),
                "跟进状态": "已完成深度评估",
            }
            is_updated = update_feishu_record(record_id, update_data)

            # 统计探针
            stats["total"] += 1
            raw_fields = job_data.get("_raw_fields", {}) or {}
            platform = (
                extract_feishu_text(raw_fields.get("招聘平台", ""))
                or job_data.get("platform")
                or "未知渠道"
            )
            stats["platforms"][platform] = stats["platforms"].get(platform, 0) + 1

            if is_updated:
                print(f"   ✅ 深度评估完成并已回写飞书！")
                success_count += 1
            else:
                print(f"   ❌ 深度评估回写飞书失败")
                fail_count += 1

            if idx < len(leads) - 1:
                sleep_time = random.randint(3, 8)
                print(f"   ⏳ 等待 {sleep_time} 秒后处理下一个岗位...")
                time.sleep(sleep_time)
            continue  # 跳过下方的常规 evaluate_single_job

        # ⬇️ 常规评估逻辑 (处理 auto 和 evaluate 模式)
        result = evaluate_single_job(
            job_data,
            resume_text,
            company_intel=company_intel,
            preferences_text=user_preferences,
            task_mode=task_mode,
        )

        if result.get("success"):
            print(f"   📤 正在将评估结果回写到飞书...")
            is_updated = update_feishu_record(
                result["record_id"],
                result["update_data"]
            )

            if is_updated:
                print(f"   ✅ 成功更新飞书记录！状态: {result['status']}, 得分: {result['ai_score']}")
                success_count += 1
            else:
                print(f"   ❌ 飞书回写失败")
                fail_count += 1

            # 🌟 白盒统计探针：无论回写是否成功，评估行为本身已发生
            stats["total"] += 1

            # 平台分布：优先读 ChatOps 投递的原始 fields，回退到归一化字段
            raw_fields = job_data.get("_raw_fields", {}) or {}
            platform_label = (
                extract_feishu_text(raw_fields.get("招聘平台", ""))
                or job_data.get("platform")
                or "未知渠道"
            )
            stats["platforms"][platform_label] = stats["platforms"].get(platform_label, 0) + 1

            # 等级归类：分数仅作为白盒展示，不再参与任何等级/通道判定。
            try:
                score = int(result.get("ai_score") or 0)
            except (TypeError, ValueError):
                score = 0
            result_grade = str(result.get("grade") or "F").strip().upper()
            stats["grades"][result_grade if result_grade in stats["grades"] else "F"] += 1

            # 人工复核计数
            status_label = str(result.get("status") or "")
            if "人工复核" in status_label or "待人工复核" in status_label:
                stats["manual_review"] += 1
                
            # 🌟 核心修复：收集成功的岗位明细，喂给 main.py 生成飞书卡片
            stats["details"].append({
                "company": job_data.get("company", "未知"),
                "title": job_data.get("job_title", "未知"),
                "score": score,
                "status": status_label
            })
            
        else:
            print(f"   ❌ 评估失败: {result.get('error', '未知错误')}")
            fail_count += 1
            
            # 🌟 核心修复：收集失败的岗位明细
            stats["details"].append({
                "company": job_data.get("company", "未知"),
                "title": job_data.get("job_title", "未知"),
                "error": result.get("error", "未知错误"),
                "status": "评估失败"
            })

        if idx < len(leads) - 1:
            sleep_time = random.randint(3, 8)
            print(f"   ⏳ 等待 {sleep_time} 秒后处理下一个岗位...")
            time.sleep(sleep_time)

    print("\n" + "="*60)
    print("🏁 智能评估任务完成！")
    print("="*60)
    print(f"📊 评估统计:")
    print(f"   - 总计岗位: {len(leads)}")
    print(f"   - 成功评估: {success_count}")
    print(f"   - 失败跳过: {fail_count}")
    print(f"   - 人工复核轨: {stats['manual_review']}")
    print(f"   - 等级分布: {stats['grades']}")
    print(f"   - 平台分布: {stats['platforms']}")
    print("="*60)

    return stats


# 🔒 向后兼容别名：旧调用方仍可继续使用 run_batch_evaluation
run_batch_evaluation = run_smart_evaluation

def run_single_job_evaluation(record_id, table_id=None):
    """处理单个岗位的评估"""
    print(f"\n{'='*60}")
    print(f"🌟 [单岗位模式] 开始处理 Record ID: {record_id}")
    print(f"{'='*60}")
    
    resume_text = load_resume()
    if not resume_text:
        return
    
    try:
        token = get_tenant_access_token()
        if not token:
            print("❌ 飞书鉴权失败")
            return
        
        import requests
        target_table_id = settings.FEISHU_TABLE_ID_JOBS
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{settings.FEISHU_APP_TOKEN}/tables/{target_table_id}/records/{record_id}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        response = requests.get(url, headers=headers, timeout=15, proxies={"http": None, "https": None})
        data = response.json()
        
        if data.get("code") != 0:
            print(f"❌ 拉取记录失败: {data.get('msg')}")
            return
        
        record = data.get("data", {}).get("record", {})
        fields = record.get("fields", {})
        
        job_data = {
            "record_id": record_id,
            "company": extract_feishu_text(fields.get("公司名称", "")) or "未知公司",
            "job_title": extract_feishu_text(fields.get("岗位名称", "")) or "未知岗位",
            "jd_text": extract_feishu_text(fields.get("岗位详情", "")),
            "salary": extract_feishu_text(fields.get("薪资", "")) or "未知",
            "city": extract_feishu_text(fields.get("城市", "")) or "未知",
            "experience": extract_feishu_text(fields.get("经验要求", "")) or "未知",
            "education": extract_feishu_text(fields.get("学历要求", "")) or "未知",
        }
        
        print(f"✅ 成功拉取岗位: {job_data['company']} - {job_data['job_title']}")
        
    except Exception as e:
        print(f"❌ 拉取岗位数据失败: {e}")
        return
    
    # 🚀 新增：在调用评估前，先调用外部 API 抓取情报
    company_name = job_data.get("company", "")
    company_intel = ""
    if company_name and company_name != "未知公司":
        print(f"📡 正在抓取公司外部情报: {company_name}...")
        company_intel = fetch_company_intel(company_name)

    # 🚀 同步拉取用户偏好底线（与批量入口保持一致）
    user_preferences = get_user_preferences()

    # 🚀 注入情报 + 偏好底线，执行 8 维度评估
    result = evaluate_single_job(
        job_data,
        resume_text,
        company_intel=company_intel,
        preferences_text=user_preferences,
    )

    if result.get("success"):
        is_updated = update_feishu_record(
            record_id,
            result["update_data"]
        )
        
        if is_updated:
            print(f"\n✅ 成功处理岗位！状态: {result['status']}, 得分: {result['ai_score']}")
        else:
            print(f"\n❌ 飞书回写失败")
    else:
        print(f"\n❌ 评估失败: {result.get('error', '未知错误')}")
    
    print(f"{'='*60}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='AI 岗位评估引擎')
    parser.add_argument('--record_id', type=str, help='飞书记录 ID')
    parser.add_argument('--table_id', type=str, help='(已废弃) 飞书表格 ID，为兼容保留')
    
    args = parser.parse_args()
    
    if args.record_id:
        run_single_job_evaluation(args.record_id)
    else:
        run_smart_evaluation()
