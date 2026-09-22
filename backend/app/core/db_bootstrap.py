# app/core/db_bootstrap.py
"""
主库（job_hunter.db）统一建表引导 —— 全新装配「用到就有」保障。

背景（2026-09-22 新机器公开仓装配排查）：
backend/data/ 被 gitignore，全新克隆既没有目录也没有 job_hunter.db；而历史缺口表
（raw_jobs / job_strategies / xhs_raw_posts）在生产代码里没有启动建表点（raw_jobs 仅
极速录入回写时懒建，job_strategies 与 xhs_raw_posts 全代码零建表），导致战报
「no such table: raw_jobs」、/goals/current 查询失败、小红书爬虫写入失败等新机装配故障。

本模块把生产库 sqlite_master 的全部表/索引/触发器 DDL 镜像为幂等引导脚本，应用启动时
执行一遍：已存在的对象原样跳过（IF NOT EXISTS），缺的补建，绝不触碰已有数据。
各业务模块自带的惰性 ensure_table 全部保留，作为双保险。

注意：主库路径解析的唯一真源是本模块 resolve_main_db_path()；goal_service.DB_PATH 是
它 import 期冻结的快照。启动引导（main.py）显式传 goal_service.DB_PATH 进
ensure_main_db_schema(db_path)，与业务模块共用同一个 import 期时机，杜绝两套解析
各建各库；改路径口径只改 resolve_main_db_path。
"""
import logging
import os
import re
import sqlite3

logger = logging.getLogger(__name__)

