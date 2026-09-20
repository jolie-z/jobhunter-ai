"""checkpoint_gc 测试：LangGraph 断点库安全回收。

重点回归三方质检定性的两个翻车点：
1. 绝不用 CAST(checkpoint_id AS INTEGER)（UUIDv6 十六进制串 CAST 恒等于 1，会清空整库）；
2. 待审批保护读 pending_delivery_pool（而非已放行的 boss_approvals）。
"""
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.automation import checkpoint_gc as gc

# ---------------------------------------------------------------- 构造工具

LANGGRAPH_SCHEMA = """
CREATE TABLE checkpoints (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    checkpoint_id TEXT NOT NULL,
    parent_checkpoint_id TEXT,
    type TEXT,
    checkpoint BLOB,
    metadata BLOB,
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
);
CREATE TABLE writes (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    checkpoint_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    idx INTEGER NOT NULL,
    channel TEXT NOT NULL,
    type TEXT,
    value BLOB,
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
);
"""


def _pack(obj) -> bytes:
    """与生产环境一致的序列化：ormsgpack 优先（venv 实际依赖），msgpack 兜底。"""
    try:
        import ormsgpack

        return ormsgpack.packb(obj)
    except ImportError:
        import msgpack

        return msgpack.packb(obj, strict_map_key=False)


def _uuid6_id(dt: datetime) -> str:
    """由时间反推 UUIDv6 形式的 checkpoint_id（checkpoint_gc._uuid6_datetime 的逆运算）。"""
    ts_100ns = int((dt.timestamp() + gc._UUID6_EPOCH_OFFSET_S) * 1e7)
    time_high = (ts_100ns >> 28) & 0xFFFFFFFF
    time_mid = (ts_100ns >> 12) & 0xFFFF
    time_low = ts_100ns & 0xFFF
    return f"{time_high:08x}-{time_mid:04x}-6{time_low:03x}-8000-000000000000"


def _insert_thread(db: str, thread_id: str, when: datetime, checkpoint_id: str | None = None,
                   blob: bytes | None = None, writes: int = 2):
    cid = checkpoint_id or _uuid6_id(when)
    if blob is None:
        blob = _pack({"v": 4, "id": cid, "ts": when.astimezone(timezone.utc).isoformat()})
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO checkpoints (thread_id, checkpoint_id, type, checkpoint) VALUES (?, ?, 'msgpack', ?)",
        (thread_id, cid, blob),
    )
    for i in range(writes):
        conn.execute(
            "INSERT INTO writes (thread_id, checkpoint_id, task_id, idx, channel) VALUES (?, ?, 't1', ?, 'ch')",
            (thread_id, cid, i),
        )
    conn.commit()
    conn.close()
    return cid


def _make_langgraph_db(path) -> str:
    db = str(path)
    conn = sqlite3.connect(db)
    conn.executescript(LANGGRAPH_SCHEMA)
    conn.commit()
    conn.close()
    return db


def _make_autopilot_db(path, pending_rows=()) -> str:
    db = str(path)
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE pending_delivery_pool (record_id TEXT PRIMARY KEY, parked_at TEXT NOT NULL)"
    )
    for record_id, parked_at in pending_rows:
        conn.execute("INSERT INTO pending_delivery_pool VALUES (?, ?)", (record_id, parked_at))
    conn.commit()
    conn.close()
    return db


def _make_job_hunter_db(path, running: int = 0, updated_at: str = "") -> str:
    db = str(path)
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE pipeline_latest_run (id INTEGER PRIMARY KEY, running INTEGER, updated_at TEXT)"
    )
    conn.execute("INSERT INTO pipeline_latest_run VALUES (1, ?, ?)", (running, updated_at))
    conn.commit()
    conn.close()
    return db


def _thread_ids(db: str, table: str = "checkpoints") -> set[str]:
    conn = sqlite3.connect(db)
    try:
        return {r[0] for r in conn.execute(f"SELECT DISTINCT thread_id FROM {table}")}
    finally:
        conn.close()


