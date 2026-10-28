"""岗位操作共享服务 —— 桌面端与飞书卡片两端动作的公共原语与动作审计。

背景（2026-10-09 双端撕裂事故 P1-6）：同一套「召回/归档/放行」动作散落在两个入口
（桌面端 processor.py / 飞书卡片 report_card_actions.py），行为不对等、无来源审计，
出事后无法还原"谁在哪端动了哪个岗位"。本模块收敛两端共用的基础能力：

- ID 解析：raw_<rowid> 前缀的拆装（此前散落 6+ 处裸 replace 拼接）
- 岗位名格式化：回执/日志通用的「公司 - 岗位」行
- 复评中判定：is_job_recalling（两端守卫共用，替代跨模块直读私有集合）
- 动作审计：每一条召回/归档/放行记录 来源端 + 动作 + 对象 + 结果，落 SQLite action_audit 表

完整动作函数（含通知/回滚/回执）仍留在两端入口——飞书端带卡片回执与后台复评链路，
桌面端带 UI 即时反馈，强行合一会让薄封装变成厚转发。待两端行为进一步对齐后再收敛。
"""

import logging
import sqlite3
from datetime import datetime
from typing import Any, Literal

AuditSource = Literal["desktop", "feishu_card"]
AuditAction = Literal["recall", "reject", "approve"]
AuditResult = Literal["success", "skipped", "failed"]

logger = logging.getLogger(__name__)

# 动作审计取值域
AUDIT_SOURCES = ("desktop", "feishu_card")
AUDIT_ACTIONS = ("recall", "reject", "approve")
AUDIT_RESULTS = ("success", "skipped", "failed")

_AUDIT_TABLE = "action_audit"


# ---- ID 解析（raw_<rowid> 拆装单一出处）----

def parse_raw_rowid(jid: str | int) -> int:
    """'raw_123' / '123' → 123；解析失败抛 ValueError（调用方按单条失败处理）。"""
    return int(str(jid).replace("raw_", "").strip())


def raw_rowid_key(rowid: int | str) -> str:
    """rowid → 'raw_<rowid>' 防重入键（召回登记簿统一用这个形态）。"""
    return f"raw_{rowid}"


# ---- 岗位名格式化（回执明细/审计/日志通用）----

def format_job_label(company_name: str | None, job_title: str | None) -> str:
    """「公司 - 岗位」行：截断防长名撑爆卡片，缺省兜底'未知'。"""
    return f"{(company_name or '未知公司')[:20]} - {(job_title or '未知岗位')[:28]}"


# ---- 召回复评登记簿（跨端共享状态：飞书卡片与桌面端守卫共用的唯一事实源）----
# check-and-add 必须置于任何 await 之前（含推送建档），与 report_card_actions 的召回协程约定一致；
# 进程重启集合清空，重启窗口由 delivery_node 的 inflight 防重兜底。
_recall_evaluating: set[str] = set()


def register_recall_start(raw_rowid: int | str) -> bool:
    """登记复评开始。返回 False 表示已在评中（防同岗位并发双跑）。接受 raw_N/N/整数形态。"""
    try:
        key = raw_rowid_key(parse_raw_rowid(raw_rowid))
    except (ValueError, AttributeError):
        return False
    if key in _recall_evaluating:
        return False
    _recall_evaluating.add(key)
    return True


def register_recall_end(raw_rowid: int | str) -> None:
    """登记复评结束（协程 finally 中调用；未登记的键不动他人租约）。"""
    try:
        _recall_evaluating.discard(raw_rowid_key(parse_raw_rowid(raw_rowid)))
    except (ValueError, AttributeError):
        pass


def is_key_recalling(key: str) -> bool:
    """按归一键(raw_<rowid> 形态)判定是否复评中——已持有键的调用方用这个,免二次解析。"""
    return key in _recall_evaluating


def is_job_recalling(raw_rowid: int | str) -> bool:
    """该岗位的召回复评是否正在进行中。接受 'raw_123' / '123' / 123 三种形态。"""
    try:
        key = raw_rowid_key(parse_raw_rowid(raw_rowid))
    except (ValueError, AttributeError):
        return False
    return key in _recall_evaluating


# ---- 动作审计 ----

_audit_ready_paths: set[str] = set()  # 建表缓存按库路径记(测试 tmp 库/多库场景各自建一次,避免 DDL 反复执行)


def _ensure_audit_table(conn: sqlite3.Connection, path: str) -> None:
    if path in _audit_ready_paths:
        return
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {_AUDIT_TABLE} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            source TEXT NOT NULL,
            action TEXT NOT NULL,
            target_id TEXT NOT NULL,
            job_label TEXT DEFAULT '',
            result TEXT NOT NULL,
            detail TEXT DEFAULT ''
        )
    """)
    _audit_ready_paths.add(path)


def record_action_audit(
    source: AuditSource,
    action: AuditAction,
    target_id: str,
    job_label: str = "",
    result: AuditResult = "success",
    detail: str = "",
    db_path: str | None = None,
) -> None:
    """记录一条动作审计。失败只告警不抛出——审计绝不阻断业务动作本身。"""
    if source not in AUDIT_SOURCES or action not in AUDIT_ACTIONS or result not in AUDIT_RESULTS:
        logger.warning(f"[动作审计] 非法取值被拒: source={source} action={action} result={result}")
        return
    try:
        from app.automation.scrape_runner import _get_raw_db_path
        path = db_path or _get_raw_db_path()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with sqlite3.connect(path) as conn:
            _ensure_audit_table(conn, path)
            conn.execute(
                f"INSERT INTO {_AUDIT_TABLE} (created_at, source, action, target_id, job_label, result, detail) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (now, source, action, str(target_id)[:64], job_label[:80], result, detail[:200]),
            )
    except Exception as ex:
        logger.warning(f"[动作审计] 写入失败（不影响业务动作）: {ex}")


def list_action_audits(limit: int = 50, db_path: str | None = None) -> list[dict[str, Any]]:
    """倒序读取最近动作审计（供查询接口/排查用）。"""
    try:
        from app.automation.scrape_runner import _get_raw_db_path
        path = db_path or _get_raw_db_path()
        with sqlite3.connect(path) as conn:
            conn.row_factory = sqlite3.Row
            _ensure_audit_table(conn, path)
            rows = conn.execute(
                f"SELECT * FROM {_AUDIT_TABLE} ORDER BY id DESC LIMIT ?", (max(1, min(int(limit), 200)),)
            ).fetchall()
            return [dict(r) for r in rows]
    except Exception as ex:
        logger.warning(f"[动作审计] 读取失败: {ex}")
        return []
