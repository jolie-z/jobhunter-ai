"""
Session 生命周期管理器

职责：
- 根据飞书消息的 chat_id + root_id（话题）确定 session_id
- 管理 session 的创建、活跃、超时切割
- 持久化 session 元数据到 SQLite

Session 映射规则：
- 飞书话题内消息 → session_id = "{chat_id}_{root_id}"
- 群主对话流消息 → session_id = "{chat_id}_main"
- 超时切割：同一 chat_id 的 main session 超过 SESSION_TIMEOUT_MINUTES 无活动，
  下次发言自动创建新 session（"{chat_id}_main_{timestamp}"）
"""

import logging
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger("session_manager")

# ==========================================
# 配置
# ==========================================
SESSION_TIMEOUT_MINUTES = getattr(settings, "SESSION_TIMEOUT_MINUTES", 30)
# 默认绝对路径：backend/data/sessions.db，防止启动目录漂移在根目录新建多余的 data/sessions.db
SESSION_DB_PATH = str(Path(__file__).resolve().parents[2] / "data" / "sessions.db")

# ==========================================
# 数据结构
# ==========================================
@dataclass
class SessionInfo:
    session_id: str
    chat_id: str
    root_id: str | None  # 飞书话题 root_id，None 表示主对话流
    created_at: float
    last_active_at: float
    is_active: bool = True
    summary: str = ""  # 上下文摘要（由 context_summarizer 写入）