@pytest.fixture()
def env(tmp_path):
    """一套自洽的测试环境：langgraph 库 + autopilot 库 + job_hunter 库。"""
    def build(pending_rows=(), running: int = 0, updated_at: str = ""):
        lg = _make_langgraph_db(tmp_path / "langgraph_checkpoints.db")
        ap = _make_autopilot_db(tmp_path / "autopilot.db", pending_rows)
        jh = _make_job_hunter_db(tmp_path / "job_hunter.db", running=running, updated_at=updated_at)
        return lg, ap, jh
    return build


# ---------------------------------------------------------------- 用例

def test_old_thread_deleted_new_thread_kept(env, tmp_path):
    """核心行为：只删「最新 checkpoint 已超期」的 thread，新 thread 分毫不动。"""
    lg, ap, jh = env()
    now = datetime.now().astimezone()
    old_id = _insert_thread(lg, "thread-old", now - timedelta(days=30))
    _insert_thread(lg, "thread-new", now - timedelta(days=2))

    results = gc.run_gc(
        dry_run=False,
        targets=[gc.GCTarget(tmp_path / "langgraph_checkpoints.db", 14, "流水线checkpoint")],
        job_hunter_db=jh,
        autopilot_db=ap,
    )

    assert results[0].threads_deleted == 1
    assert results[0].checkpoints_deleted == 1
    assert results[0].writes_deleted == 2
    assert _thread_ids(lg) == {"thread-new"}
    # 被删 thread 的 writes 必须级联清空，不留孤儿行
    conn = sqlite3.connect(lg)
    assert conn.execute("SELECT COUNT(*) FROM writes WHERE thread_id='thread-old'").fetchone()[0] == 0
    conn.close()


def test_dry_run_deletes_nothing(env, tmp_path):
    """dry-run 只统计、不动数据。"""
    lg, ap, jh = env()
    now = datetime.now().astimezone()
    _insert_thread(lg, "thread-old", now - timedelta(days=30))

    results = gc.run_gc(
        dry_run=True,
        targets=[gc.GCTarget(tmp_path / "langgraph_checkpoints.db", 14, "流水线checkpoint")],
        job_hunter_db=jh,
        autopilot_db=ap,
    )

    assert results[0].threads_deleted == 1
    assert _thread_ids(lg) == {"thread-old"}


def test_uuid4_thread_id_never_deleted_by_cast_trap(env, tmp_path):
    """回归 CAST 陷阱：uuid4 形式的 thread_id 数学换算必然失败 → 必须走保护路径，绝不误删。

    生产中 scheduler 兜底生成 str(uuid.uuid4()) 作 thread_id；若 GC 用
    CAST(checkpoint_id AS INTEGER) 这类 id 会被整库清空。
    """
    lg, ap, jh = env()
    now = datetime.now().astimezone()
    rid = str(uuid.uuid4())
    _insert_thread(
        lg,
        rid,
        now - timedelta(days=30),
        checkpoint_id=rid,  # uuid4：version nibble 是 4，_uuid6_datetime 应拒绝
        blob=_pack({"v": 4, "id": rid, "ts": (now - timedelta(days=30)).astimezone(timezone.utc).isoformat()}),
    )

    results = gc.run_gc(
        dry_run=False,
        targets=[gc.GCTarget(tmp_path / "langgraph_checkpoints.db", 14, "流水线checkpoint")],
        job_hunter_db=jh,
        autopilot_db=ap,
    )

    assert results[0].threads_deleted == 0
    assert results[0].protected == 1
    assert _thread_ids(lg) == {rid}


def test_corrupted_blob_protected(env, tmp_path):
    """blob 损坏/无 ts 的 thread 一律保护，绝不猜测。"""
    lg, ap, jh = env()
    now = datetime.now().astimezone()
    _insert_thread(lg, "thread-corrupt", now - timedelta(days=30), blob=b"\x87garbage-not-msgpack")

    results = gc.run_gc(
        dry_run=False,
        targets=[gc.GCTarget(tmp_path / "langgraph_checkpoints.db", 14, "流水线checkpoint")],
        job_hunter_db=jh,
        autopilot_db=ap,
    )

    assert results[0].threads_deleted == 0
    assert results[0].protected == 1
    assert results[0].warnings, "解析失败的 thread 必须产生告警"
    assert _thread_ids(lg) == {"thread-corrupt"}


