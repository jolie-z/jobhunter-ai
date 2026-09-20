"""sessions 48h 沉寂巡检测试（TODO.md 数据库治理第 6 项）。"""
import time

from app.core.session_manager import SessionManager


def _mk_manager(tmp_path) -> SessionManager:
    return SessionManager(db_path=str(tmp_path / "sessions.db"))


def _insert_session(mgr: SessionManager, session_id: str, last_active_hours_ago: float, is_active: int = 1):
    with sqlite3_connect(mgr._db_path) as conn:
        conn.execute(
            "INSERT INTO sessions (session_id, chat_id, root_id, created_at, last_active_at, is_active)"
            " VALUES (?, ?, NULL, ?, ?, ?)",
            (session_id, session_id.split("_")[0], time.time() - 100, time.time() - last_active_hours_ago * 3600, is_active),
        )


def sqlite3_connect(path):
    import sqlite3
    return sqlite3.connect(path)


def test_sweep_only_deactivates_stale(tmp_path):
    mgr = _mk_manager(tmp_path)
    _insert_session(mgr, "chatA_main", last_active_hours_ago=49)   # 超期 → 沉寂
    _insert_session(mgr, "chatB_main", last_active_hours_ago=1)    # 活跃 → 保留
    _insert_session(mgr, "chatC_main", last_active_hours_ago=0.5, is_active=0)  # 已沉寂 → 不动

    swept = mgr.sweep_stale_sessions(max_idle_hours=48)

    assert swept == 1
    import sqlite3
    conn = sqlite3.connect(mgr._db_path)
    states = dict(conn.execute("SELECT session_id, is_active FROM sessions").fetchall())
    conn.close()
    assert states["chatA_main"] == 0
    assert states["chatB_main"] == 1
    assert states["chatC_main"] == 0


def test_sweep_clears_memory_cache(tmp_path):
    """DB 沉寂后内存缓存同步清除，否则下次消息仍复用旧会话。"""
    mgr = _mk_manager(tmp_path)
    # 走真实 resolve 建立内存缓存
    mgr.resolve_session("chatD", None)
    key = "chatD_main"
    assert key in mgr._active_sessions
    # 把该会话的 last_active_at 拨回 49 小时前
    import sqlite3
    conn = sqlite3.connect(mgr._db_path)
    conn.execute("UPDATE sessions SET last_active_at = ? WHERE chat_id='chatD'", (time.time() - 49 * 3600,))
    conn.commit()
    conn.close()

    swept = mgr.sweep_stale_sessions(max_idle_hours=48)

    assert swept == 1
    assert key not in mgr._active_sessions
    # 再 resolve 应创建全新会话而非复用被沉寂的
    fresh = mgr.resolve_session("chatD", None)
    assert fresh.session_id != "chatD_main"
    assert fresh.is_active


def test_sweep_idempotent(tmp_path):
    mgr = _mk_manager(tmp_path)
    _insert_session(mgr, "chatE_main", last_active_hours_ago=100)
    assert mgr.sweep_stale_sessions() == 1
    assert mgr.sweep_stale_sessions() == 0