# ==========================================
# SessionManager
# ==========================================
class SessionManager:
    """管理飞书对话的 session 生命周期。线程安全。"""

    def __init__(self, db_path: str = SESSION_DB_PATH):
        self._db_path = db_path
        self._lock = threading.Lock()
        # 内存缓存：chat_id → 当前活跃 SessionInfo
        self._active_sessions: dict[str, SessionInfo] = {}
        self._init_db()

    def _init_db(self):
        """初始化 SQLite 表结构。"""
        import os
        os.makedirs(os.path.dirname(self._db_path) if os.path.dirname(self._db_path) else ".", exist_ok=True)
        logger.info(f"[SessionManager._init_db] 正在初始化会话数据库 [db_path={self._db_path}]")
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    chat_id TEXT NOT NULL,
                    root_id TEXT,
                    created_at REAL NOT NULL,
                    last_active_at REAL NOT NULL,
                    is_active INTEGER DEFAULT 1,
                    summary TEXT DEFAULT ''
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_sessions_chat_active
                ON sessions(chat_id, is_active)
            """)
            conn.commit()
        logger.info(f"[SessionManager] DB 初始化完成: {self._db_path}")

    def resolve_session(self, chat_id: str, root_id: str | None = None) -> SessionInfo:
        """
        根据消息来源解析出当前应使用的 session。

        Args:
            chat_id: 飞书群 ID
            root_id: 飞书话题根消息 ID（话题内消息才有，主对话流为 None）

        Returns:
            当前活跃的 SessionInfo
        """
        with self._lock:
            # 话题消息：每个话题是独立 session，不存在超时切割
            if root_id:
                session_id = f"{chat_id}_{root_id}"
                session = self._active_sessions.get(session_id)
                if session and session.is_active:
                    session.last_active_at = time.time()
                    self._update_last_active(session_id)
                    return session
                # 话题 session 不存在或已关闭 → 创建/恢复
                session = self._load_or_create(session_id, chat_id, root_id)
                self._active_sessions[session_id] = session
                return session

            # 主对话流：需要检查超时切割
            main_key = f"{chat_id}_main"
            session = self._active_sessions.get(main_key)

            if session and session.is_active:
                elapsed = time.time() - session.last_active_at
                if elapsed < SESSION_TIMEOUT_MINUTES * 60:
                    # 未超时，继续使用
                    session.last_active_at = time.time()
                    self._update_last_active(main_key)
                    return session
                else:
                    # 超时，关闭旧 session
                    logger.info(f"[Session] 主对话超时 {elapsed/60:.0f}min，切割新 session")
                    session.is_active = False
                    self._deactivate(main_key)

            # 创建新的主对话 session
            new_session_id = f"{chat_id}_main_{uuid.uuid4().hex[:8]}"
            session = self._load_or_create(new_session_id, chat_id, None)
            self._active_sessions[main_key] = session
            return session

    def get_session_summary(self, session_id: str) -> str:
        """获取 session 的上下文摘要。"""
        with self._lock:
            session = self._active_sessions.get(session_id)
            if session:
                return session.summary
        # 从 DB 查
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT summary FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            return row[0] if row and row[0] else ""

    def save_session_summary(self, session_id: str, summary: str) -> None:
        """保存/更新 session 的上下文摘要。"""
        with self._lock:
            session = self._active_sessions.get(session_id)
            if session:
                session.summary = summary
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "UPDATE sessions SET summary = ? WHERE session_id = ?",
                (summary, session_id)
            )
            conn.commit()

    def sweep_stale_sessions(self, max_idle_hours: float = 48) -> int:
        """沉寂超期未活跃的 session（TODO.md 数据库治理第 6 项）。

        DB 层 is_active 置 0，并同步清除内存缓存中对应的活跃项，
        保证下次消息到来时按新会话解析。返回本轮沉寂的 session 数。
        """
        cutoff = time.time() - max_idle_hours * 3600
        stale_ids: list[str] = []
        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute(
                "SELECT session_id FROM sessions WHERE is_active = 1 AND last_active_at < ?",
                (cutoff,),
            ).fetchall()
            stale_ids = [r[0] for r in rows]
            if stale_ids:
                conn.execute(
                    "UPDATE sessions SET is_active = 0 WHERE is_active = 1 AND last_active_at < ?",
                    (cutoff,),
                )
                conn.commit()
        if stale_ids:
            with self._lock:
                for key, s in list(self._active_sessions.items()):
                    if s.session_id in stale_ids:
                        del self._active_sessions[key]
            logger.info(f"[Session] 已沉寂 {len(stale_ids)} 个超 {max_idle_hours}h 未活跃的会话: {stale_ids[:5]}")
        return len(stale_ids)

    def close_session(self, session_id: str) -> None:
        """显式关闭一个 session（用户发 /new 或 /reset 时调用）。"""
        with self._lock:
            session = self._active_sessions.get(session_id)
            if session:
                session.is_active = False
            # 如果是主对话，清除缓存让下次 resolve 创建新的
            for _key, s in list(self._active_sessions.items()):
                if s.session_id == session_id:
                    s.is_active = False
        self._deactivate(session_id)
        logger.info(f"[Session] 已关闭: {session_id}")

    def force_new_session(self, chat_id: str, root_id: str | None = None) -> SessionInfo:
        """强制开启新 session（用户显式指令）。"""
        with self._lock:
            if root_id:
                # 话题内不支持强制新建（话题本身就是隔离的）
                session_id = f"{chat_id}_{root_id}"
            else:
                # 关闭当前主对话
                main_key = f"{chat_id}_main"
                old = self._active_sessions.get(main_key)
                if old:
                    old.is_active = False
                    self._deactivate(old.session_id)
                session_id = f"{chat_id}_main_{uuid.uuid4().hex[:8]}"

            session = self._load_or_create(session_id, chat_id, root_id)
            self._active_sessions[f"{chat_id}_{'main' if not root_id else root_id}"] = session
            return session

    # ==========================================
    # 内部方法
    # ==========================================
    def _load_or_create(self, session_id: str, chat_id: str, root_id: str | None) -> SessionInfo:
        """从 DB 加载或创建新 session。"""
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT session_id, chat_id, root_id, created_at, last_active_at, is_active, summary "
                "FROM sessions WHERE session_id = ?",
                (session_id,)
            ).fetchone()

            if row:
                session = SessionInfo(
                    session_id=row[0], chat_id=row[1], root_id=row[2],
                    created_at=row[3], last_active_at=time.time(),
                    is_active=True, summary=row[6] or ""
                )
                # 重新激活
                conn.execute(
                    "UPDATE sessions SET is_active = 1, last_active_at = ? WHERE session_id = ?",
                    (time.time(), session_id)
                )
                conn.commit()
                return session

            # 创建新记录
            now = time.time()
            conn.execute(
                "INSERT INTO sessions (session_id, chat_id, root_id, created_at, last_active_at, is_active, summary) "
                "VALUES (?, ?, ?, ?, ?, 1, '')",
                (session_id, chat_id, root_id, now, now)
            )
            conn.commit()
            logger.info(f"[Session] 新建: {session_id}")
            return SessionInfo(
                session_id=session_id, chat_id=chat_id, root_id=root_id,
                created_at=now, last_active_at=now
            )

    def _update_last_active(self, session_id: str):
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "UPDATE sessions SET last_active_at = ? WHERE session_id = ?",
                (time.time(), session_id)
            )
            conn.commit()

    def _deactivate(self, session_id: str):
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "UPDATE sessions SET is_active = 0 WHERE session_id = ?",
                (session_id,)
            )
            conn.commit()


# ==========================================
# 全局单例
# ==========================================
_session_manager: SessionManager | None = None


def get_session_manager() -> SessionManager:
    """获取全局 SessionManager 单例。"""
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
    return _session_manager