def test_pending_pool_within_grace_protected(env, tmp_path):
    """待审批保护：pending_delivery_pool 内宽限期内的 thread 即使超期也强制保留。"""
    lg, ap, jh = env(pending_rows=[("rec-parked", datetime.now().astimezone().isoformat())])
    now = datetime.now().astimezone()
    _insert_thread(lg, "rec-parked", now - timedelta(days=60))  # 远超 14 天保留期
    _insert_thread(lg, "rec-free", now - timedelta(days=60))  # 无停车记录 → 可删

    results = gc.run_gc(
        dry_run=False,
        targets=[gc.GCTarget(tmp_path / "langgraph_checkpoints.db", 14, "流水线checkpoint")],
        job_hunter_db=jh,
        autopilot_db=ap,
    )

    assert results[0].threads_deleted == 1
    assert _thread_ids(lg) == {"rec-parked"}


def test_stale_parked_record_not_protected(env, tmp_path):
    """停车超宽限期（默认 30 天）的僵尸记录不再保护，对应 thread 可回收。"""
    lg, ap, jh = env(pending_rows=[("rec-zombie", (datetime.now().astimezone() - timedelta(days=40)).isoformat())])
    now = datetime.now().astimezone()
    _insert_thread(lg, "rec-zombie", now - timedelta(days=60))

    results = gc.run_gc(
        dry_run=False,
        targets=[gc.GCTarget(tmp_path / "langgraph_checkpoints.db", 14, "流水线checkpoint")],
        job_hunter_db=jh,
        autopilot_db=ap,
    )

    assert results[0].threads_deleted == 1
    assert _thread_ids(lg) == set()


def test_running_pipeline_blocks_pipeline_target_only(env, tmp_path):
    """流水线运行中：流水线库整轮中止，聊天库照常回收。"""
    lg, ap, jh = env(running=1, updated_at=datetime.now().astimezone().isoformat())
    now = datetime.now().astimezone()
    _insert_thread(lg, "thread-old", now - timedelta(days=30))
    chat = _make_langgraph_db(tmp_path / "agent_chat_checkpoints.db")
    _insert_thread(chat, "chat-old", now - timedelta(days=120))

    results = gc.run_gc(
        dry_run=False,
        targets=[
            gc.GCTarget(tmp_path / "langgraph_checkpoints.db", 14, "流水线checkpoint"),
            gc.GCTarget(tmp_path / "agent_chat_checkpoints.db", 90, "ChatAgent对话checkpoint",
                        pipeline_protections=False),
        ],
        job_hunter_db=jh,
        autopilot_db=ap,
    )

    assert results[0].skipped_reason, "流水线库必须被跳过"
    assert results[1].threads_deleted == 1
    assert _thread_ids(lg) == {"thread-old"}
    assert _thread_ids(chat) == set()


def test_stale_running_flag_does_not_block(env, tmp_path):
    """running=1 但 updated_at 超 24 小时 → 异常残留标记，不阻塞 GC。"""
    lg, ap, jh = env(
        running=1,
        updated_at=(datetime.now().astimezone() - timedelta(hours=30)).isoformat(),
    )
    now = datetime.now().astimezone()
    _insert_thread(lg, "thread-old", now - timedelta(days=30))

    results = gc.run_gc(
        dry_run=False,
        targets=[gc.GCTarget(tmp_path / "langgraph_checkpoints.db", 14, "流水线checkpoint")],
        job_hunter_db=jh,
        autopilot_db=ap,
    )

    assert not results[0].skipped_reason
    assert results[0].threads_deleted == 1


