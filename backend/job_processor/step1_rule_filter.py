import sqlite3
import re
import json
import os
import datetime
import asyncio

# 统一走 db_paths 阀门：dev 态逐字保持 backend/data 锚点，打包态落 JOBHUNTER_DATA_DIR
from app.core.db_paths import job_hunter_db_path

DB_PATH = job_hunter_db_path(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "job_hunter.db"))

# 🌟 全局清洗互斥锁：确保全系统（调试面板、全自动链路、定时调度）同时只有 1 个清洗流水线在跑，杜绝并发自愈冲突
GLOBAL_CLEAN_LOCK = asyncio.Lock()

# 清洗平台范围归一：把口语平台名映射为 raw_jobs.platform 库内规范值。
# 口径与 app/services/feishu_jobs_fetcher.normalize_platform_name 的四平台子串规则一致
# （引擎不 import 它，保持 job_processor 可独立测试）；只认清洗管道实际覆盖的四平台。
_CLEAN_PLATFORM_PATTERNS = (
    ("boss", "BOSS直聘"), ("直聘", "BOSS直聘"),
    ("51", "51job"), ("前程", "51job"),
    ("猎聘", "猎聘"), ("liepin", "猎聘"),
    ("智联", "智联招聘"), ("zhilian", "智联招聘"), ("zhaopin", "智联招聘"),
)

def _normalize_clean_platform(platform) -> str:
    """归一清洗平台范围；None/空串/识别不出返回 ""（由调用方决定不限定或拒绝）。"""
    n = str(platform or "").strip().lower()
    if not n:
        return ""
    for needle, canonical in _CLEAN_PLATFORM_PATTERNS:
        if needle in n:
            return canonical
    return ""

# 🌟 全局急刹车开关：支持手动终止清洗任务
GLOBAL_STOP_FLAG = False

# AI 侦察兵死因溯源字段：模型对判定为 true 的维度回摘的 JD 原句（对象，键=维度 Key）
EVIDENCE_KEY = "触发依据"

def set_stop_flag(value: bool):
    global GLOBAL_STOP_FLAG
    GLOBAL_STOP_FLAG = bool(value)
    print(f"🛑 [Step1RuleFilter] GLOBAL_STOP_FLAG -> {GLOBAL_STOP_FLAG}")

def get_stop_flag() -> bool:
    return GLOBAL_STOP_FLAG