# 生产库（老机器）sqlite_master 全量镜像。改动表结构时：先改生产迁移，再同步此蓝本。
BOOTSTRAP_SCRIPT = """
CREATE TABLE IF NOT EXISTS custom_model_pricing (
    model_name TEXT PRIMARY KEY,
    prompt_rate REAL NOT NULL,        -- 元 / 1M tokens
    cached_prompt_rate REAL NOT NULL, -- 元 / 1M tokens
    completion_rate REAL NOT NULL,    -- 元 / 1M tokens
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evaluation_weights (
    dimension TEXT PRIMARY KEY,
    weight REAL
);
CREATE TABLE IF NOT EXISTS job_goals (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    start_date TEXT NOT NULL,
    end_date TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    daily_deliver_target INTEGER DEFAULT 10,
    daily_crawl_target INTEGER DEFAULT 50,
    weekly_interview_target INTEGER DEFAULT 3,
    a_grade_deadline_hours INTEGER DEFAULT 24,
    total_offer_target INTEGER DEFAULT 1,
    plan_days INTEGER DEFAULT 60,
    report_time_daily TEXT DEFAULT '21:00',
    report_time_weekly TEXT DEFAULT '09:00',
    report_time_monthly TEXT DEFAULT '09:00',
    report_enabled_daily INTEGER DEFAULT 1,
    report_enabled_weekly INTEGER DEFAULT 1,
    report_enabled_monthly INTEGER DEFAULT 1,
    feishu_receive_id TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS job_preferences (
    record_id TEXT PRIMARY KEY,
    type TEXT,
    rule TEXT,
    status TEXT
);
CREATE TABLE IF NOT EXISTS job_strategies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_name TEXT NOT NULL,
    is_active INTEGER DEFAULT 0,
    min_salary_k INTEGER,
    max_salary_k INTEGER,
    experience_years_max INTEGER,
    exclude_education TEXT,
    allowed_cities TEXT,
    safe_phrases TEXT,
    keyword_rules TEXT,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    ai_scout_rules TEXT,
    require_education TEXT,
    veto_keywords TEXT DEFAULT '[]',
    positive_keywords TEXT DEFAULT '[]',
    llm_prompt_preference TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS pipeline_keyword_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword TEXT NOT NULL,
    city TEXT NOT NULL DEFAULT '',
    salary TEXT NOT NULL DEFAULT '',
    jobs_added INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'auto',
    pipeline_task_id TEXT NOT NULL DEFAULT '',
    used_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS pipeline_latest_run (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    task_id TEXT,
    start_rowid INTEGER,
    budgets_json TEXT,
    disabled_json TEXT,
    running INTEGER,
    started INTEGER,
    record_ids_json TEXT,
    dismissed_ids_json TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    delivery_failures_json TEXT DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS pipeline_scrape_config (
    id INTEGER PRIMARY KEY DEFAULT 1,
    keywords TEXT NOT NULL DEFAULT '[]',
    platforms TEXT NOT NULL DEFAULT '{}',
    default_city TEXT NOT NULL DEFAULT '',
    default_salary TEXT NOT NULL DEFAULT '',
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS raw_jobs (
    -- A. 基础采集维度
    job_link TEXT PRIMARY KEY,               -- 岗位链接 (全网唯一标识)
    job_title TEXT,                          -- 岗位名称
    company_name TEXT,                       -- 公司名称
    city TEXT,                               -- 城市
    jd_text TEXT,                            -- 岗位详情 (LLM 评估的核心语料)
    salary TEXT,                             -- 薪资描述
    work_address TEXT,                       -- 精确上班地址
    hr_activity TEXT,                        -- HR 活跃度
    industry TEXT,                           -- 所属行业
    welfare_tags TEXT,                       -- 福利标签
    company_size TEXT,                       -- 公司规模
    education_req TEXT,                      -- 学历要求
    experience_req TEXT,                     -- 经验要求
    hr_skill_tags TEXT,                      -- HR 技能标签
    company_intro TEXT,                      -- 公司介绍
    role TEXT,                               -- 招聘者角色 (HR/经理/猎头)
    publish_date TEXT,                       -- 岗位发布/更新日期
    platform TEXT,                           -- 招聘平台 (Boss/51job/Liepin)
    crawl_time DATETIME DEFAULT (datetime('now', 'localtime')), -- 抓取时间
    -- B. 业务逻辑与状态流转维度
    process_status TEXT DEFAULT '已存入数据',
    reject_reason TEXT,                      -- 详细淘汰原因
    is_synced INTEGER DEFAULT 0,
    feishu_record_id TEXT DEFAULT '',
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS scrape_sessions (
    keyword     TEXT    NOT NULL,
    city        TEXT    NOT NULL DEFAULT '',
    salary      TEXT    NOT NULL DEFAULT '',
    platform    TEXT    NOT NULL,
    last_page   INTEGER NOT NULL DEFAULT 1,
    last_run    TEXT,
    predicted_total INTEGER NOT NULL DEFAULT 0,
    scraped_count INTEGER NOT NULL DEFAULT 0,
    ttl_updated_at TEXT DEFAULT '',
    PRIMARY KEY (keyword, city, salary, platform)
);
CREATE TABLE IF NOT EXISTS token_log (
    id TEXT PRIMARY KEY,
    action_name TEXT NOT NULL,
    job_id TEXT,
    prompt_tokens INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    model_name TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    caller TEXT DEFAULT '',
    cost_cny REAL DEFAULT 0,
    estimated INTEGER DEFAULT 0,
    cached_tokens INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS xhs_raw_posts (
    post_link TEXT PRIMARY KEY,
    account_name TEXT,
    raw_text TEXT,
    image_urls TEXT,
    video_urls TEXT,
    crawl_time DATETIME DEFAULT (datetime('now', 'localtime')),
    clean_status TEXT DEFAULT 'PENDING',
    publish_date TEXT,
    note_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_raw_jobs_status ON raw_jobs(process_status, is_synced);
CREATE INDEX IF NOT EXISTS idx_raw_jobs_platform ON raw_jobs(platform, process_status);
CREATE INDEX IF NOT EXISTS idx_raw_jobs_feishu_rid ON raw_jobs(feishu_record_id);
CREATE INDEX IF NOT EXISTS idx_raw_jobs_company_title_city ON raw_jobs(company_name, job_title, city);
CREATE INDEX IF NOT EXISTS idx_token_log_created ON token_log(created_at);
CREATE INDEX IF NOT EXISTS idx_token_log_action ON token_log(action_name);
CREATE INDEX IF NOT EXISTS idx_token_log_model ON token_log(model_name);
CREATE INDEX IF NOT EXISTS idx_xhs_raw_posts_clean_status ON xhs_raw_posts(clean_status);
CREATE TRIGGER IF NOT EXISTS trg_raw_jobs_insert_updated
AFTER INSERT ON raw_jobs
FOR EACH ROW
BEGIN
    UPDATE raw_jobs SET updated_at = COALESCE(NEW.crawl_time, datetime('now', 'localtime')) WHERE rowid = NEW.rowid;
END;
CREATE TRIGGER IF NOT EXISTS trg_raw_jobs_status_updated
AFTER UPDATE OF process_status ON raw_jobs
FOR EACH ROW
BEGIN
    UPDATE raw_jobs SET updated_at = datetime('now', 'localtime') WHERE rowid = OLD.rowid;
END;
"""


