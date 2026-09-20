import sqlite3
import re
import json
import os
import datetime
import asyncio

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "job_hunter.db")

# 🌟 全局清洗互斥锁：确保全系统（调试面板、全自动链路、定时调度）同时只有 1 个清洗流水线在跑，杜绝并发自愈冲突
GLOBAL_CLEAN_LOCK = asyncio.Lock()

# 🌟 全局急刹车开关：支持手动终止清洗任务
GLOBAL_STOP_FLAG = False

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
            print("⚠️ 未找到激活的求职策略，将使用空策略兜底")
            return None

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
        print(f"❌ 读取策略数据库失败: {e}")
        return None

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
        raw = AsyncOpenAI(api_key=key, base_url=url, timeout=60.0)
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
        from app.tasks.state import task_queues
        if task_id in task_queues:
            msg = f'data: {json.dumps(event_data, ensure_ascii=False)}\n\n'
            await task_queues[task_id].put(msg)
    except Exception:
        pass

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

    def _check_ai_rules(self, result_json: dict, rules: list) -> dict:
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
                return {"status": "REJECT", "reject_reason": f"触发 AI 侦察兵排雷: 触发绝不条件 [{keyword}]"}
        
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
            
        example_json_str = json.dumps(example_json, ensure_ascii=False, indent=4)

        system_prompt = f"""你是一个无情的简历匹配排雷兵。请阅读用户提供的招聘JD，并严格判断几个核心条件。
请只输出一个 JSON，不要包含任何 markdown 代码块或多余解释。
【非常重要】必须严格使用【判断维度】中定义的中文 Key 作为 JSON 的键名，绝对不能自行翻译成英文！

【判断维度】
{chr(10).join(schema_fields)}

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
                await push_sse_message(sse_task_id, "⚠️ 模型返回格式异常，本轮保留该岗位在待AI初筛池，等待下轮重试", status="error")
                return {"status": "PRESERVE", "reject_reason": None}

            formatted_judgement = ", ".join([f"{k}={'是' if v else '否'}" for k, v in result_json.items()])
            await push_sse_message(sse_task_id, f"🧠 AI 返回判定矩阵: [{formatted_judgement}]")

            return self._check_ai_rules(result_json, self.ai_scout_rules)

        except Exception as e:
            print(f"❌ AI 侦察兵请求异常: {str(e)}")
            # 🌟 fail-preserve：网络/配额异常同样保留原池，防止 API 故障时不合格岗位整批漏进待推送池
            await push_sse_message(sse_task_id, f"⚠️ AI 请求异常（{str(e)[:80]}），本轮保留该岗位在待AI初筛池", status="error")
            return {"status": "PRESERVE", "reject_reason": None}

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
            f"WHERE process_status = '已存入数据' AND ({city_not_like}) AND ({address_not_like}) AND {target_condition}",
            params
        )

def _filter_empty_details(cursor, target_condition, target_links):
    cursor.execute(f"UPDATE raw_jobs SET publish_date = REPLACE(publish_date, '更新于 ', '') WHERE platform = '智联招聘' AND {target_condition}", target_links)
    cursor.execute(
        f"UPDATE raw_jobs SET process_status = '清洗淘汰', reject_reason = '岗位详情为空' "
        f"WHERE process_status = '已存入数据' AND (jd_text IS NULL OR TRIM(jd_text) = '') AND {target_condition}",
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
            f"WHERE process_status = '已存入数据' AND ({edu_conditions}) AND {target_condition}",
            params
        )

def _filter_experience(cursor, strategy, target_condition, target_links):
    experience_years_max = strategy.get("experience_years_max", 7)
    cursor.execute(f"SELECT job_link, experience_req, jd_text FROM raw_jobs WHERE process_status = '已存入数据' AND {target_condition}", target_links)
    exp_rejects = [(lk,) for lk, exp, jd in cursor.fetchall() if is_experience_rejected(exp, jd, experience_years_max)]
    if exp_rejects:
        cursor.executemany(f"UPDATE raw_jobs SET process_status = '清洗淘汰', reject_reason = '要求资历过高(≥{experience_years_max}年)' WHERE job_link = ?", exp_rejects)

def _filter_salary(cursor, strategy, target_condition, target_links):
    min_salary_k = strategy.get("min_salary_k", 10)
    max_salary_k = strategy.get("max_salary_k", 25)
    cursor.execute(f"SELECT job_link, salary FROM raw_jobs WHERE process_status = '已存入数据' AND {target_condition}", target_links)
    salary_rejects = [(lk,) for lk, sal in cursor.fetchall() if is_salary_rejected(sal, min_salary_k, max_salary_k)]
    if salary_rejects:
        cursor.executemany("UPDATE raw_jobs SET process_status = '清洗淘汰', reject_reason = '薪资区间不符' WHERE job_link = ?", salary_rejects)

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
    cursor.execute(f"SELECT job_link, job_title, experience_req FROM raw_jobs WHERE process_status = '已存入数据' AND {target_condition}", target_links)
    kw_rejects = []
    for lk, title, exp in cursor.fetchall():
        reason = _check_keyword_rejects(title, exp, keyword_rules)
        if reason:
            kw_rejects.append((reason, lk))
    if kw_rejects:
        cursor.executemany("UPDATE raw_jobs SET process_status = '清洗淘汰', reject_reason = ? WHERE job_link = ?", kw_rejects)

async def _run_tier2_ai_scout(cursor, conn, strategy, sse_task_id, limit, target_links=None):
    print("🤖 [阶段二] 开始执行 AI 侦察兵排雷...")
    engine = AIScoutEngine(strategy)
    
    if target_links:
        # 精准闭环：优先处理本轮硬过滤锁定的岗位中进入「待AI初筛」的记录
        pending_jobs = []
        chunk_size = 500
        for i in range(0, len(target_links), chunk_size):
            chunk = target_links[i:i + chunk_size]
            placeholders = ','.join(['?'] * len(chunk))
            cursor.execute(f"SELECT job_link, job_title, jd_text, company_name FROM raw_jobs WHERE process_status = '待AI初筛' AND job_link IN ({placeholders})", chunk)
            pending_jobs.extend(cursor.fetchall())
        if limit and limit > 0:
            pending_jobs = pending_jobs[:limit]
    else:
        query = "SELECT job_link, job_title, jd_text, company_name FROM raw_jobs WHERE process_status = '待AI初筛'"
        if limit and limit > 0:
            query += f" LIMIT {limit}"
        cursor.execute(query)
        pending_jobs = cursor.fetchall()

    if pending_jobs:
        await push_sse_message(sse_task_id, f"Tier 1 清洗完毕，有 {len(pending_jobs)} 个岗位进入 Tier 2: AI 侦察兵排雷 (并发=5)")

    if not pending_jobs:
        return

    sem = asyncio.Semaphore(5)
    total = len(pending_jobs)
    completed_count = 0
    passed_count = 0
    rejected_count = 0
    await push_sse_event(sse_task_id, {"type": "phase_progress", "phase": "ai_scout", "current": 0, "total": total, "passed": 0, "rejected": 0})

    async def _eval_one(idx: int, job_link, job_title, jd_text, company_name):
        nonlocal completed_count, passed_count, rejected_count
        if get_stop_flag():
            print(f"🛑 [AI排雷急刹] 收到终止信号，跳过后续岗位: {job_title}")
            return ('待AI初筛', '任务已手动终止', job_link)
        async with sem:
            if get_stop_flag():
                print(f"🛑 [AI排雷急刹] 信号生效，跳过未评估岗位: {job_title}")
                return ('待AI初筛', None, job_link)
            print(f"\n🔍 [AI排雷] {idx+1}/{total}: {company_name} - {job_title}", flush=True)
            await push_sse_message(sse_task_id, f"🔍 开始评估: {company_name} - {job_title}")
            res = await engine.evaluate_job(job_title, jd_text, company_name, sse_task_id)

            # 🌟 急刹二次确认：若在网络请求等待期间收到了终止信号，坚决放弃本次流转，保留在待AI初筛池！
            if get_stop_flag():
                print(f"🛑 [AI排雷急刹] 推理中途收到终止信号，废弃中途结果，严格保留在待AI初筛池: {company_name} - {job_title}", flush=True)
                return ('待AI初筛', None, job_link)

            if res['status'] == 'PRESERVE':
                # 🌟 fail-preserve：解析失败/API 异常，不计通过也不计拦截，保留原池下轮重试
                print(f"↩️ [Tier 2 AI排雷保留] 【{job_title}】 -> 模型输出异常，保留在待AI初筛池等待重试", flush=True)
                completed_count += 1
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
                final_status = 'ai清洗淘汰'
                rejected_count += 1
                print(f"🚫 [Tier 2 AI排雷淘汰] 【{job_title}】 -> 死因: {res['reject_reason']}", flush=True)
                await push_sse_message(sse_task_id, f"🚫 {company_name} - {job_title}: {res['reject_reason']}", status="error")
            else:
                final_status = '待推送至飞书'
                passed_count += 1
                print(f"✅ 侦察兵放行: {company_name} - {job_title}", flush=True)
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

    tasks = [
        _eval_one(i, job_link, job_title, jd_text, company_name)
        for i, (job_link, job_title, jd_text, company_name) in enumerate(pending_jobs)
    ]
    update_data = await asyncio.gather(*tasks)

    # 🌟 仅真正被 AI 判定完成（ai清洗淘汰 或 待推送至飞书）的岗位才落库，未完成/中止的岗位保持原状（待AI初筛）
    changed_data = [d for d in update_data if d[0] != '待AI初筛']
    if changed_data:
        cursor.executemany("UPDATE raw_jobs SET process_status = ?, reject_reason = ? WHERE job_link = ?", changed_data)
        conn.commit()
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
    passed = status_counts.get('待推送至飞书', 0) + status_counts.get('已推送飞书', 0)
    
    report_data = {
        "total_processed": total_processed,
        "passed": passed,
        "hard_rejected": hard_rejected,
        "ai_rejected": ai_rejected
    }
    await push_sse_event(sse_task_id, {"type": "cleaning_report", "data": report_data})
    await push_sse_message(sse_task_id, f"📊 清洗报告: 共处理 {total_processed} 条 -> 最终通过 {passed} 条 (硬规则拦截 {hard_rejected} 条, AI 拦截 {ai_rejected} 条)")


def _run_tier1_hard_filter(cursor, conn, strategy, target_links):
    """同步执行 Tier 1 绝对硬指标过滤核心逻辑，将合格岗位推进为「待AI初筛」，不合格为「清洗淘汰」"""
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
            await push_sse_event(sse_task_id, {"type": "phase_progress", "phase": "hard_clean", "current": 0, "total": len(target_links) if target_links else 1})
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
                "current": len(target_links) if target_links else 1, 
                "total": len(target_links) if target_links else 1,
                "passed": passed_count,
                "rejected": rejected_count
            })
            await push_sse_message(sse_task_id, f"🎉 Tier 1 硬规则清洗完成！合格通过: {passed_count} 条 (已进入待AI清洗池)，规则拦截淘汰: {rejected_count} 条")
            return {"total": len(target_links), "passed": passed_count, "rejected": rejected_count}
        finally:
            conn.close()

async def _async_run_ai_scout_only(sse_task_id=None, limit=None):
    """仅执行阶段二：Tier 2 AI 深度排雷（消耗 Token），对现存「待AI初筛」执行大模型排雷"""
    async with GLOBAL_CLEAN_LOCK:
        set_stop_flag(False)
        strategy = _get_active_strategy()
        conn = sqlite3.connect(DB_PATH, timeout=30.0)
        try:
            cursor = conn.cursor()
            query = "SELECT job_link FROM raw_jobs WHERE process_status = '待AI初筛' ORDER BY rowid DESC"
            if limit and limit > 0:
                query += f" LIMIT {limit}"
            cursor.execute(query)
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

async def _async_run_pipeline(sse_task_id=None, limit=None, min_rowid=0):
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
            if min_rowid:
                query_target += f" AND rowid > {int(min_rowid)}"
            query_target += " ORDER BY rowid DESC"
            if limit and limit > 0:
                query_target += f" LIMIT {limit}"
            cursor.execute(query_target)
            target_links = [r[0] for r in cursor.fetchall()]

            print(f"🧹 [联合清洗] 执行数据清洗 (Tier 1 硬性规则) - 本轮处理 {len(target_links)} 条...")
            await push_sse_event(sse_task_id, {"type": "phase_progress", "phase": "hard_clean", "current": 0, "total": len(target_links) if target_links else 1})
            await push_sse_message(sse_task_id, f"开始执行 Tier 1: 绝对硬指标清洗 (本轮锁定 {len(target_links)} 条)")

            if target_links:
                _run_tier1_hard_filter(cursor, conn, strategy, target_links)

            tier1_passed = 0
            if target_links:
                ph = ','.join(['?'] * len(target_links))
                cursor.execute(f"SELECT COUNT(*) FROM raw_jobs WHERE process_status = '待AI初筛' AND job_link IN ({ph})", target_links)
                tier1_passed = cursor.fetchone()[0]
            tier1_rejected = len(target_links) - tier1_passed

            await push_sse_event(sse_task_id, {
                "type": "phase_progress", 
                "phase": "hard_clean", 
                "current": len(target_links) if target_links else 1, 
                "total": len(target_links) if target_links else 1,
                "passed": tier1_passed,
                "rejected": tier1_rejected
            })

            if get_stop_flag():
                print("🛑 [清洗急刹] 在阶段一完成后收到终止信号，跳过阶段二 AI 评估。")
                await push_sse_message(sse_task_id, "🛑 任务已被手动终止，阶段二 AI 排雷已取消", "warning")
                return []

            await _run_tier2_ai_scout(cursor, conn, strategy, sse_task_id, limit, target_links=target_links)
            await _generate_cleaning_report(cursor, sse_task_id, target_links)

            # 🌟 获取本轮真正通过 AI 初筛、进入「待推送至飞书」的岗位列表，供下游精确推送
            passed_links = []
            if target_links:
                ph = ','.join(['?'] * len(target_links))
                cursor.execute(f"SELECT job_link FROM raw_jobs WHERE process_status = '待推送至飞书' AND job_link IN ({ph})", target_links)
                passed_links = [r[0] for r in cursor.fetchall()]
            return passed_links
        finally:
            conn.close()

if __name__ == "__main__":
    run_pipeline()