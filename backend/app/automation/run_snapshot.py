"""
全链路运行台账 —— 刷新不丢的抓取统计与本轮判定
==============================================

SSE 是「直播」：连接断开（刷新页面）后，之前推过的进度数字不会重发。
本模块持久化记录「最新一轮任务」的完整生命周期（task_id / start_rowid / budgets / record_ids）。
即使任务收尾、后端重启、页面刷新，在下一次新任务启动覆盖前，当前最后一轮产出的岗位永远锁定为「本轮」！
"""
import json
import sqlite3
import threading
from pathlib import Path

_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "job_hunter.db"
_lock = threading.Lock()

_runtime: dict[str, object] = {
    "task_id": None,
    "start_rowid": 0,
    "budgets": {},    # 平台key -> 本轮预算(limit)
    "disabled": [],   # 登录失效被跳过的平台key
    "running": False,
    "started": False,  # 本进程内是否有过链路登记；未登记时不返回历史全表统计
    "record_ids": [],  # 本轮进入评估流转的飞书记录 ID（jobs-snapshot 用它把看板限定在本轮岗位内）
}
_dismissed_jobs: set[str] = set()
_delivery_failures: dict[str, dict] = {}
_retrying_jobs: set[str] = set()


def _ensure_db():
    try:
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(_DB_PATH)) as conn:
            conn.execute("""
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
                    delivery_failures_json TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            try:
                conn.execute("ALTER TABLE pipeline_latest_run ADD COLUMN delivery_failures_json TEXT DEFAULT '{}'")
            except Exception:
                pass
    except Exception:
        pass


def _save_to_db():
    try:
        _ensure_db()
        with sqlite3.connect(str(_DB_PATH)) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO pipeline_latest_run
                (id, task_id, start_rowid, budgets_json, disabled_json, running, started, record_ids_json, dismissed_ids_json, delivery_failures_json, updated_at)
                VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))
            """, (
                _runtime["task_id"],
                _runtime["start_rowid"],
                json.dumps(_runtime["budgets"], ensure_ascii=False),
                json.dumps(_runtime["disabled"], ensure_ascii=False),
                1 if _runtime["running"] else 0,
                1 if _runtime["started"] else 0,
                json.dumps(_runtime["record_ids"], ensure_ascii=False),
                json.dumps(list(_dismissed_jobs), ensure_ascii=False),
                json.dumps(_delivery_failures, ensure_ascii=False),
            ))
    except Exception:
        pass