def resolve_main_db_path() -> str:
    """解析主库路径——全仓唯一真源，goal_service.DB_PATH 直接复用本函数。

    口径与 goal_service 历史行为逐字一致（勿改语义）：
    - ANALYTICS_DB_PATH：显式覆盖，即使文件尚不存在也采纳（QA 隔离栈先指路径后建库）；
    - MAIN_PROJECT_DB：遗留外部主库开关，仅当文件已存在才采纳；
    - 缺省：仓内 backend/data/job_hunter.db。
    """
    main_project_db = os.environ.get("MAIN_PROJECT_DB", "")
    local_db = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "data", "job_hunter.db",
    )
    analytics_db = os.environ.get("ANALYTICS_DB_PATH")
    if analytics_db:
        return analytics_db
    if main_project_db and os.path.exists(main_project_db):
        return main_project_db
    return local_db


def _user_objects(conn: sqlite3.Connection) -> set[str]:
    """业务对象名（table/index/trigger/view），排除 sqlite_autoindex/sqlite_sequence 等内部对象。"""
    return {
        row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type IN ('table','index','trigger','view') AND name NOT LIKE 'sqlite_%'"
        )
    }


def _split_statements(script: str) -> list[str]:
    """按 sqlite3.complete_statement 切分 DDL——触发器 BEGIN...END 体内含分号，
    complete_statement 对触发器有感知（体内分号不算完整，须等 END;），实测可证。

    注释语义（实测）：complete_statement 按 SQLite 分词规则跳过 `--` 注释，
    注释内的分号不会触发误切（实证见 tests/test_db_bootstrap.py）；但为可读性
    起见，蓝本注释仍避免写分号。"""
    statements: list[str] = []
    buf = ""
    for line in script.splitlines(keepends=True):
        buf += line
        if sqlite3.complete_statement(buf):
            stmt = buf.strip()
            if stmt:
                statements.append(stmt)
            buf = ""
    if buf.strip():
        statements.append(buf.strip())
    return statements


def _pre_existing_table_columns(conn: sqlite3.Connection) -> dict[str, set[str]]:
    """引导前已存在的表 → 当前列集（用于识别历史窄表）。"""
    return {
        row[0]: {c[1] for c in conn.execute(f'PRAGMA table_info("{row[0]}")')}
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }


def _trigger_target_table(stmt: str) -> str | None:
    """从 CREATE TRIGGER DDL 里取目标表名（... ON <table>）。"""
    m = re.search(r"\bON\s+[\"']?(\w+)", stmt, re.IGNORECASE)
    return m.group(1) if m else None