def test_vacuum_shrinks_file(env, tmp_path):
    """删除超期大 blob 后 VACUUM 必须真实缩小文件（166MB 膨胀问题的验收点）。"""
    lg, ap, jh = env()
    now = datetime.now().astimezone()
    big = _pack({"v": 4, "ts": (now - timedelta(days=30)).astimezone(timezone.utc).isoformat(),
                 "payload": "x" * 2_000_000})
    _insert_thread(lg, "thread-big-old", now - timedelta(days=30), blob=big)
    size_before = (tmp_path / "langgraph_checkpoints.db").stat().st_size

    results = gc.run_gc(
        dry_run=False,
        targets=[gc.GCTarget(tmp_path / "langgraph_checkpoints.db", 14, "流水线checkpoint")],
        job_hunter_db=jh,
        autopilot_db=ap,
    )

    size_after = (tmp_path / "langgraph_checkpoints.db").stat().st_size
    assert results[0].threads_deleted == 1
    assert size_after < size_before, f"VACUUM 后文件必须缩小: {size_before} -> {size_after}"
    assert results[0].bytes_after < results[0].bytes_before


def test_blob_ts_overrides_math_disagreement(env, tmp_path):
    """双保险：数学换算与 blob ts 结论冲突时，以保护为准（不删）。"""
    lg, ap, jh = env()
    now = datetime.now().astimezone()
    # 数学换算=60 天前（超期），blob ts=1 天前（未超期）→ 冲突 → 保护
    _insert_thread(
        lg,
        "thread-conflict",
        now - timedelta(days=60),
        blob=_pack({"v": 4, "ts": (now - timedelta(days=1)).astimezone(timezone.utc).isoformat()}),
    )

    results = gc.run_gc(
        dry_run=False,
        targets=[gc.GCTarget(tmp_path / "langgraph_checkpoints.db", 14, "流水线checkpoint")],
        job_hunter_db=jh,
        autopilot_db=ap,
    )

    assert results[0].threads_deleted == 0
    assert _thread_ids(lg) == {"thread-conflict"}


def test_missing_db_file_skipped(tmp_path):
    """库文件不存在时优雅跳过，不抛异常。"""
    results = gc.run_gc(
        dry_run=False,
        targets=[gc.GCTarget(tmp_path / "not_exist.db", 14, "不存在")],
        job_hunter_db=tmp_path / "jh.db",
        autopilot_db=tmp_path / "ap.db",
    )
    assert results[0].skipped_reason == "库文件不存在"


def test_dry_run_beyond_legacy_variable_limit(env, tmp_path):
    """超大批量回归：thread 数超过 SQLite 老版本 999 绑定变量上限时 dry-run 仍可靠。

    dry-run 与真实删除同构分批（_CHUNK=500），任何环境（含 SQLite<3.32 默认
    MAX_VARIABLE_NUMBER=999）都不应出现 too many SQL variables；
    同时校验 dry-run 统计数与真实删除数严格一致。
    """
    lg, ap, jh = env()
    now = datetime.now().astimezone()
    old = now - timedelta(days=30)
    conn = sqlite3.connect(lg)
    for i in range(1100):  # > 999（老版 SQLite 默认变量上限）
        cid = _uuid6_id(old - timedelta(seconds=i))
        conn.execute(
            "INSERT INTO checkpoints (thread_id, checkpoint_id, type, checkpoint) VALUES (?, ?, 'msgpack', ?)",
            (f"thread-{i}", cid, _pack({"v": 4, "ts": old.astimezone(timezone.utc).isoformat()})),
        )
        conn.execute(
            "INSERT INTO writes (thread_id, checkpoint_id, task_id, idx, channel) VALUES (?, ?, 't1', 0, 'ch')",
            (f"thread-{i}", cid),
        )
    conn.commit()
    conn.close()

    targets = [gc.GCTarget(tmp_path / "langgraph_checkpoints.db", 14, "流水线checkpoint")]
    dry = gc.run_gc(dry_run=True, targets=targets, job_hunter_db=jh, autopilot_db=ap)[0]
    assert dry.threads_deleted == 1100
    assert dry.checkpoints_deleted == 1100
    assert dry.writes_deleted == 1100
    assert _thread_ids(lg) == {f"thread-{i}" for i in range(1100)}, "dry-run 不得删数据"

    real = gc.run_gc(dry_run=False, targets=targets, job_hunter_db=jh, autopilot_db=ap)[0]
    assert (real.threads_deleted, real.checkpoints_deleted, real.writes_deleted) == (
        dry.threads_deleted, dry.checkpoints_deleted, dry.writes_deleted,
    ), "dry-run 统计必须与真实删除严格一致"
    assert _thread_ids(lg) == set()