# ================= 0. 从 SQLite 加载激活策略 =================
def load_active_strategy():
    """从 SQLite 数据库实时拉取当前激活的策略模板"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT min_salary_k, max_salary_k, experience_years_max, "
            "exclude_education, allowed_cities, safe_phrases, keyword_rules "
            "FROM job_strategies WHERE is_active = 1 LIMIT 1"
        )
        row = cursor.fetchone()
        conn.close()

        if not row:
            # 2026-10-07：兜底必须是空 dict 而非 None——注释语义即"空策略兜底"，
            # 但 None 会让本文件全部 3 个调用点（Tier1 硬过滤/Tier2 AI 侦察/完整流水线）
            # 对 None 调 .get() 崩溃（Windows 新装系统无策略行时用户实测必现）
            print("⚠️ 未找到激活的求职策略，将使用空策略兜底（全部规则放行）")
            return {}

        config = {
            "min_salary_k": row[0],
            "max_salary_k": row[1],
            "experience_years_max": row[2],
            "exclude_education": json.loads(row[3] or "[]"),
            "allowed_cities": json.loads(row[4] or "[]"),
            "safe_phrases": json.loads(row[5] or "[]"),
            "keyword_rules": json.loads(row[6] or "[]"),
        }
        
        # Load AI Scout Rules if the column exists
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT ai_scout_rules FROM job_strategies WHERE is_active = 1 LIMIT 1")
            scout_row = cursor.fetchone()
            if scout_row and scout_row[0]:
                config["ai_scout_rules"] = json.loads(scout_row[0])
            else:
                config["ai_scout_rules"] = []
        except sqlite3.OperationalError:
            config["ai_scout_rules"] = []
            
        conn.close()
        return config
    except Exception as e:
        if "no such table" in str(e):
            # 表缺失两种可能：全新机器首启建表引导尚未跑完（正常时序），或运行期库结构
            # 意外损坏/被删（需排查）。文案保持中立、不预设场景（agy P2 复审建议采纳）
            print(f"⏳ 策略数据表不存在（{e}），本次降级用空策略兜底；若非首次启动，请排查主库结构")
            return {}
        print(f"❌ 读取策略数据库失败: {e}")
        return {}

# 🌟 别名兼容（解决单跑微控与流水线调用的命名一致性）
_get_active_strategy = load_active_strategy


import asyncio
from openai import AsyncOpenAI
from dotenv import load_dotenv

# 🌟 统一 Token 埋点：AI 侦察兵的每次 create() 都自动记录 token 消耗
from app.core.llm_tracker import make_tracked_client

load_dotenv()
# 🌟 清洗 LLM 通道选择（每次调用动态读取，配置页保存即生效）：
# 优先 CLEANER 专属通道；USE_MAIN_LLM_FOR_CLEANER=1 强制走主通道；
# CLEANER 未配置时自动回落主通道（与配置页「如不填写默认走 LLM 大模型」的说明一致）
from common.config import _cfg

# 🌟 模块级兼容，允许测试脚本覆写或旧调用注入
LLM_MODEL = None
client = None

def _cleaner_llm_config():
    if LLM_MODEL:
        return _cfg("OPENAI_API_KEY", json_key="OPENAI_API_KEY"), _cfg("OPENAI_BASE_URL", json_key="OPENAI_BASE_URL"), LLM_MODEL
    use_main = (_cfg("USE_MAIN_LLM_FOR_CLEANER", json_key="USE_MAIN_LLM_FOR_CLEANER") or "").strip().lower() in ("1", "true", "yes")
    if not use_main:
        key = _cfg("CLEANER_LLM_API_KEY", json_key="CLEANER_LLM_API_KEY")
        url = _cfg("CLEANER_LLM_BASE_URL", json_key="CLEANER_LLM_BASE_URL")
        model = _cfg("CLEANER_LLM_MODEL", json_key="CLEANER_LLM_MODEL")
        if key and url:
            return key, url, (model or _cfg("OPENAI_MODEL", json_key="OPENAI_MODEL") or "qwen-turbo")
    return (
        _cfg("OPENAI_API_KEY", json_key="OPENAI_API_KEY"),
        _cfg("OPENAI_BASE_URL", json_key="OPENAI_BASE_URL"),
        _cfg("OPENAI_MODEL", json_key="OPENAI_MODEL") or "qwen-turbo",
    )

def get_cleaner_model() -> str:
    """获取当前生效的清洗模型名称"""
    _, _, model = _cleaner_llm_config()
    return model

_cleaner_client = None
_cleaner_sig = None

def get_cleaner_client():
    """惰性构建并缓存清洗客户端；Key/URL/模型任一变更时自动重建，配置页保存即生效。"""
    global _cleaner_client, _cleaner_sig
    if client is not None:
        return client
    key, url, model = _cleaner_llm_config()
    sig = (key, url, model)
    if _cleaner_client is None or _cleaner_sig != sig:
        # max_retries=0：重试权威唯一归统一策略层（RetryPolicy 3 次尝试、槽外退避）。
        # SDK 默认 2 次重试会在并发槽在飞期间放大 3 倍占槽时长，上游故障时把
        # 批处理配额（默认 2）饿死（2026-10-31 事故：60s 槽等待连环超时）。
        raw = AsyncOpenAI(api_key=key, base_url=url, timeout=60.0, max_retries=0)
        # 🌟 经 make_tracked_client 包装，调用方代码（client.chat.completions.create）零改动即自动埋点
        _cleaner_client = make_tracked_client(raw, model_default=model, caller="step1_rule_filter")
        _cleaner_sig = sig
    return _cleaner_client

async def push_sse_message(task_id: str, message: str, status="info"):
    if not task_id: return
    try:
        from app.tasks.state import task_queues
        if task_id in task_queues:
            data = {"type": "log", "message": f"🤖 [AI侦察兵] {message}"}
            if status == "error":
                data["type"] = "warning"
            msg = f'data: {json.dumps(data, ensure_ascii=False)}\n\n'
            await task_queues[task_id].put(msg)
    except Exception:
        pass

async def push_sse_event(task_id: str, event_data: dict):
    if not task_id: return
    try:
        from app.automation import pipeline_broadcast as _pb
        _pb.record_phase_progress_event(task_id, event_data)
    except Exception as e:
        print(f"⚠️ [SSE] phase_progress 登记失败（不阻断推流）: {e}", flush=True)
    try:
        from app.tasks.state import task_queues
        if task_id in task_queues:
            msg = f'data: {json.dumps(event_data, ensure_ascii=False)}\n\n'
            await task_queues[task_id].put(msg)
    except Exception:
        pass


# ================= 逐岗位流式事件（指挥中心看板实时卡片） =================
# 清洗/飞书推送原本只在整段结束后由编排器批量补发卡片，看板要等全部岗位跑完才动。
# 这里按岗位广播 job 事件（node=clean_rule_node / clean_ai_node），前端卡片随处理逐张翻转。
_JOB_ROW_SQL = (
    "SELECT rowid, * FROM raw_jobs WHERE job_link IN ({ph}) ORDER BY rowid ASC"
)


def _fetch_job_rows(cursor, links) -> list[dict]:
    """按 job_link 批量取卡片所需字段（分块防 SQLite 占位符上限）。"""
    rows: list[dict] = []
    if not links:
        return rows
    chunk_size = 500
    for i in range(0, len(links), chunk_size):
        chunk = links[i:i + chunk_size]
        ph = ','.join(['?'] * len(chunk))
        cursor.execute(_JOB_ROW_SQL.format(ph=ph), chunk)
        cols = [c[0] for c in cursor.description]
        rows.extend(dict(zip(cols, r)) for r in cursor.fetchall())
    return rows


async def _emit_clean_job_event(sse_task_id, row: dict, *, node: str, status: str,
                                sub_status: str | None = None,
                                reject_reason: str | None = None,
                                reject_type: str | None = None,
                                last_action_desc: str | None = None) -> None:
    """广播单个清洗岗位的流转事件（job_id 与抓取卡一致：raw_{rowid}）。"""
    from app.automation import pipeline_broadcast as pb
    kwargs = {}
    if sub_status is not None:
        kwargs["sub_status"] = sub_status
    if reject_reason is not None:
        kwargs["reject_reason"] = reject_reason
    if reject_type is not None:
        kwargs["reject_type"] = reject_type
    if last_action_desc is not None:
        kwargs["last_action_desc"] = last_action_desc
    try:
        await pb.emit_job(
            sse_task_id,
            job_id=f"raw_{row['rowid']}",
            job_name=row.get("job_title") or "未知岗位",
            node=node,
            status=status,
            platform=row.get("platform") or "",
            company_name=row.get("company_name") or "",
            salary=row.get("salary") or "",
            city=row.get("city") or "",
            job_url=row.get("job_link") or "",
            **kwargs,
        )
    except Exception as e:
        # 流式事件只服务看板，任何异常都不得阻断真实清洗
        print(f"⚠️ [SSE] 清洗岗位事件广播失败（不阻断）: {e}", flush=True)


async def _emit_tier1_job_events(sse_task_id, cursor, target_links) -> None:
    """Tier 1 完成后逐岗位广播：淘汰卡立刻进淘汰 Tab，通过卡显示排队 AI 排雷。"""
    for row in _fetch_job_rows(cursor, target_links):
        p_status = row.get("process_status") or ""
        if p_status in ('清洗淘汰', 'ai清洗淘汰'):
            is_ai = p_status == 'ai清洗淘汰'
            await _emit_clean_job_event(
                sse_task_id, row,
                node="clean_rejected", status="rejected",
                reject_reason=row.get("reject_reason") or ("触发AI排雷规则淘汰" if is_ai else "触发清洗淘汰规则"),
                reject_type="ai" if is_ai else "rule",
                last_action_desc="触发AI排雷规则淘汰" if is_ai else "触发规则清洗淘汰",
            )
        else:
            await _emit_clean_job_event(
                sse_task_id, row,
                node="clean_rule_node", status="running", sub_status="clean_rule_passed",
            )


class AIScoutEngine:
    def __init__(self, strategy: dict):
        self.ai_scout_rules = strategy.get("ai_scout_rules", [])
        self.system_prompt_printed = False
        
    def _parse_evaluate_result(self, result_text: str) -> dict | None:
        """解析模型返回的 JSON。失败返回 None（而非空 dict）——空 dict 会被
        _check_ai_rules 当成「所有 must 条件都不满足」而大面积误杀。"""
        json_str = result_text.replace("```json", "").replace("```", "").strip()
        try:
            result_json = json.loads(json_str, strict=False)
            if not isinstance(result_json, dict):
                print(f"❌ [AI侦察兵] 模型返回非 JSON 对象（{type(result_json).__name__}），视为解析失败", flush=True)
                return None
            print(f"======== 🧩 [AI侦察兵] 判定结果 ========\n{json.dumps(result_json, ensure_ascii=False, indent=2)}\n======================================", flush=True)
            return result_json
        except json.JSONDecodeError as e:
            print(f"❌ [AI侦察兵] JSON 解析失败，模型返回内容: {result_text}\n错误详情: {e}", flush=True)
            return None

    def _format_evidence_suffix(self, evidence_map: dict, keyword: str, jd_text) -> str:
        """把模型给出的「触发依据」原句拼进死因，便于人工核对是否误杀。

        摘录能在 JD 原文（空白归一后）逐字命中时标「JD 原句」；否则标「模型转述」，
        提醒读者该句可能经过模型改写，需回 JD 详情核对。
        """
        quote = re.sub(r"\s+", " ", str(evidence_map.get(keyword) or "").strip())
        if not quote:
            return ""
        if len(quote) > 120:
            quote = quote[:120] + "…"
        normalized_jd = re.sub(r"\s+", " ", str(jd_text or ""))
        label = "JD 原句" if (normalized_jd and quote in normalized_jd) else "JD 依据(模型转述)"
        return f"，{label}: “{quote}”"

    def _check_ai_rules(self, result_json: dict, rules: list, jd_text=None) -> dict:
        # 触发依据：模型对判定为 true 的维度回摘的 JD 原句（缺省/格式异常时静默降级，不影响判定）
        evidence_map = result_json.get(EVIDENCE_KEY)
        if not isinstance(evidence_map, dict):
            evidence_map = {}
        for rule in rules:
            keyword = rule.get("keyword")
            condition = rule.get("condition")
            is_match = result_json.get(keyword)

            if isinstance(is_match, str):
                is_match = is_match.lower() in ('true', '是', '1', 'yes')
            elif is_match is None:
                is_match = False
            else:
                is_match = bool(is_match)

            if condition == "must" and not is_match:
                return {"status": "REJECT", "reject_reason": f"触发 AI 侦察兵排雷: 不满足必须条件 [{keyword}]"}
            if condition == "never" and is_match:
                reason = f"触发 AI 侦察兵排雷: 触发绝不条件 [{keyword}]"
                reason += self._format_evidence_suffix(evidence_map, keyword, jd_text)
                return {"status": "REJECT", "reject_reason": reason}

        return {"status": "PASS", "reject_reason": None}

    async def evaluate_job(self, job_title, jd_text, company_name="", sse_task_id=None):
        if not self.ai_scout_rules:
            return {"status": "PASS", "reject_reason": None}
            
        schema_fields = []
        example_json = {}
        for i, rule in enumerate(self.ai_scout_rules):
            keyword = rule.get("keyword", f"rule_{i}")
            desc = rule.get("desc", "")
            schema_fields.append(f'- "{keyword}": Boolean. {desc}')
            example_json[keyword] = False
        # 死因溯源：要求模型对判定为 true 的维度摘录 JD 原句，人工核对误杀时不用逐条翻 JD
        example_json[EVIDENCE_KEY] = {}

        example_json_str = json.dumps(example_json, ensure_ascii=False, indent=4)

        system_prompt = f"""你是一个无情的简历匹配排雷兵。请阅读用户提供的招聘JD，并严格判断几个核心条件。
