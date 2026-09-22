# tests/test_db_bootstrap.py
"""主库统一建表引导 + goals/update 缺行自动建档（2026-09-22 新机装配排查批）。

全新克隆无 backend/data/job_hunter.db（gitignore 整目录）：
- 引导须在父目录缺失时也能建库，且幂等、绝不触碰已有表/数据；
- update_goals 无目标行时按默认值自动建档，保存接收群不再依赖先手动 /start。

蓝本漂移防线：蓝本是生产库 sqlite_master 的人工镜像，各业务模块又自带惰性 DDL
（CREATE TABLE IF NOT EXISTS）——引导先建表后，模块 DDL 永远静默跳过，蓝本一旦
落后于模块 DDL（少列窄表）就会复现「no such column」类新机故障。因此必须有
test_bootstrap_columns_cover_module_ddl：重叠表锁「蓝本列集 ⊇ 模块列集」，并对
「模块表不在蓝本」做跨库白名单对账，堵住主库新表漏配蓝本的缺口。
"""
import re
import sqlite3
from contextlib import closing
from pathlib import Path

from app.core.db_bootstrap import (
    BLUEPRINT_TABLE_COLUMNS,
    BOOTSTRAP_SCRIPT,
    _split_statements,
    ensure_main_db_schema,
    resolve_main_db_path,
)
from app.services import goal_service

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = str(BACKEND_ROOT / "data" / "job_hunter.db")

EXPECTED_TABLES = {
    "custom_model_pricing", "evaluation_weights", "job_goals", "job_preferences",
    "job_strategies", "pipeline_keyword_history", "pipeline_latest_run",
    "pipeline_scrape_config", "raw_jobs", "scrape_sessions", "token_log", "xhs_raw_posts",
}
EXPECTED_TRIGGERS = {"trg_raw_jobs_insert_updated", "trg_raw_jobs_status_updated"}

# 拥有模块 DDL 但合法不属于主库蓝本的表（分属 autopilot.db / 会话库等其它库）。
# 模块表若既不在蓝本、又不在此白名单，说明主库新表漏配蓝本——正是「no such table」
# 类全新装配故障（引导只建蓝本里的表，漏配的表在新机上无人创建）。
CROSS_DB_TABLES = {
    "automation_configs", "automation_logs", "pending_delivery_pool",
    "boss_approvals", "platform_status", "sessions",
}


def _object_names(db_path: str, types: tuple[str, ...]) -> set[str]:
    with closing(sqlite3.connect(db_path)) as conn:
        marks = ",".join("?" * len(types))
        return {r[0] for r in conn.execute(
            f"SELECT name FROM sqlite_master WHERE type IN ({marks})", types)}


def test_ensure_main_db_schema_fresh_creates_all(tmp_path):
    # 父目录也不存在，模拟全新克隆：验证 makedirs + 全量建表/触发器
    db_path = str(tmp_path / "sub" / "fresh.db")
    created = ensure_main_db_schema(db_path)

    assert EXPECTED_TABLES <= _object_names(db_path, ("table",))
    assert EXPECTED_TRIGGERS <= _object_names(db_path, ("trigger",))
    assert EXPECTED_TABLES <= set(created)


def test_ensure_main_db_schema_idempotent(tmp_path):
    db_path = str(tmp_path / "fresh.db")
    ensure_main_db_schema(db_path)
    # 第二遍不该再新建任何对象
    assert ensure_main_db_schema(db_path) == []