def _load_from_db():
    try:
        _ensure_db()
        with sqlite3.connect(str(_DB_PATH)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM pipeline_latest_run WHERE id = 1").fetchone()
            if row:
                _runtime["task_id"] = row["task_id"]
                _runtime["start_rowid"] = int(row["start_rowid"] or 0)
                _runtime["budgets"] = json.loads(row["budgets_json"] or "{}")
                _runtime["disabled"] = json.loads(row["disabled_json"] or "[]")
                _runtime["running"] = bool(row["running"])
                _runtime["started"] = bool(row["started"]) or bool(row["task_id"]) or bool(row["record_ids_json"] and row["record_ids_json"] != "[]")
                _runtime["record_ids"] = json.loads(row["record_ids_json"] or "[]")
                dismissed = json.loads(row["dismissed_ids_json"] or "[]")
                _dismissed_jobs.clear()
                _dismissed_jobs.update(str(x) for x in dismissed)
                if "delivery_failures_json" in row.keys() and row["delivery_failures_json"]:
                    try:
                        _delivery_failures.clear()
                        _delivery_failures.update(json.loads(row["delivery_failures_json"]))
                    except Exception:
                        pass
            else:
                try:
                    max_row = conn.execute("SELECT IFNULL(MAX(rowid), 0) FROM raw_jobs").fetchone()[0]
                except Exception:
                    max_row = 0
                _runtime["start_rowid"] = int(max_row or 0)
                _runtime["started"] = False
                _runtime["running"] = False
                _runtime["record_ids"] = []
                _delivery_failures.clear()
    except Exception:
        pass


# 模块初始化时主动从数据库恢复
_load_from_db()


def begin(task_id: str, start_rowid: int, budgets: dict[str, int], disabled: list) -> None:
    with _lock:
        _runtime.update(
            task_id=task_id,
            start_rowid=int(start_rowid or 0),
            budgets=dict(budgets or {}),
            disabled=list(disabled or []),
            running=True,
            started=True,
            record_ids=[],
        )
        _save_to_db()


def register_record_ids(ids) -> None:
    """登记本轮进入评估的飞书记录 ID（评估批次构建时调用；begin() 时清空）。"""
    clean = list(dict.fromkeys(i for i in (ids or []) if i))
    if not clean:
        return
    with _lock:
        known = set(_runtime["record_ids"])
        _runtime["record_ids"].extend(i for i in clean if i not in known)
        _save_to_db()


def current_runtime() -> dict:
    """当前台账只读快照（供 jobs-snapshot 等接口按「本轮」过滤）。"""
    with _lock:
        _load_from_db()
        return {
            "started": _runtime["started"],
            "running": _runtime["running"],
            "task_id": _runtime["task_id"],
            "start_rowid": _runtime["start_rowid"],
            "record_ids": list(_runtime["record_ids"]),
        }


def dismiss_job(job_id: str) -> None:
    """将岗位标记为已放弃/移出指挥中心看板"""
    if not job_id:
        return
    with _lock:
        _dismissed_jobs.add(str(job_id))
        _save_to_db()


def undismiss_job(job_id: str) -> None:
    """恢复被放弃的岗位"""
    if not job_id:
        return
    with _lock:
        _dismissed_jobs.discard(str(job_id))
        _save_to_db()


def get_dismissed_job_ids() -> set:
    """获取所有被放弃/移出看板的岗位 ID"""
    with _lock:
        return set(_dismissed_jobs)


def record_delivery_failure(job_id: str, error: str, step: str = "自动投递阶段", company: str = "", job_name: str = "", platform: str = "", job_url: str = "", grade: str = "") -> None:
    """记录当天发生的投递异常岗位（同岗位重复失败时累加 failure_count，供 L1 分诊判定重试上限）。

    内置 15 秒纯时间窗幂等防抖保护（脱敏两层微小报错文字差异），避免跨层兜底调用时计次双倍虚高。
    """
    if not job_id:
        return
    with _lock:
        from datetime import datetime
        prev = _delivery_failures.get(str(job_id), {})
        now_ts = datetime.now()
        # 办法 1 纯天然去重：同岗位 15 秒内不依赖文字逐字相等，统一视为同一次投递事件，不重复递增 failure_count
        is_dup = False
        prev_time_str = str(prev.get("failed_at") or "")
        if prev_time_str:
            try:
                prev_dt = datetime.strptime(prev_time_str, "%Y-%m-%d %H:%M:%S")
                if (now_ts - prev_dt).total_seconds() < 15:
                    is_dup = True
            except Exception:
                pass

        prev_cnt = int(prev.get("failure_count") or 0)
        _delivery_failures[str(job_id)] = {
            "job_id": str(job_id),
            "job_name": job_name or prev.get("job_name", ""),
            "company_name": company or prev.get("company_name", ""),
            "platform": platform or prev.get("platform", ""),
            "job_url": job_url or prev.get("job_url", ""),
            "grade": grade or prev.get("grade", ""),
            "error": error,
            "step": step,
            "failure_count": prev_cnt if is_dup else (prev_cnt + 1),
            "failed_at": now_ts.strftime("%Y-%m-%d %H:%M:%S")
        }
        _save_to_db()


def remove_delivery_failure(job_id: str) -> None:
    """投递成功或人工放行后移除异常状态"""
    if not job_id:
        return
    with _lock:
        _delivery_failures.pop(str(job_id), None)
        _save_to_db()


def get_delivery_failures() -> dict:
    """获取当前所有未处置的投递异常"""
    with _lock:
        _load_from_db()
        return dict(_delivery_failures)


_delivering_jobs: set[str] = set()


def mark_job_delivering(job_ids) -> None:
    """标记岗位进入自动投递中状态（单岗或批量）。"""
    if not job_ids:
        return
    targets = [str(j) for j in ([job_ids] if isinstance(job_ids, (str, int)) else job_ids) if j]
    with _lock:
        _delivering_jobs.update(targets)


def unmark_job_delivering(job_ids) -> None:
    """解除岗位的自动投递中状态。"""
    if not job_ids:
        return
    targets = [str(j) for j in ([job_ids] if isinstance(job_ids, (str, int)) else job_ids) if j]
    with _lock:
        _delivering_jobs.difference_update(targets)


def mark_job_retrying(job_id: str) -> None:
    """标记岗位进入正在重试发射状态（快照与看板在此期间强制识别为进行态，杜绝状态乒乓）"""
    if not job_id:
        return
    with _lock:
        _retrying_jobs.add(str(job_id))


def unmark_job_retrying(job_id: str) -> None:
    """解除岗位的正在重试发射状态"""
    if not job_id:
        return
    with _lock:
        _retrying_jobs.discard(str(job_id))


def is_job_retrying(job_id: str) -> bool:
    """查询指定岗位是否正处于重试或投递在途中"""
    if not job_id:
        return False
    with _lock:
        return str(job_id) in _retrying_jobs


def get_active_inflight_job_ids() -> set[str]:
    """获取当前所有正在投递、重试或处于投递流水线中的岗位 ID 全集"""
    with _lock:
        res = set(_retrying_jobs) | set(_delivering_jobs)
    try:
        import sys
        dr = sys.modules.get("app.automation.routes.delivery_router")
        if dr and hasattr(dr, "_ACTIVE_DELIVERY_RECORD_IDS"):
            res.update(str(x) for x in dr._ACTIVE_DELIVERY_RECORD_IDS if x)
    except Exception:
        pass
    try:
        import sys
        wf = sys.modules.get("app.automation.workflow")
        if wf and hasattr(wf, "_DELIVERY_INFLIGHT_RECORD_IDS"):
            res.update(str(x) for x in wf._DELIVERY_INFLIGHT_RECORD_IDS if x)
    except Exception:
        pass
    return res


def get_retrying_job_ids() -> set[str]:
    """获取当前所有正在重试发射的岗位 ID 集合（兼容返回 inflight 全集）"""
    return get_active_inflight_job_ids()


def clear_delivery_failures() -> None:
    """清空所有投递异常"""
    with _lock:
        _delivery_failures.clear()
        _save_to_db()


def end() -> None:
    """链路收尾：标记结束（台账数字保留，供结束后查看，直到下一轮 begin 覆盖）。"""
    with _lock:
        _runtime["running"] = False
        _save_to_db()


def compute(db_path: str, platform_cn: dict[str, str]) -> dict:
    """返回各平台本轮真实入库数 + 预算 + 失效平台，供前端轮询合并。"""
    with _lock:
        if not _runtime["started"]:
            return {"running": False, "task_id": None, "disabled": [], "platforms": [], "conditions": _condition_rows()}
        snap = {
            "task_id": _runtime["task_id"],
            "start_rowid": _runtime["start_rowid"],
            "budgets": dict(_runtime["budgets"]),
            "disabled": list(_runtime["disabled"]),
            "running": _runtime["running"],
        }

    counts: dict[str, int] = {}
    try:
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute(
                "SELECT platform, COUNT(*) FROM raw_jobs WHERE rowid > ? GROUP BY platform",
                (snap["start_rowid"],),
            ).fetchall()
        counts = {cn: int(n) for cn, n in rows}
    except Exception:
        counts = {}

    platforms = []
    seen_names = set()
    for key, budget in snap["budgets"].items():
        name = platform_cn.get(key, key)
        seen_names.add(name)
        platforms.append({
            "key": key,
            "name": name,
            "current": counts.get(name, 0),
            "total": int(budget or 0),
        })
    # 预算外但有入库的平台（兜底展示，不丢数据）
    for cn, n in counts.items():
        if cn not in seen_names:
            platforms.append({"key": cn, "name": cn, "current": n, "total": 0})

    return {
        "running": snap["running"],
        "task_id": snap["task_id"],
        "disabled": snap["disabled"],
        "platforms": platforms,
        "conditions": _condition_rows(),
    }


def _condition_rows() -> list:
    """全部「条件×平台」进度行（分子 scraped_count / 分母 predicted_total），历史进度也可见。"""
    try:
        from app.session.scrape_sessions import list_condition_progress
        return list_condition_progress()
    except Exception:
        return []