请只输出一个 JSON，不要包含任何 markdown 代码块或多余解释。
【非常重要】必须严格使用【判断维度】中定义的中文 Key 作为 JSON 的键名，绝对不能自行翻译成英文！

【判断维度】
{chr(10).join(schema_fields)}

【触发依据】（强制字段，用于死因溯源）
- "触发依据" 是一个对象：判定为 true 的每个维度必须收录，键为维度 Key，值为该维度命中的 JD 原文句子——必须一字不差摘抄原文，禁止改写、总结或跨段拼凑；超过 60 字时截取最关键的一句。
- 判定为 false 的维度绝不能出现在 "触发依据" 中。
- 所有维度均为 false 时，"触发依据" 返回空对象 {{}}。

返回的 JSON 格式示例（必须使用以下精确的Key）：
{example_json_str}
"""

        user_prompt = f"""【职位名称】
{job_title}

【职位描述】
{str(jd_text)}"""

        model = get_cleaner_model()
        if not self.system_prompt_printed:
            print(f"\n======== 🧠 [AI侦察兵 - 白盒探针] 发送给 {model} 的 System Prompt (仅打印一次) ========\n{system_prompt}\n============================================================", flush=True)
            self.system_prompt_printed = True
            
        print(f"🤖 [AI侦察兵] 正在评估岗位: 【{company_name} - {job_title}】...", flush=True)
        
        try:
            response = await get_cleaner_client().chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ]
            )
            result_text = response.choices[0].message.content.strip()

            result_json = self._parse_evaluate_result(result_text)

            # 🌟 fail-preserve：解析失败返回 None，岗位保留「待AI初筛」等下轮重试，
            # 绝不误判成「不满足 must 条件」误杀，也不无脑 PASS 放行不合格岗位
            if result_json is None:
                self._report_blocked(sse_task_id, kind="unknown",
                                     message="模型返回格式异常（JSON 解析失败）",
                                     gateway_hint=str(result_text)[:200])
                await push_sse_message(sse_task_id, "⚠️ 模型返回格式异常，本轮保留该岗位在待AI初筛池，等待下轮重试", status="error")
                return {"status": "PRESERVE", "reject_reason": None}

            # 判定矩阵只播报布尔维度；「触发依据」是溯源原句对象，不进矩阵文案
            judge_items = [(k, v) for k, v in result_json.items() if k != EVIDENCE_KEY]
            formatted_judgement = ", ".join([f"{k}={'是' if v else '否'}" for k, v in judge_items])
            await push_sse_message(sse_task_id, f"🧠 AI 返回判定矩阵: [{formatted_judgement}]")

            # 真实 LLM 往返成功（含 PASS/REJECT 判定）：解除任务级阻塞登记
            self._report_recovered(sse_task_id)
            return self._check_ai_rules(result_json, self.ai_scout_rules, jd_text=jd_text)

        except Exception as e:
            print(f"❌ AI 侦察兵请求异常: {str(e)}")
            self._report_blocked(sse_task_id, exc=e)
            # 🌟 fail-preserve：网络/配额异常同样保留原池，防止 API 故障时不合格岗位整批漏进待推送池
            await push_sse_message(sse_task_id, f"⚠️ AI 请求异常（{str(e)[:80]}），本轮保留该岗位在待AI初筛池", status="error")
            return {"status": "PRESERVE", "reject_reason": None}

    @staticmethod
    def _report_blocked(sse_task_id, exc: Exception | None = None, kind: str | None = None,
                        message: str = "", gateway_hint: str = "") -> None:
        """把 PRESERVE 根因上报到任务级阻塞登记（dashboard-sync/横幅/继续任务的依据）。"""
        if not sse_task_id:
            return
        try:
            from app.automation import pipeline_blocked
            if exc is not None:
                from app.core.llm_errors import classify_llm_error
                err_kind, user_msg, retry_after = classify_llm_error(exc)
                kind = err_kind.value if hasattr(err_kind, "value") else str(err_kind)
                message = user_msg
                gateway_hint = str(exc)[:200]
            try:
                model = get_cleaner_model()
            except Exception:
                model = None
            pipeline_blocked.report_llm_failure(
                sse_task_id, kind=kind or "unknown", model=model,
                message=message, gateway_hint=gateway_hint)
        except Exception as report_e:
            print(f"⚠️ [AI侦察兵] 阻塞状态登记失败（不阻断清洗）: {report_e}", flush=True)

    @staticmethod
    def _report_recovered(sse_task_id) -> None:
        if not sse_task_id:
            return
        try:
            from app.automation import pipeline_blocked
            pipeline_blocked.report_llm_success(sse_task_id)
        except Exception:
            pass

# ================= 2. 数据清洗专项 =================

def _parse_daily_salary(salary_str: str, min_k: float, max_k: float) -> bool:
    matches = re.findall(r'(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)', salary_str)
    if not matches:
        return False
    min_val, max_val = float(matches[0][0]), float(matches[0][1])
    return (min_val * 22 / 1000 > max_k) or (max_val * 22 / 1000 < min_k)

def _parse_yearly_salary(salary_str: str, min_k: float, max_k: float) -> bool:
    matches = re.findall(r'(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)', salary_str)
    if not matches:
        return False
    min_val, max_val = float(matches[0][0]), float(matches[0][1])
    return (min_val * 10 / 12 > max_k) or (max_val * 10 / 12 < min_k)

def _get_max_monthly_salary(max_val: float, max_unit: str) -> float:
    if max_unit == '元' or (not max_unit and max_val >= 1000):
        return max_val / 1000
    if max_unit == '万':
        return max_val * 10
    return max_val

def _get_min_monthly_salary(min_val: float, min_unit: str, max_val: float, max_unit: str) -> float:
    if min_unit == '万':
        return min_val * 10
    if min_unit in ('k', '千'):
        return min_val
    if max_unit == '万' and min_val < 100:
        return min_val * 10
    if max_unit in ('k', '千') and min_val < 1000:
        return min_val
    if (max_unit == '元' or max_val >= 1000) and min_val >= 1000:
        return min_val / 1000
    return min_val

def _parse_monthly_salary(salary_str: str, min_k: float, max_k: float) -> bool:
    matches = re.search(r'(\d+(?:\.\d+)?)([千万k])?[-至~]+(\d+(?:\.\d+)?)([千万k元])?', salary_str)
    if not matches:
        return False
    min_val, min_unit, max_val, max_unit = float(matches.group(1)), matches.group(2), float(matches.group(3)), matches.group(4)
    max_sal = _get_max_monthly_salary(max_val, max_unit)
    min_sal = _get_min_monthly_salary(min_val, min_unit, max_val, max_unit)
    return (min_sal > max_k) or (max_sal < min_k)

def is_salary_rejected(salary_str, min_k=10, max_k=25):
    if not salary_str or str(salary_str).strip() in ('', 'None', 'nan', '面议', '薪资面议'):
        return False
    salary_str = str(salary_str).lower().replace(' ', '')
    
    if '元/天' in salary_str or '/天' in salary_str:
        return _parse_daily_salary(salary_str, min_k, max_k)
        
    if '万/年' in salary_str or '万元/年' in salary_str:
        return _parse_yearly_salary(salary_str, min_k, max_k)
        
    return _parse_monthly_salary(salary_str, min_k, max_k)

# ================= 修订：资历拦截函数 =================
def is_experience_rejected(exp_req, jd_text, max_years=7):
    """
    向上拦截：拒绝要求 >= max_years 经验的岗位。
    保留 3-5年、5年以上、5-10年 等岗位。
    """
    # 1. 检查官方字段 (experience_req)
    if exp_req and str(exp_req).strip() not in ('', 'None', 'nan', '不限', '经验不限'):
        exp_str = str(exp_req).replace(' ', '')
        
        # 匹配 "X-Y年" (例如 "7-10年")
        range_match = re.search(r'(\d+)-(\d+)年', exp_str)
        if range_match and int(range_match.group(1)) >= max_years:
            return True
            
        # 匹配 "X年以上" / "X年及以上" (例如 "8年以上")
        up_match = re.search(r'(\d+)年(?:及)?以上', exp_str)
        if up_match and int(up_match.group(1)) >= max_years:
            return True

    # 2. 检查 JD 详情内容 (提取年限数字后与阈值比对)
    if jd_text:
        text = str(jd_text).replace(' ', '')
        for pattern in [
            r'(?:要求|需要|具备).{0,5}(\d+)年(?:及)?以上.*经验',
            r'(\d+)年(?:及)?以上(?:的)?(?:相关)?(?:工作|项目|团队管理)经验',
            r'(\d+)-(?:\d+)年(?:的)?(?:相关)?(?:工作|项目)经验',
        ]:
            m = re.search(pattern, text)
            if m and int(m.group(1)) >= max_years:
                return True
            
    return False

# ================= 3. 核心流转逻辑 =================
def run_pipeline(sse_task_id=None, limit=None, min_rowid=0):
    # 强制将整个过程放入事件循环，因为我们要调用 async 侦察兵
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
    loop.run_until_complete(_async_run_pipeline(sse_task_id, limit, min_rowid))


def _filter_by_city(cursor, strategy, target_condition, target_links):
    allowed_cities = strategy.get("allowed_cities", [])
    if allowed_cities:
        # 🌟 参数化绑定：城市名含 ' 或 % 时 f-string 拼 LIKE 会语法错误或错配
        city_not_like = " AND ".join(["IFNULL(city, '') NOT LIKE ?" for _ in allowed_cities])
        address_not_like = " AND ".join(["IFNULL(work_address, '') NOT LIKE ?" for _ in allowed_cities])
        params = [f"%{c}%" for c in allowed_cities] * 2 + list(target_links)
        cursor.execute(
            f"UPDATE raw_jobs SET process_status = '清洗淘汰', reject_reason = '工作城市不在目标范围内' "
            # 谓词必须是认领后的「清洗中」：_run_tier1_hard_filter 已先把本轮行从
            # 「已存入数据」翻为「清洗中」，再查旧态会一条都匹配不到（2026-09-03 回归）。
            # city 与 work_address 同时为空 = 位置字段缺失，交给 AI 判断，不硬杀。
            f"WHERE process_status = '清洗中' "
            f"AND (TRIM(IFNULL(city, '')) <> '' OR TRIM(IFNULL(work_address, '')) <> '') "
            f"AND ({city_not_like}) AND ({address_not_like}) AND {target_condition}",
            params
        )

def _filter_empty_details(cursor, target_condition, target_links):
    cursor.execute(f"UPDATE raw_jobs SET publish_date = REPLACE(publish_date, '更新于 ', '') WHERE platform = '智联招聘' AND {target_condition}", target_links)
    cursor.execute(
        f"UPDATE raw_jobs SET process_status = '清洗淘汰', reject_reason = '岗位详情为空' "
        f"WHERE process_status = '清洗中' AND (jd_text IS NULL OR TRIM(jd_text) = '') AND {target_condition}",
        target_links
    )

def _filter_education(cursor, strategy, target_condition, target_links):
    exclude_education = strategy.get("exclude_education", [])
    if exclude_education:
        # 🌟 参数化绑定：学历词含引号/通配符时不再炸 SQL
        edu_conditions = " OR ".join(["education_req LIKE ?" for _ in exclude_education])
        edu_label = "/".join(exclude_education)
        params = [f"%{edu}%" for edu in exclude_education] + list(target_links)
        cursor.execute(
            f"UPDATE raw_jobs SET process_status = '清洗淘汰', reject_reason = '学历要求不符({edu_label})' "
            f"WHERE process_status = '清洗中' AND ({edu_conditions}) AND {target_condition}",
            params
        )

def _filter_experience(cursor, strategy, target_condition, target_links):
    experience_years_max = strategy.get("experience_years_max", 7)
    cursor.execute(f"SELECT job_link, experience_req, jd_text FROM raw_jobs WHERE process_status = '清洗中' AND {target_condition}", target_links)
    exp_rejects = [(lk,) for lk, exp, jd in cursor.fetchall() if is_experience_rejected(exp, jd, experience_years_max)]
    if exp_rejects:
        cursor.executemany(f"UPDATE raw_jobs SET process_status = '清洗淘汰', reject_reason = '要求资历过高(≥{experience_years_max}年)' WHERE process_status = '清洗中' AND job_link = ?", exp_rejects)

def _filter_salary(cursor, strategy, target_condition, target_links):
    min_salary_k = strategy.get("min_salary_k", 10)
    max_salary_k = strategy.get("max_salary_k", 25)
    cursor.execute(f"SELECT job_link, salary FROM raw_jobs WHERE process_status = '清洗中' AND {target_condition}", target_links)
    salary_rejects = [(lk,) for lk, sal in cursor.fetchall() if is_salary_rejected(sal, min_salary_k, max_salary_k)]
    if salary_rejects:
        cursor.executemany("UPDATE raw_jobs SET process_status = '清洗淘汰', reject_reason = '薪资区间不符' WHERE process_status = '清洗中' AND job_link = ?", salary_rejects)

def _check_keyword_rejects(title: str, exp: str, keyword_rules: list) -> str:
    title_lower = str(title).lower() if title else ""
    exp_lower = str(exp).lower() if exp else ""
    for rule in keyword_rules:
        kw = rule.get("keyword", "")
        scope = rule.get("scope", "")
        action = rule.get("action", "")
        if action == "reject" and kw:
            kw_lower = kw.lower()
            if scope == "title" and kw_lower in title_lower:
                return f"标题包含排除词: {kw}"
            if scope == "experience" and kw_lower in exp_lower:
                return f"经验要求包含排除词: {kw}"
    return ""

def _filter_keywords(cursor, strategy, target_condition, target_links):
    keyword_rules = strategy.get("keyword_rules", [])
    if not keyword_rules:
        return
    cursor.execute(f"SELECT job_link, job_title, experience_req FROM raw_jobs WHERE process_status = '清洗中' AND {target_condition}", target_links)
    kw_rejects = []
    for lk, title, exp in cursor.fetchall():
        reason = _check_keyword_rejects(title, exp, keyword_rules)
        if reason:
            kw_rejects.append((reason, lk))
    if kw_rejects:
        cursor.executemany("UPDATE raw_jobs SET process_status = '清洗淘汰', reject_reason = ? WHERE process_status = '清洗中' AND job_link = ?", kw_rejects)

async def _run_tier2_ai_scout(cursor, conn, strategy, sse_task_id, limit, target_links=None,
                              emit_job_events=False, on_job_passed=None):
    print("🤖 [阶段二] 开始执行 AI 侦察兵排雷...")
    engine = AIScoutEngine(strategy)

    # 卡片字段随查询一次取回：逐岗位事件要复用与抓取卡完全一致的 job_id/描述字段。
    # 用 rowid,* 而不是固定列名：历史/测试库可能缺列，缺列时按空值降级而不是直接崩。
    select_cols = "rowid, *"

    def _rows_to_dicts(rows):
        cols = [c[0] for c in cursor.description]
        return [dict(zip(cols, r)) for r in rows]

    if target_links:
        # 精准闭环：优先处理本轮硬过滤锁定的岗位中进入「待AI初筛」的记录
        pending_jobs = []
        chunk_size = 500
        for i in range(0, len(target_links), chunk_size):
            chunk = target_links[i:i + chunk_size]
            placeholders = ','.join(['?'] * len(chunk))
            cursor.execute(
                f"SELECT {select_cols} FROM raw_jobs WHERE process_status = '待AI初筛' AND job_link IN ({placeholders})",
                chunk,
            )
            pending_jobs.extend(_rows_to_dicts(cursor.fetchall()))
        if limit and limit > 0:
            pending_jobs = pending_jobs[:limit]
    else:
        query = f"SELECT {select_cols} FROM raw_jobs WHERE process_status = '待AI初筛'"
        if limit and limit > 0:
            query += f" LIMIT {limit}"
        cursor.execute(query)
        pending_jobs = _rows_to_dicts(cursor.fetchall())

    if pending_jobs:
        await push_sse_message(sse_task_id, f"Tier 1 清洗完毕，有 {len(pending_jobs)} 个岗位进入 Tier 2: AI 侦察兵排雷 (并发=5)")

    if not pending_jobs:
        return

    sem = asyncio.Semaphore(5)
    total = len(pending_jobs)
    completed_count = 0
    passed_count = 0
    rejected_count = 0
    # D1（2026-10-31 事故）：LLM 网关持续故障时逐岗硬撞只会把每岗全价重试预算烧完
    # （当时实测每岗约 3 分钟），整轮清洗被拖到收口超时。连续 N 个岗位评估失败即短路
    # 本轮：剩余岗位不再调用 LLM，直接保留「待AI初筛」，等网关恢复后由「继续任务」
    # 或下一轮重洗。成功/淘汰即清零计数，间歇性失败不误触发。
    try:
        AI_SCOUT_SHORTCUT_THRESHOLD = max(1, int(_cfg("AI_SCOUT_SHORTCUT_THRESHOLD") or 3))
    except (TypeError, ValueError):
        AI_SCOUT_SHORTCUT_THRESHOLD = 3
    consecutive_failures = 0
    llm_shortcut = False
    shortcut_skipped = 0
    # 流式推送后台任务：不占评估槽位，收尾前统一 await 收口
    push_tasks: list[asyncio.Task] = []
    await push_sse_event(sse_task_id, {"type": "phase_progress", "phase": "ai_scout", "current": 0, "total": total, "passed": 0, "rejected": 0})

    def _persist_one(job_link: str, status: str, reason) -> bool:
        """单岗位即时落库：先落库再发事件，12 秒快照永远不会把刚判定的状态倒回旧值。

        返回 False 表示落库失败（锁等待超时等）。此时该岗位保持「待AI初筛」，
        由调用方按未完成处理——绝不能让单岗落库异常炸穿整个清洗段。
        """
        for attempt in (1, 2):
            try:
                cursor.execute(
                    "UPDATE raw_jobs SET process_status = ?, reject_reason = ? WHERE job_link = ?",
                    (status, reason, job_link),
                )
                conn.commit()
                return True
            except sqlite3.OperationalError as e:
                try:
                    conn.rollback()
                except Exception:
                    pass
                if attempt == 2:
                    print(
                        f"⚠️ [清洗] 岗位落库失败（保留待AI初筛，可手动重跑 AI 排雷）: "
                        f"{job_link}: {e}", flush=True)
        return False

    async def _eval_one(idx: int, job: dict):
        nonlocal completed_count, passed_count, rejected_count
        nonlocal consecutive_failures, llm_shortcut, shortcut_skipped
        job_link = job.get("job_link")
        job_title = job.get("job_title")
        jd_text = job.get("jd_text")
        company_name = job.get("company_name")
        if get_stop_flag():
            print(f"🛑 [AI排雷急刹] 收到终止信号，跳过后续岗位: {job_title}")
            return ('待AI初筛', '任务已手动终止', job_link)

        async def _shortcut_skip():
            """D1 短路跳过单点实现：不再调用 LLM，岗位原样留池，计数照常推进（看板进度不悬挂）。
            外审 R2-P1：外层快路径与信号量内复检共用本协程——首个事件循环 tick 内
            排队协程已越过外层判断挂到 sem 门口，sem 内不复检则短路保护完全失效。"""
            nonlocal shortcut_skipped, completed_count
            shortcut_skipped += 1
            completed_count += 1
            print(f"⏭️ [AI排雷短路] LLM 持续失败，本轮跳过评估，保留待AI初筛: {company_name} - {job_title}", flush=True)
            if emit_job_events:
                # 岗位级卡片事件：未评估的岗位在看板上同样翻成「保留待AI初筛」，
                # 避免看板出现整段无明细的空洞
                await _emit_clean_job_event(
                    sse_task_id, job, node="clean_ai_node", status="running",
                    sub_status="clean_ai_preserved",
                )
            await push_sse_event(sse_task_id, {
                "type": "phase_progress",
                "phase": "ai_scout",
                "current": completed_count,
                "total": total,
                "passed": passed_count,
                "rejected": rejected_count
            })
            return ('待AI初筛', None, job_link)

        if llm_shortcut:
            return await _shortcut_skip()
        async with sem:
            if get_stop_flag():
                print(f"🛑 [AI排雷急刹] 信号生效，跳过未评估岗位: {job_title}")
                return ('待AI初筛', None, job_link)
            if llm_shortcut:
                # 信号量唤醒后复检短路标志：等待期间前序请求可能已把 llm_shortcut 置位
                return await _shortcut_skip()
            print(f"\n🔍 [AI排雷] {idx+1}/{total}: {company_name} - {job_title}", flush=True)
            await push_sse_message(sse_task_id, f"🔍 开始评估: {company_name} - {job_title}")
            if emit_job_events:
                await _emit_clean_job_event(sse_task_id, job, node="clean_ai_node", status="running")
            res = await engine.evaluate_job(job_title, jd_text, company_name, sse_task_id)

            # 🌟 急刹二次确认：若在网络请求等待期间收到了终止信号，坚决放弃本次流转，保留在待AI初筛池！
            if get_stop_flag():
                print(f"🛑 [AI排雷急刹] 推理中途收到终止信号，废弃中途结果，严格保留在待AI初筛池: {company_name} - {job_title}", flush=True)
                return ('待AI初筛', None, job_link)

            if res['status'] == 'PRESERVE':
                # 🌟 fail-preserve：解析失败/API 异常，不计通过也不计拦截，保留原池下轮重试
                print(f"↩️ [Tier 2 AI排雷保留] 【{job_title}】 -> 模型输出异常，保留在待AI初筛池等待重试", flush=True)
                consecutive_failures += 1
                if not llm_shortcut and consecutive_failures >= AI_SCOUT_SHORTCUT_THRESHOLD:
                    llm_shortcut = True
                    remaining = max(0, total - completed_count - 1)
                    print(f"⏸️ [AI排雷短路] 连续 {consecutive_failures} 个岗位评估失败，本轮剩余约 {remaining} 个岗位直接留池，不再调用 LLM", flush=True)
                    await push_sse_message(
                        sse_task_id,
                        f"⏸️ AI 排雷连续 {consecutive_failures} 次失败（疑似 LLM 网关不可用），本轮剩余岗位保留待AI初筛，已短路不再调用 LLM",
                        status="error",
                    )
                completed_count += 1
                if emit_job_events:
                    await _emit_clean_job_event(
                        sse_task_id, job, node="clean_ai_node", status="running",
                        sub_status="clean_ai_preserved",
                    )
                await push_sse_event(sse_task_id, {
                    "type": "phase_progress",
                    "phase": "ai_scout",
                    "current": completed_count,
                    "total": total,
                    "passed": passed_count,
                    "rejected": rejected_count
                })
                return ('待AI初筛', None, job_link)

            if res['status'] == 'REJECT':
                consecutive_failures = 0
                final_status = 'ai清洗淘汰'
                print(f"🚫 [Tier 2 AI排雷淘汰] 【{job_title}】 -> 死因: {res['reject_reason']}", flush=True)
                if not _persist_one(job_link, final_status, res['reject_reason']):
                    return ('待AI初筛', None, job_link)
                rejected_count += 1
                if emit_job_events:
                    await _emit_clean_job_event(
                        sse_task_id, job, node="clean_rejected", status="rejected",
                        reject_reason=res['reject_reason'], reject_type="ai",
                        last_action_desc="触发AI排雷规则淘汰",
                    )
                await push_sse_message(sse_task_id, f"🚫 {company_name} - {job_title}: {res['reject_reason']}", status="error")
            else:
                consecutive_failures = 0
                final_status = '待推送至飞书'
                print(f"✅ 侦察兵放行: {company_name} - {job_title}", flush=True)
                if not _persist_one(job_link, final_status, res['reject_reason']):
                    return ('待AI初筛', None, job_link)
                passed_count += 1
                if emit_job_events:
                    await _emit_clean_job_event(
                        sse_task_id, job, node="clean_ai_node", status="running",
                        sub_status="clean_ai_passed",
                    )
                # 流式推送：通过清洗即刻推飞书，不等整批清洗跑完。
                # 后台任务执行，不占用 Tier2 评估并发槽位；失败只告警——
                # 行仍是「待推送至飞书」，批量段会再兜底一次。
                if on_job_passed is not None:
                    push_tasks.append(asyncio.create_task(on_job_passed(job)))
                await push_sse_message(sse_task_id, f"✅ {company_name} - {job_title}: 安全放行")

            completed_count += 1
            await push_sse_event(sse_task_id, {
                "type": "phase_progress", 
                "phase": "ai_scout", 
                "current": completed_count, 
                "total": total,
                "passed": passed_count,
                "rejected": rejected_count
            })
            return (final_status, res['reject_reason'], job_link)

    tasks = [_eval_one(i, job) for i, job in enumerate(pending_jobs)]
    update_data = await asyncio.gather(*tasks)
    # 流式推送是后台任务：必须等全部推送收口再返回，否则批量兜底段会与在途推送并发
    if push_tasks:
        await asyncio.gather(*push_tasks, return_exceptions=True)

    if shortcut_skipped:
        await push_sse_message(
            sse_task_id,
            f"⏸️ 本轮 AI 排雷短路收口：{shortcut_skipped} 个岗位未经评估保留在待AI初筛池，LLM 恢复后可通过「继续任务」重洗",
            status="error",
        )

    # 🌟 每个岗位已在 _eval_one 内即时落库，gather 后不再做批量回写：
    # 流式推送成功的行此时已是「已同步 + is_synced=1」，批量回写会把它打回
    # 「待推送至飞书」，而批量兜底又按 is_synced=0 过滤 → 行永久卡死（2026-10-31 审查 P0）。
    # 仅真正被 AI 判定完成（ai清洗淘汰 或 待推送至飞书）的岗位计数播报。
    changed_data = [d for d in update_data if d[0] != '待AI初筛']
    if changed_data:
        await push_sse_message(sse_task_id, f"🎉 本轮处理完成！共对 {len(changed_data)} 条岗位进行了有效落库。")

async def _generate_cleaning_report(cursor, sse_task_id, target_links):
    if not target_links:
        return
    
    # 🌟 分块聚合查询，防止超长 target_links 击穿 SQLite 占位符数量上限
    status_counts = {}
    chunk_size = 500
    for i in range(0, len(target_links), chunk_size):
        chunk = target_links[i:i + chunk_size]
        placeholders = ','.join(['?'] * len(chunk))
        cursor.execute(f"SELECT process_status, COUNT(*) FROM raw_jobs WHERE job_link IN ({placeholders}) GROUP BY process_status", chunk)
        for st, cnt in cursor.fetchall():
            status_counts[st] = status_counts.get(st, 0) + cnt
    
    total_processed = len(target_links)
    hard_rejected = status_counts.get('清洗淘汰', 0)
    ai_rejected = status_counts.get('ai清洗淘汰', 0)
    # 「已同步」必须计入通过：流式推送成功的岗位在报告生成前就已建档（process_status.SYNCED），
    # 漏计会让清洗报表通过数凭空少一截（2026-10-31 审查 P0 连带项）。
    passed = (
        status_counts.get('待推送至飞书', 0)
        + status_counts.get('已推送飞书', 0)   # 存量旧词，读取兼容
        + status_counts.get('已同步', 0)
    )
    
    report_data = {
        "total_processed": total_processed,
        "passed": passed,
        "hard_rejected": hard_rejected,
        "ai_rejected": ai_rejected
    }
    await push_sse_event(sse_task_id, {"type": "cleaning_report", "data": report_data})
    await push_sse_message(sse_task_id, f"📊 清洗报告: 共处理 {total_processed} 条 -> 最终通过 {passed} 条 (硬规则拦截 {hard_rejected} 条, AI 拦截 {ai_rejected} 条)")


def _run_tier1_hard_filter(cursor, conn, strategy, target_links):
    """同步执行 Tier 1 绝对硬指标过滤核心逻辑，将合格岗位推进为「待AI初筛」，不合格为「清洗淘汰」。

    ⚠️ 状态不变量：本函数先把本轮行原子认领为「清洗中」，之后所有 _filter_*
    必须按「清洗中」查询/更新（不是「已存入数据」）。改成旧态会让 Tier 1 全部空转
    （2026-09-03 回归：bb074e26 加认领后谓词未同步，硬规则静默失效两个月）。
    """
    if not target_links:
        return
    chunk_size = 500
    for i in range(0, len(target_links), chunk_size):
        chunk = target_links[i:i + chunk_size]
        ph = ','.join(['?'] * len(chunk))
        cursor.execute(f"UPDATE raw_jobs SET process_status = '清洗中' WHERE job_link IN ({ph}) AND process_status = '已存入数据'", chunk)
    conn.commit()

    placeholders = ','.join(['?'] * len(target_links))
    target_condition = f"job_link IN ({placeholders})"

    _filter_by_city(cursor, strategy, target_condition, target_links)
    _filter_empty_details(cursor, target_condition, target_links)
    _filter_education(cursor, strategy, target_condition, target_links)
    _filter_experience(cursor, strategy, target_condition, target_links)
    _filter_salary(cursor, strategy, target_condition, target_links)
    _filter_keywords(cursor, strategy, target_condition, target_links)

    cursor.execute(f"SELECT job_title, reject_reason FROM raw_jobs WHERE process_status = '清洗淘汰' AND {target_condition}", target_links)
    tier1_rejects = cursor.fetchall()
    if tier1_rejects:
        print("\n" + "="*50)
        print("🛡️  [Tier 1 硬规则淘汰明细]")
        for title, reason in tier1_rejects:
            print(f"🚫 淘汰: 【{title}】 -> 死因: {reason}")
        print("="*50 + "\n")

    # 将第一阶段未淘汰、依然处于「清洗中」的岗位正式推进到「待AI初筛」
    for i in range(0, len(target_links), chunk_size):
        chunk = target_links[i:i + chunk_size]
        ph = ','.join(['?'] * len(chunk))
        cursor.execute(f"UPDATE raw_jobs SET process_status = '待AI初筛' WHERE process_status = '清洗中' AND job_link IN ({ph})", chunk)
    conn.commit()

async def _async_run_hard_filter_only(sse_task_id=None, limit=None):
    """仅执行阶段一：Tier 1 硬规则初筛（0 Token，本地毫秒级过滤），合格者落库为「待AI初筛」"""
    async with GLOBAL_CLEAN_LOCK:
        set_stop_flag(False)
        strategy = _get_active_strategy()
        conn = sqlite3.connect(DB_PATH, timeout=30.0)
        try:
            cursor = conn.cursor()
            cursor.execute("UPDATE raw_jobs SET process_status = '已存入数据', reject_reason = NULL WHERE process_status = '清洗中'")
            conn.commit()

            query_target = "SELECT job_link FROM raw_jobs WHERE process_status = '已存入数据' ORDER BY rowid DESC"
            if limit and limit > 0:
                query_target += f" LIMIT {limit}"
            cursor.execute(query_target)
            target_links = [r[0] for r in cursor.fetchall()]

            print(f"🧹 [单跑硬规则] 执行 Tier 1 绝对硬指标清洗 - 本轮锁定 {len(target_links)} 条...")
            await push_sse_event(sse_task_id, {"type": "phase_progress", "phase": "hard_clean", "current": 0, "total": len(target_links)})
            await push_sse_message(sse_task_id, f"开始执行 Tier 1: 绝对硬指标清洗 (本轮锁定 {len(target_links)} 条，0 Token消耗)")

            if target_links:
                _run_tier1_hard_filter(cursor, conn, strategy, target_links)

            passed_count = 0
            if target_links:
                ph = ','.join(['?'] * len(target_links))
                cursor.execute(f"SELECT COUNT(*) FROM raw_jobs WHERE process_status = '待AI初筛' AND job_link IN ({ph})", target_links)
                passed_count = cursor.fetchone()[0]
            rejected_count = len(target_links) - passed_count

            await push_sse_event(sse_task_id, {
                "type": "phase_progress", 
                "phase": "hard_clean", 
                "current": len(target_links), 
                "total": len(target_links),
                "passed": passed_count,
                "rejected": rejected_count
            })
            await push_sse_message(sse_task_id, f"🎉 Tier 1 硬规则清洗完成！合格通过: {passed_count} 条 (已进入待AI清洗池)，规则拦截淘汰: {rejected_count} 条")
            return {"total": len(target_links), "passed": passed_count, "rejected": rejected_count}
        finally:
            conn.close()

async def _async_run_ai_scout_only(sse_task_id=None, limit=None, min_rowid=0):
    """仅执行阶段二：Tier 2 AI 深度排雷（消耗 Token），对现存「待AI初筛」执行大模型排雷

    min_rowid > 0 时只处理该 rowid 之后入库的「待AI初筛」行（「继续任务」按阻塞轮次
    圈定重洗范围用）；0 = 全表扫描（手动清洗面板既有语义）。
    """
    async with GLOBAL_CLEAN_LOCK:
        set_stop_flag(False)
        strategy = _get_active_strategy()
        conn = sqlite3.connect(DB_PATH, timeout=30.0)
        try:
            cursor = conn.cursor()
            query = "SELECT job_link FROM raw_jobs WHERE process_status = '待AI初筛'"
            query_params: list = []
            if min_rowid:
                query += " AND rowid > ?"
                query_params.append(int(min_rowid))
            query += " ORDER BY rowid DESC"
            if limit and limit > 0:
                query += f" LIMIT {limit}"
            cursor.execute(query, query_params)
            target_links = [r[0] for r in cursor.fetchall()]

            if not target_links:
                await push_sse_message(sse_task_id, "当前「待 AI 清洗池」暂无待处理岗位，无需排雷。")
                return []

            await push_sse_message(sse_task_id, f"开始对「待 AI 清洗池」中 {len(target_links)} 个岗位执行 Tier 2 AI 深度排雷...")
            await _run_tier2_ai_scout(cursor, conn, strategy, sse_task_id, limit, target_links=target_links)
            await _generate_cleaning_report(cursor, sse_task_id, target_links)

            ph = ','.join(['?'] * len(target_links))
            cursor.execute(f"SELECT job_link FROM raw_jobs WHERE process_status = '待推送至飞书' AND job_link IN ({ph})", target_links)
            passed_links = [r[0] for r in cursor.fetchall()]
            return passed_links
        finally:
            conn.close()

async def _async_skip_ai_to_feishu(sse_task_id=None, limit=None):
    """免 AI 排雷直通飞书：将现存「待AI初筛」直接升格为「待推送至飞书」"""
    async with GLOBAL_CLEAN_LOCK:
        set_stop_flag(False)
        conn = sqlite3.connect(DB_PATH, timeout=30.0)
        try:
            cursor = conn.cursor()
            cursor.execute("UPDATE raw_jobs SET process_status = '待AI初筛', reject_reason = NULL WHERE process_status = '清洗中'")
            conn.commit()

            # 将「待AI初筛」直接升格为「待推送至飞书」
            query_ai_pending = "SELECT job_link FROM raw_jobs WHERE process_status = '待AI初筛' ORDER BY rowid DESC"
            if limit and limit > 0:
                query_ai_pending += f" LIMIT {limit}"
            cursor.execute(query_ai_pending)
            pending_links = [r[0] for r in cursor.fetchall()]

            if pending_links:
                chunk_size = 500
                for i in range(0, len(pending_links), chunk_size):
                    chunk = pending_links[i:i + chunk_size]
                    ph = ','.join(['?'] * len(chunk))
                    cursor.execute(f"UPDATE raw_jobs SET process_status = '待推送至飞书' WHERE process_status = '待AI初筛' AND job_link IN ({ph})", chunk)
                conn.commit()
                await push_sse_message(sse_task_id, f"✅ 已成功将 {len(pending_links)} 条硬规则合格岗位直接升格为「待推送至飞书」")
            else:
                await push_sse_message(sse_task_id, "待AI清洗池中暂无可升格的合格岗位。")

            return pending_links
        finally:
            conn.close()

async def _async_run_pipeline(sse_task_id=None, limit=None, min_rowid=0, platform=None,
                              emit_job_events=False, on_job_passed=None):
    """平台范围参数：None/空 = 全平台（既有行为）；指定平台 = 仅清洗该平台「已存入数据」岗位。

    传入口语平台名（如 "zhilian"/"智联"）会先归一为库内规范值；识别不出的平台名
    直接空跑返回，绝不静默放大成全平台清洗（宁可不做也不做错范围）。
    limit 在平台过滤之后生效（该平台范围内取最新 N 条）。

    emit_job_events=True：逐岗位广播 job 事件（全自动链路看板实时卡片）；
    独立清洗任务不传，保持原有日志/进度协议不变。
    on_job_passed：岗位通过 Tier 2 后的即时回调（全自动链路用于立刻推飞书，
    实现「过一个推一条」；失败由后续批量段兜底）。
    """
    canonical_platform = _normalize_clean_platform(platform)
    raw_platform = str(platform or "").strip()
    if raw_platform and not canonical_platform:
        msg = (f"⚠️ 清洗范围的平台名无法识别: {raw_platform!r}"
               f"（可识别示例: 智联招聘/BOSS直聘/51job/猎聘），本轮未清洗任何数据。")
        print(msg)
        await push_sse_message(sse_task_id, msg, "warning")
        return []

    async with GLOBAL_CLEAN_LOCK:
        set_stop_flag(False)
        strategy = _get_active_strategy()

        conn = sqlite3.connect(DB_PATH, timeout=30.0)
        try:
            cursor = conn.cursor()

            # 🌟 僵尸状态自愈回收（仅回收真正崩溃遗留的行级锁「清洗中」，绝不回退「待AI初筛」）：
            cursor.execute("""
                UPDATE raw_jobs 
                SET process_status = '已存入数据', reject_reason = NULL 
                WHERE process_status = '清洗中'
            """)
            reclaimed_count = cursor.rowcount
            if reclaimed_count > 0:
                conn.commit()
                print(f"🔄 [Processor自愈] 成功回收 {reclaimed_count} 条因异常中断或急刹残留的僵尸岗位，重新纳管清洗！")

            query_target = "SELECT job_link FROM raw_jobs WHERE process_status = '已存入数据'"
            target_params: list = []
            if canonical_platform:
                query_target += " AND platform = ?"
                target_params.append(canonical_platform)
            if min_rowid:
                query_target += f" AND rowid > {int(min_rowid)}"
            query_target += " ORDER BY rowid DESC"
            if limit and limit > 0:
                query_target += f" LIMIT {limit}"
            cursor.execute(query_target, target_params)
            target_links = [r[0] for r in cursor.fetchall()]

            scope_desc = f"平台={canonical_platform}" if canonical_platform else "全平台"
            print(f"🧹 [联合清洗] 执行数据清洗 (Tier 1 硬性规则) - 范围: {scope_desc}, 本轮处理 {len(target_links)} 条...")
            await push_sse_event(sse_task_id, {"type": "phase_progress", "phase": "hard_clean", "current": 0, "total": len(target_links)})
            await push_sse_message(sse_task_id, f"开始执行 Tier 1: 绝对硬指标清洗 (范围: {scope_desc}，本轮锁定 {len(target_links)} 条)")
            if not target_links:
                # 2026-10-07 透明化：本轮 0 条锁定（待清洗池空）时向用户说明——
                # AI 侦察阶段接下来处理的是存量「待AI初筛」遗留，避免用户误读为
                # "跳过硬清洗直接 AI"（阶段顺序未变，是本轮无新岗位）
                await push_sse_message(sse_task_id, "ℹ️ 本轮「已存入数据」池为空，硬规则阶段无岗位可清洗；若后续 AI 侦察有处理数量，均为上一轮遗留的「待AI初筛」存量岗位。")

            if target_links:
                _run_tier1_hard_filter(cursor, conn, strategy, target_links)
                if emit_job_events:
                    # Tier 1 毫秒级完成：逐岗位补发事件，淘汰卡立即进回收站、通过卡进入 AI 排队态
                    await _emit_tier1_job_events(sse_task_id, cursor, target_links)

            tier1_passed = 0
            if target_links:
                ph = ','.join(['?'] * len(target_links))
                cursor.execute(f"SELECT COUNT(*) FROM raw_jobs WHERE process_status = '待AI初筛' AND job_link IN ({ph})", target_links)
                tier1_passed = cursor.fetchone()[0]
            tier1_rejected = len(target_links) - tier1_passed

            await push_sse_event(sse_task_id, {
                "type": "phase_progress", 
                "phase": "hard_clean", 
                "current": len(target_links), 
                "total": len(target_links),
                "passed": tier1_passed,
                "rejected": tier1_rejected
            })

            if get_stop_flag():
                print("🛑 [清洗急刹] 在阶段一完成后收到终止信号，跳过阶段二 AI 评估。")
                await push_sse_message(sse_task_id, "🛑 任务已被手动终止，阶段二 AI 排雷已取消", "warning")
                return []

            await _run_tier2_ai_scout(
                cursor, conn, strategy, sse_task_id, limit,
                target_links=target_links, emit_job_events=emit_job_events,
                on_job_passed=on_job_passed,
            )
            await _generate_cleaning_report(cursor, sse_task_id, target_links)

            # 🌟 获取本轮真正通过 AI 初筛的岗位列表，供下游精确推送。
            # 已同步也计入：流式推送会在 Tier2 放行后立刻把行写成「已同步」。
            passed_links = []
            if target_links:
                ph = ','.join(['?'] * len(target_links))
                cursor.execute(
                    f"SELECT job_link FROM raw_jobs WHERE process_status IN ('待推送至飞书', '已同步') AND job_link IN ({ph})",
                    target_links,
                )
                passed_links = [r[0] for r in cursor.fetchall()]
            return passed_links
        finally:
            conn.close()

if __name__ == "__main__":
    run_pipeline()