def test_ensure_main_db_schema_preserves_existing_table(tmp_path):
    # 已有表（哪怕列更少）原样保留，引导绝不替换/重建
    db_path = str(tmp_path / "old.db")
    with closing(sqlite3.connect(db_path)) as conn:
        conn.execute("CREATE TABLE token_log (id TEXT PRIMARY KEY, action_name TEXT NOT NULL)")
        conn.execute("INSERT INTO token_log VALUES ('t1', 'eval')")
        conn.commit()

    ensure_main_db_schema(db_path)

    with closing(sqlite3.connect(db_path)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM token_log").fetchone()[0] == 1
        cols = {r[1] for r in conn.execute("PRAGMA table_info(token_log)")}
        assert "cost_cny" not in cols  # 旧结构未被替换成蓝本新结构


def test_raw_jobs_trigger_maintains_updated_at(tmp_path):
    db_path = str(tmp_path / "fresh.db")
    ensure_main_db_schema(db_path)
    with closing(sqlite3.connect(db_path)) as conn:
        conn.execute(
            "INSERT INTO raw_jobs (job_link, crawl_time) VALUES ('u1', '2026-09-22 10:00:00')")
        row = conn.execute("SELECT updated_at FROM raw_jobs WHERE job_link = 'u1'").fetchone()
        assert row[0] == "2026-09-22 10:00:00"


def test_narrow_raw_jobs_preserved_and_trigger_skipped(tmp_path):
    # 历史窄 raw_jobs（缺 updated_at）：引导绝不 crash/替换重建，窄表数据原样保留，
    # 且触发器必须被守卫跳过——SQLite 建触发器不校验体内列名，若放任带病创建，
    # 该表原本可用的 INSERT 会在触发器执行时爆缺列（引导反把好路径改坏）
    db_path = str(tmp_path / "narrow.db")
    with closing(sqlite3.connect(db_path)) as conn:
        conn.execute("CREATE TABLE raw_jobs (job_link TEXT PRIMARY KEY, crawl_time TEXT)")
        conn.execute("INSERT INTO raw_jobs VALUES ('u1', '2026-09-22 10:00:00')")
        conn.commit()

    ensure_main_db_schema(db_path)  # 不得抛异常

    with closing(sqlite3.connect(db_path)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM raw_jobs").fetchone()[0] == 1
        triggers = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
        assert not (EXPECTED_TRIGGERS & triggers)  # 窄表触发器被守卫跳过，绝不带病创建
        conn.execute("INSERT INTO raw_jobs VALUES ('u2', '2026-09-23 09:00:00')")  # 写路径保持可用


def test_narrow_table_trigger_backfills_after_column_added(tmp_path):
    # 窄表补齐缺失列后，下一次引导应自动补建触发器（守卫只挡「当前缺列」，不永久拉黑）
    db_path = str(tmp_path / "narrow_then_fixed.db")
    # 构造除 updated_at 外与蓝本同列的窄表
    cols = sorted(BLUEPRINT_TABLE_COLUMNS["raw_jobs"] - {"updated_at"})
    col_defs = ", ".join(f"{c} TEXT PRIMARY KEY" if c == "job_link" else f"{c} TEXT" for c in cols)
    with closing(sqlite3.connect(db_path)) as conn:
        conn.execute(f"CREATE TABLE raw_jobs ({col_defs})")
        conn.commit()

    ensure_main_db_schema(db_path)
    with closing(sqlite3.connect(db_path)) as conn:
        assert not (EXPECTED_TRIGGERS & {
            r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")})
        conn.execute("ALTER TABLE raw_jobs ADD COLUMN updated_at TEXT")
        conn.commit()

    ensure_main_db_schema(db_path)
    with closing(sqlite3.connect(db_path)) as conn:
        assert EXPECTED_TRIGGERS <= {
            r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}


def test_update_goals_autocreates_row_when_missing(tmp_path, monkeypatch):
    db_path = str(tmp_path / "goals.db")
    monkeypatch.setattr(goal_service, "DB_PATH", db_path)
    ensure_main_db_schema(db_path)  # 生产中启动引导先行，测试对齐同一起点

    result = goal_service.update_goals({"feishu_receive_id": "oc_test"})

    assert result is not None
    assert result["feishu_receive_id"] == "oc_test"
    assert result["status"] == "active"


def test_update_goals_partial_keeps_other_fields(tmp_path, monkeypatch):
    db_path = str(tmp_path / "goals.db")
    monkeypatch.setattr(goal_service, "DB_PATH", db_path)
    ensure_main_db_schema(db_path)

    goal_service.update_goals({"feishu_receive_id": "oc_a", "plan_days": 30})
    result = goal_service.update_goals({"plan_days": 90})

    assert result["plan_days"] == 90
    assert result["feishu_receive_id"] == "oc_a"  # 部分更新不重置其他字段


def test_split_statements_keeps_trigger_body_intact():
    # 触发器 BEGIN...END 体内的分号不得切碎语句（切碎会导致表/触发器残缺）
    script = (
        "CREATE TABLE t (a TEXT);\n"
        "CREATE TRIGGER trg AFTER INSERT ON t FOR EACH ROW\n"
        "BEGIN\n"
        "    UPDATE t SET a = datetime('now', 'localtime') WHERE rowid = NEW.rowid;\n"
        "END;\n"
    )
    stmts = _split_statements(script)
    assert len(stmts) == 2
    assert stmts[1].startswith("CREATE TRIGGER")
    assert stmts[1].rstrip().endswith("END;")


def test_split_statements_tolerates_semicolon_in_comment():
    # complete_statement 按 SQLite 分词规则跳过 -- 注释：注释里的分号不会误切
    # （db_bootstrap._split_statements docstring 语义结论的实证锚点）
    script = (
        "CREATE TABLE t (a TEXT);  -- 行尾注释; 带分号\n"
        "-- 独立注释; 也带分号\n"
        "CREATE TABLE u (b TEXT);\n"
    )
    stmts = _split_statements(script)
    assert len(stmts) == 2
    assert stmts[0].startswith("CREATE TABLE t")
    assert stmts[1].startswith("-- 独立注释")  # 注释行归并进下一条语句，无害


def test_bootstrap_script_statement_mix():
    # 蓝本真实脚本必须整脚本切开且类型分布正确（12 表 + 8 索引 + 2 触发器）：
    # 比纯总数更有分辨力——新增一张表少配索引、触发器被切碎都会在此报红。
    # 剥离开头注释行再锚定 CREATE：兼容蓝本日后在语句前加独立注释
    stmts = _split_statements(BOOTSTRAP_SCRIPT)
    kinds: dict[str, int] = {}
    for stmt in stmts:
        body = re.sub(r"^(?:\s*--[^\n]*\n)+", "", stmt)
        m = re.search(r"CREATE (?:UNIQUE )?(TABLE|INDEX|TRIGGER)", body, re.IGNORECASE)
        assert m, f"无法识别的语句类型: {stmt[:60]!r}"
        kinds[m.group(1).upper()] = kinds.get(m.group(1).upper(), 0) + 1
    # 表/触发器数从规格集合派生；索引无独立规格清单，蓝本演进时人工同步此数
    assert kinds == {
        "TABLE": len(EXPECTED_TABLES), "INDEX": 8, "TRIGGER": len(EXPECTED_TRIGGERS)
    }


def test_bootstrap_split_statements_are_executable():
    # 切分结果必须逐条可被 sqlite3 直接执行：锁死「分号后尾随注释触发
    # only-execute-one-statement」与触发器被切碎两类潜在翻车（实测 Python 3.12
    # 尾随注释可执行，此用例将该实证固化为回归防线）
    conn = sqlite3.connect(":memory:")
    try:
        for stmt in _split_statements(BOOTSTRAP_SCRIPT):
            conn.execute(stmt)
        remaining = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchone()[0]
        assert remaining >= len(EXPECTED_TABLES)
    finally:
        conn.close()


def _module_ddl_columns() -> dict[str, set[str]]:
    """从 app 源码提取各业务模块自带的 CREATE TABLE IF NOT EXISTS 列集（含函数内联与 DDL 常量）。

    必须排除 db_bootstrap.py 自身：蓝本脚本里的 CREATE TABLE 是「被测对象」，
    混进扫描集会让纯蓝本表以「自己 ⊇ 自己」恒真通过，一致性检查形同虚设。
    只取「列名 类型」形态的行；表级约束（PRIMARY/FOREIGN/UNIQUE/CHECK/CONSTRAINT 等关键字
    开头）与引号/非标识符 token 一律跳过（后半段关键字仅为行首误吞降级，非 SQL 语法表）。
    已知局限：单行写法的 DDL 或注释里的圆括号可能导致漏解析或误报（误红方向，失败即人工
    核对），不做 SQL 级精确解析。
    """
    create_re = re.compile(
        r"CREATE TABLE IF NOT EXISTS\s+(\w+)\s*\((.*?)\n\s*\)", re.DOTALL | re.IGNORECASE
    )
    constraint_starts = {
        "PRIMARY", "FOREIGN", "UNIQUE", "CHECK", "CONSTRAINT", "EXCLUDE",
        "WITH", "SELECT", "INSERT", "CREATE", "IF",
    }
    tables: dict[str, set[str]] = {}
    for path in (BACKEND_ROOT / "app").rglob("*.py"):
        if path.name == "db_bootstrap.py":
            continue
        src = path.read_text(encoding="utf-8")
        if not re.search(r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS", src, re.IGNORECASE):
            continue
        for name, body in create_re.findall(src):
            cols: set[str] = set()
            for line in body.splitlines():
                token = line.strip().split(None, 1)[0].strip(",").strip() if line.strip() else ""
                if not token or not re.fullmatch(r"\w+", token):
                    continue
                if token.upper() in constraint_starts:
                    continue
                cols.add(token)
            tables.setdefault(name, set()).update(cols)
    return tables


def test_bootstrap_columns_cover_module_ddl(tmp_path):
    # 蓝本先建表后，模块惰性 DDL 会被 IF NOT EXISTS 静默跳过——蓝本一旦比模块 DDL 少列
    # 就是「no such column」类新机故障。此用例锁死：蓝本列集 ⊇ 全部重叠表的模块列集。
    db_path = str(tmp_path / "fresh.db")
    ensure_main_db_schema(db_path)
    with closing(sqlite3.connect(db_path)) as conn:
        blueprint_cols = {
            row[0]: {r[1] for r in conn.execute(f"PRAGMA table_info({row[0]})")}
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    module_cols = _module_ddl_columns()
    # 自证扫描有效：真实模块 DDL（排除蓝本自身后）必须解析出这批关键表，
    # 防止解析正则失效时用例静默退化为恒真
    assert {"job_goals", "token_log", "scrape_sessions", "raw_jobs", "evaluation_weights"} <= set(module_cols)

    # 覆盖对账：模块表要么在蓝本（主库），要么命中跨库白名单；
    # 两者皆非 = 主库新表漏配蓝本，正是「raw_jobs 类 no such table」的立项故障
    unaccounted = set(module_cols) - set(blueprint_cols) - CROSS_DB_TABLES
    assert not unaccounted, f"主库新表漏配蓝本（也不在跨库白名单）: {sorted(unaccounted)}"

    overlap = set(module_cols) & set(blueprint_cols)
    assert overlap, "模块 DDL 与蓝本零重叠，扫描必然失效"
    narrow = {
        table: sorted(module_cols[table] - blueprint_cols[table])
        for table in overlap
        if module_cols[table] - blueprint_cols[table]
    }
    assert not narrow, f"蓝本落后于模块 DDL（缺列），请先改生产迁移再同步蓝本: {narrow}"


def test_resolve_main_db_path_analytics_override_wins(tmp_path, monkeypatch):
    # ANALYTICS_DB_PATH 是显式覆盖：文件不存在也采纳（QA 隔离栈先指路径后建库）
    missing = str(tmp_path / "not_yet.db")
    monkeypatch.setenv("ANALYTICS_DB_PATH", missing)
    monkeypatch.delenv("MAIN_PROJECT_DB", raising=False)
    assert resolve_main_db_path() == missing


def test_resolve_main_db_path_main_project_only_when_exists(tmp_path, monkeypatch):
    monkeypatch.delenv("ANALYTICS_DB_PATH", raising=False)
    existing = tmp_path / "external.db"
    existing.write_text("")
    monkeypatch.setenv("MAIN_PROJECT_DB", str(existing))
    assert resolve_main_db_path() == str(existing)
    # 文件不存在则回落仓内默认（显式拼路径断言，不随进程环境变量红绿）
    monkeypatch.setenv("MAIN_PROJECT_DB", str(tmp_path / "ghost.db"))
    assert resolve_main_db_path() == DEFAULT_DB_PATH


def test_goal_service_db_path_is_resolver_snapshot():
    # 单一真源：goal_service.DB_PATH 是 import 期 resolve_main_db_path() 的冻结快照。
    # 刻意不动环境变量——只要 import 与调用之间环境未变，两者按构造必然一致；
    # 不用「delenv 后再比对」的写法：那会随进程启动时的环境变量不同而红绿不定。
    # 默认回落路径本身已在上一用例用显式拼路径断言。
    assert goal_service.DB_PATH == resolve_main_db_path()