def _derive_blueprint_table_columns() -> dict[str, set[str]]:
    """从蓝本自身派生「表 → 列集」（:memory: 执行一次），供窄表触发器守卫比对。

    自蓝本派生而非手抄：蓝本改列时守卫口径自动跟进，不产生第二份需要人工同步的清单。
    """
    mem = sqlite3.connect(":memory:")
    try:
        for stmt in _split_statements(BOOTSTRAP_SCRIPT):
            mem.execute(stmt)
        return {
            row[0]: {c[1] for c in mem.execute(f'PRAGMA table_info("{row[0]}")')}
            for row in mem.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    finally:
        mem.close()


# 蓝本列集（import 期派生一次；进程内蓝本为常量，无失效问题）
BLUEPRINT_TABLE_COLUMNS = _derive_blueprint_table_columns()


def ensure_main_db_schema(db_path: str | None = None) -> list[str]:
    """幂等补齐主库全部表/索引/触发器，返回本次实际新建的对象名。

    全新克隆连 backend/data/ 目录都不存在（gitignore 掉了整个目录），sqlite3.connect
    只建文件不建父目录，所以这里必须先 makedirs，否则各惰性建表会直接
    「unable to open database file」。

    逐条执行、单条失败记警告继续：若库里已有历史窄表缺蓝本索引的列（如旧版懒建的
    token_log 没有 created_at），对应索引跳过即可，不能卡死整个引导。

    触发器特殊：SQLite 不预校验触发器体内列名，历史窄表上「带病创建」会让后续
    每次 INSERT 到触发器执行时才爆缺列——把原本可用的写路径改成必失败且无告警。
    因此对「引导前已存在、列集窄于蓝本」的表跳过其触发器（与索引容错同口径），
    并记入 skipped 留痕；表补齐列后下一次引导会自动补建触发器。
    """
    path = db_path or resolve_main_db_path()
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    conn = sqlite3.connect(path, timeout=10.0)
    # TODO(债): 单条语句 busy timeout 10s，库被长事务持锁时最坏逐条串行等待；
    # 后续可收紧单条超时或加全局引导超时（逐条容错设计本身保留：旧窄表只跳过缺索引，不整体失败）
    skipped: list[str] = []
    try:
        # 与 goal_service._get_conn 同款：主库在线上本就以 WAL 运行，非本批新增行为
        conn.execute("PRAGMA journal_mode=WAL")
        before = _user_objects(conn)
        pre_existing_cols = _pre_existing_table_columns(conn)
        for stmt in _split_statements(BOOTSTRAP_SCRIPT):
            # 触发器防带病创建：目标表在引导前已存在且缺蓝本列（历史窄表）→ 跳过，
            # 否则 SQLite 会照建不误、把写失败延迟到业务 INSERT 时才爆
            if stmt.upper().lstrip().startswith("CREATE TRIGGER"):
                target = _trigger_target_table(stmt)
                existing_cols = pre_existing_cols.get(target or "")
                if existing_cols is not None:
                    blueprint_cols = BLUEPRINT_TABLE_COLUMNS.get(target or "")
                    if blueprint_cols and blueprint_cols - existing_cols:
                        m = re.search(
                            r"TRIGGER\s+(?:IF\s+NOT\s+EXISTS\s+)?[\"']?(\w+)",
                            stmt, re.IGNORECASE,
                        )
                        trg_name = m.group(1) if m else stmt[:50]
                        skipped.append(trg_name)
                        logger.warning(
                            f"⚠️ [db_bootstrap] 触发器跳过（历史窄表 {target} 缺列 "
                            f"{sorted(blueprint_cols - existing_cols)}，防带病创建）: {trg_name}"
                        )
                        continue
            try:
                conn.execute(stmt)
            except sqlite3.Error as e:
                # skipped 清单取对象名（触发器体内无圆括号，切前缀会带换行），便于定位
                m = re.search(
                    r"(?:TABLE|INDEX|TRIGGER)\s+(?:IF\s+NOT\s+EXISTS\s+)?[\"']?(\w+)",
                    stmt, re.IGNORECASE,
                )
                skipped.append(m.group(1) if m else stmt[:50])
                logger.warning(f"⚠️ [db_bootstrap] 语句跳过（{e}）: {stmt[:60]}...")
        conn.commit()
        after = _user_objects(conn)
    finally:
        conn.close()
    created = sorted(after - before)
    if created:
        logger.info(f"✅ [db_bootstrap] 主库建表引导完成，本次新建: {created}")
    if skipped:
        logger.warning(f"⚠️ [db_bootstrap] 共 {len(skipped)} 条语句未就绪: {skipped}")
    return created
