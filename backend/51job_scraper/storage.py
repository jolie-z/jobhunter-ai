"""51job 采集持久化层 — raw_jobs 入库 + 去重 + 城市/薪资代码字典（collector 拆分模块）。

拆分原因（plan §3.3 文件解耦表，plan-review R1 P1）：51job_collector.py 作为编排入口
控制在 500 行以内。字段契约不变：raw_jobs 19 列 INSERT 语句是唯一权威
（data/job_hunter.db，飞书同步链路零感知）。
"""
import datetime
import os
import sqlite3

_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(_CURRENT_DIR)
DB_PATH = os.path.join(PARENT_DIR, 'data', 'job_hunter.db')

# 51job 城市代码字典
CITY_CODE_MAP = {
    "广州": "030200",
    "深圳": "040000",
    "杭州": "080200",
    "北京": "010000",
    "上海": "020000",
    "成都": "090200",
    "南京": "070200",
    "武汉": "180200"
}

# 51job 薪资代码字典 (包含你找出的所有规律，并兼容 K 的写法)
SALARY_CODE_MAP = {
    "8千以下": "201",
    "0.8-1万": "06",
    "8-10K": "06",
    "1-1.5万": "07",
    "1万-1.5万": "07",
    "10-15K": "07",
    "1.5-2万": "08",
    "1.5万-2万": "08",
    "15-20K": "08",
    "2-3万": "09",
    "2万-3万": "09",
    "20-30K": "09",
    "3-4万": "10",
    "3万-4万": "10",
    "30-40K": "10",
    "4-5万": "11",
    "4万-5万": "11",
    "40-50K": "11",
    "不限": ""
}

def get_city_code(city_name):
    """根据飞书配置的城市名匹配代码，默认为全国(000000)"""
    for name, code in CITY_CODE_MAP.items():
        if name in city_name:
            return code
    return "000000"

def get_salary_code(salary_text):
    """提取薪资代码，支持多选（自动拼凑 %2C）"""
    if not salary_text or "不限" in salary_text:
        return ""

    codes = set()
    # 遍历字典，如果飞书填写的文本包含了字典里的词，就收集对应的代码
    for key, code in SALARY_CODE_MAP.items():
        if key in salary_text:
            codes.add(code)

    if codes:
        # 将收集到的所有代码去重、排序，然后用 %2C 拼接（例如：07%2C08）
        return "%2C".join(sorted(codes))

    return ""

def save_to_raw_db(job_data):
    """将数据安全写入 SQLite，并强制写入本地精确时间"""
    try:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        conn = sqlite3.connect(DB_PATH, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL;")
        cursor = conn.cursor()

        # 🌟 获取本地的当前准确时间，避免数据库使用 UTC 默认时间
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        cursor.execute('''
            INSERT OR IGNORE INTO raw_jobs (
                job_link, job_title, company_name, city, jd_text,
                salary, work_address, hr_activity, industry, welfare_tags,
                company_size, education_req, experience_req, hr_skill_tags,
                company_intro, role, publish_date, platform, crawl_time
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            job_data.get('job_link'), job_data.get('job_title'),
            job_data.get('company_name'), job_data.get('city'),
            job_data.get('jd_text'), job_data.get('salary'),
            job_data.get('work_address'), job_data.get('hr_activity'),
            job_data.get('industry'), job_data.get('welfare_tags'),
            job_data.get('company_size'), job_data.get('education_req'),
            job_data.get('experience_req'), job_data.get('hr_skill_tags'),
            job_data.get('company_intro'), job_data.get('role'),
            job_data.get('publish_date'), '51job', current_time # 🌟 写入正确的爬取时间
        ))
        inserted = cursor.rowcount > 0
        conn.commit()
        conn.close()
        return inserted
    except Exception as e:
        print(f"      ❌ 数据库写入失败: {e}")
        return False

def check_exists(company, title, city):
    """前置去重检查"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT 1 FROM raw_jobs WHERE company_name=? AND job_title=? AND city=?', (company, title, city))
        exists = cursor.fetchone() is not None
        conn.close()
        return exists
    except Exception:
        return False
