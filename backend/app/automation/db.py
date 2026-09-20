import json
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 锚定到 backend/ 目录：若用相对路径，从其他 cwd 启动会静默新建空库
BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = BACKEND_ROOT / "autopilot.db"

_DEFAULT_GREETING_PLATFORMS = {"boss": True, "liepin": True, "zhilian": True, "51job": False}


def _parse_greeting_platforms(raw) -> dict[str, bool]:
    try:
        if raw:
            val = json.loads(raw)
            if isinstance(val, dict):
                res = dict(_DEFAULT_GREETING_PLATFORMS)
                for k, v in val.items():
                    res[str(k)] = bool(v)
                return res
    except Exception:
        pass
    return dict(_DEFAULT_GREETING_PLATFORMS)

def init_autopilot_db():
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL;")
            logger.info(f"[init_autopilot_db] 已确保 autopilot.db 启用 WAL 模式: {DB_PATH}")

            # 创建配置表 (单例模式)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS automation_configs (
                    id INTEGER PRIMARY KEY DEFAULT 1,
                    cron_time TEXT NOT NULL,
                    auto_deliver_grades TEXT NOT NULL,
                    auto_deliver_platforms TEXT NOT NULL DEFAULT '["boss", "liepin", "51job", "zhilian"]',
                    is_enabled BOOLEAN NOT NULL DEFAULT 1,
                    platform_configs TEXT DEFAULT '{}'
                )
            ''')

            # 兼容老数据：加入 platform_configs 和 auto_deliver_platforms 列
            try:
                cursor.execute("ALTER TABLE automation_configs ADD COLUMN platform_configs TEXT DEFAULT '{}'")
            except sqlite3.OperationalError:
                pass
            try:
                cursor.execute("ALTER TABLE automation_configs ADD COLUMN auto_deliver_platforms TEXT DEFAULT '[\"boss\", \"liepin\", \"51job\", \"zhilian\"]'")
            except sqlite3.OperationalError:
                pass
            try:
                cursor.execute("ALTER TABLE automation_configs ADD COLUMN batch_limit INTEGER DEFAULT 20")
            except sqlite3.OperationalError:
                pass
            # 海投简历（C-F 级自动投递用的通用简历，指向简历库记录 ID；空=回退启用简历）
            try:
                cursor.execute("ALTER TABLE automation_configs ADD COLUMN mass_apply_resume_id TEXT DEFAULT ''")
            except sqlite3.OperationalError:
                pass
            # A/B 级改写底稿（指定后评估与改写都用它；空=用启用简历）
            try:
                cursor.execute("ALTER TABLE automation_configs ADD COLUMN rewrite_base_resume_id TEXT DEFAULT ''")
            except sqlite3.OperationalError:
                pass
            # 海投门槛：公司规模下限 ≥ 该值的岗位不海投，停在「已完成初步评估」
            try:
                cursor.execute("ALTER TABLE automation_configs ADD COLUMN mass_apply_max_headcount INTEGER DEFAULT 1000")
            except sqlite3.OperationalError:
                pass
            # 海投打招呼语：非空时 C-F 海投直接复用，跳过每岗现场生成
            try:
                cursor.execute("ALTER TABLE automation_configs ADD COLUMN mass_apply_greeting TEXT DEFAULT ''")
            except sqlite3.OperationalError:
                pass
            # 打招呼语生成平台开关（指挥页 GreetingPanel 配置，JSON: {平台: bool}）
            try:
                cursor.execute("ALTER TABLE automation_configs ADD COLUMN greeting_platforms TEXT DEFAULT ''")
            except sqlite3.OperationalError:
                pass
            # AI 初评并发通道数（默认 5 并发）
            try:
                cursor.execute("ALTER TABLE automation_configs ADD COLUMN eval_concurrency INTEGER DEFAULT 5")
            except sqlite3.OperationalError:
                pass
            # 外部企业联网实时背调开关（默认开启）
            try:
                cursor.execute("ALTER TABLE automation_configs ADD COLUMN enable_company_search BOOLEAN DEFAULT 1")
            except sqlite3.OperationalError:
                pass
            # 简历改写 Skill ID
            try:
                cursor.execute("ALTER TABLE automation_configs ADD COLUMN rewrite_skill_id TEXT DEFAULT 'resume_rewrite'")
            except sqlite3.OperationalError:
                pass
            # 简历改写是否带入深度体检诊断
            try:
                cursor.execute("ALTER TABLE automation_configs ADD COLUMN rewrite_include_diagnosis BOOLEAN DEFAULT 1")
            except sqlite3.OperationalError:
                pass
            # 打招呼语提示词模式 (official 官方标准 / custom 自定义Prompt)
            try:
                cursor.execute("ALTER TABLE automation_configs ADD COLUMN greeting_prompt_mode TEXT DEFAULT 'official'")
            except sqlite3.OperationalError:
                pass
            # 打招呼语自定义 System Prompt 全文
            try:
                cursor.execute("ALTER TABLE automation_configs ADD COLUMN custom_greeting_prompt TEXT DEFAULT ''")
            except sqlite3.OperationalError:
                pass
            # 每日海投发射时间 (默认 09:30)
            try:
                cursor.execute("ALTER TABLE automation_configs ADD COLUMN mass_deliver_time TEXT DEFAULT '09:30'")
            except sqlite3.OperationalError:
                pass
            # 精投岗位发射模式 (immediate 审批后即刻 / scheduled 黄金时段定时)
            try:
                cursor.execute("ALTER TABLE automation_configs ADD COLUMN custom_deliver_mode TEXT DEFAULT 'immediate'")
            except sqlite3.OperationalError:
                pass
            # 精投岗位定时发射时间 (默认 14:00)
            try:
                cursor.execute("ALTER TABLE automation_configs ADD COLUMN custom_deliver_time TEXT DEFAULT '14:00'")
            except sqlite3.OperationalError:
                pass
            # 单岗超时看门狗熔断秒数 (默认 45 秒)
            try:
                cursor.execute("ALTER TABLE automation_configs ADD COLUMN delivery_timeout_sec INTEGER DEFAULT 45")
            except sqlite3.OperationalError:
                pass
            # 定时链路日期范围 (YYYY-MM-DD，空 = 不限；每日 cron 触发时检查今天是否在范围内)
            try:
                cursor.execute("ALTER TABLE automation_configs ADD COLUMN schedule_start_date TEXT DEFAULT ''")
            except sqlite3.OperationalError:
                pass
            try:
                cursor.execute("ALTER TABLE automation_configs ADD COLUMN schedule_end_date TEXT DEFAULT ''")
            except sqlite3.OperationalError:
                pass
            # 非工作日跳过开关 (默认开：周末/法定节假日 HR 不在岗，采集与发射都暂停；调休补班日除外)
            try:
                cursor.execute("ALTER TABLE automation_configs ADD COLUMN skip_non_workdays BOOLEAN DEFAULT 1")
            except sqlite3.OperationalError:
                pass
            # 飞书任务报告推送开关 (默认开)
            try:
                cursor.execute("ALTER TABLE automation_configs ADD COLUMN feishu_enable_report BOOLEAN DEFAULT 1")
            except sqlite3.OperationalError:
                pass
            # 飞书链路异常告警推送开关 (默认开)
            try:
                cursor.execute("ALTER TABLE automation_configs ADD COLUMN feishu_enable_alert BOOLEAN DEFAULT 1")
            except sqlite3.OperationalError:
                pass

            # 由于之前创建了 platform_limits 和 search_*, 我们可以保留列但不去用它，避免删列麻烦

            # 创建日志表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS automation_logs (
                    task_id TEXT PRIMARY KEY,
                    started_at DATETIME NOT NULL,
                    finished_at DATETIME,
                    status TEXT NOT NULL,
                    jobs_processed INTEGER DEFAULT 0,
                    details TEXT
                )
            ''')

            # 海投发射池：只登记「定时链路(stop_at_review)停在审批断点」的岗位。
            # T2 海投发射只消费池内记录——历史遗留的待审批岗位永远不进池、不会被自动投出，
            # 留给用户在岗位列表里手动勾选投递。
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS pending_delivery_pool (
                    record_id TEXT PRIMARY KEY,
                    job_name TEXT DEFAULT '',
                    company_name TEXT DEFAULT '',
                    platform TEXT DEFAULT '',
                    grade TEXT DEFAULT '',
                    task_id TEXT DEFAULT '',
                    parked_at TEXT NOT NULL
                )
            ''')

            # 审批放行标记表：老板在指挥中心点「放行/一键放行」时写入。
            # 定时发射波次以此做双保险：仍停在审批断点但没有放行标记的岗位不得自动发射。
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS boss_approvals (
                    record_id TEXT PRIMARY KEY,
                    approved_at TEXT NOT NULL
                )
            ''')

            # 创建平台状态表（反爬控制互斥锁）
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS platform_status (
                    platform TEXT PRIMARY KEY,
                    status TEXT NOT NULL DEFAULT 'idle',
                    last_operation_start INTEGER,
                    last_operation_end INTEGER,
                    operations_count INTEGER NOT NULL DEFAULT 0
                )
            ''')

            # 二级索引：自动化日志倒序检索与海投池超期清理
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_automation_logs_started
                ON automation_logs(started_at DESC)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_pending_pool_parked
                ON pending_delivery_pool(parked_at)
            ''')

            # 初始化默认配置
            cursor.execute("SELECT COUNT(*) FROM automation_configs WHERE id = 1")
            if cursor.fetchone()[0] == 0:
                default_platforms = json.dumps(["boss", "liepin", "51job", "zhilian"])
                default_grades = json.dumps(["C", "D", "F"])
                default_configs = json.dumps({
                    "boss": {"limit": 0, "keyword": "", "city": "全国", "salary": "不限"},
                    "xiaohongshu": {"limit": 0, "keyword": "", "sort_by": "general"},
                    "liepin": {"limit": 0, "keyword": "", "city": "全国", "salary": "不限"},
                    "zhilian": {"limit": 0, "keyword": "", "city": "全国", "salary": "不限"},
                    "51job": {"limit": 0, "keyword": "", "city": "全国", "salary": "不限"}
                })
                cursor.execute('''
                    INSERT INTO automation_configs
                    (id, cron_time, auto_deliver_grades, auto_deliver_platforms, is_enabled, platform_configs, batch_limit, mass_apply_resume_id, rewrite_base_resume_id, mass_apply_max_headcount, mass_apply_greeting, greeting_platforms, eval_concurrency, enable_company_search, rewrite_skill_id, rewrite_include_diagnosis, greeting_prompt_mode, custom_greeting_prompt, mass_deliver_time, custom_deliver_mode, custom_deliver_time, delivery_timeout_sec)
                    VALUES (1, '09:00', ?, ?, 1, ?, 20, '', '', 1000, '', ?, 5, 1, 'resume_rewrite', 1, 'official', '', '09:30', 'immediate', '14:00', 45)
                ''', (default_grades, default_platforms, default_configs, json.dumps(_DEFAULT_GREETING_PLATFORMS)))
                conn.commit()
    except Exception as e:
        logger.error(f"初始化 autopilot 数据库失败: {e}", exc_info=True)

def get_autopilot_config() -> dict[str, Any]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM automation_configs WHERE id = 1")
        row = cursor.fetchone()
        if row:
            try:
                platform_configs = json.loads(row["platform_configs"]) if "platform_configs" in row.keys() and row["platform_configs"] else {}
            except Exception:
                platform_configs = {}

            try:
                auto_deliver_platforms = json.loads(row["auto_deliver_platforms"]) if "auto_deliver_platforms" in row.keys() and row["auto_deliver_platforms"] else ["boss", "liepin", "51job", "zhilian"]
            except Exception:
                auto_deliver_platforms = ["boss", "liepin", "51job", "zhilian"]

            return {
                "cron_time": row["cron_time"],
                "auto_deliver_grades": json.loads(row["auto_deliver_grades"]),
                "auto_deliver_platforms": auto_deliver_platforms,
                "is_enabled": bool(row["is_enabled"]),
                "batch_limit": row["batch_limit"] if "batch_limit" in row.keys() and row["batch_limit"] is not None else 20,
                "platform_configs": platform_configs,
                "mass_apply_resume_id": (row["mass_apply_resume_id"] if "mass_apply_resume_id" in row.keys() else "") or "",
                "rewrite_base_resume_id": (row["rewrite_base_resume_id"] if "rewrite_base_resume_id" in row.keys() else "") or "",
                "mass_apply_max_headcount": int(row["mass_apply_max_headcount"]) if "mass_apply_max_headcount" in row.keys() and row["mass_apply_max_headcount"] is not None else 1000,
                "mass_apply_greeting": (row["mass_apply_greeting"] if "mass_apply_greeting" in row.keys() else "") or "",
                "greeting_platforms": _parse_greeting_platforms(row["greeting_platforms"] if "greeting_platforms" in row.keys() else ""),
                "eval_concurrency": int(row["eval_concurrency"]) if "eval_concurrency" in row.keys() and row["eval_concurrency"] is not None else 5,
                "enable_company_search": bool(row["enable_company_search"]) if "enable_company_search" in row.keys() and row["enable_company_search"] is not None else True,
                "rewrite_skill_id": (row["rewrite_skill_id"] if "rewrite_skill_id" in row.keys() else "resume_rewrite") or "resume_rewrite",
                "rewrite_include_diagnosis": bool(row["rewrite_include_diagnosis"]) if "rewrite_include_diagnosis" in row.keys() and row["rewrite_include_diagnosis"] is not None else True,
                "greeting_prompt_mode": (row["greeting_prompt_mode"] if "greeting_prompt_mode" in row.keys() else "official") or "official",
                "custom_greeting_prompt": (row["custom_greeting_prompt"] if "custom_greeting_prompt" in row.keys() else "") or "",
                "mass_deliver_time": (row["mass_deliver_time"] if "mass_deliver_time" in row.keys() else "09:30") or "09:30",
                "custom_deliver_mode": (row["custom_deliver_mode"] if "custom_deliver_mode" in row.keys() else "immediate") or "immediate",
                "custom_deliver_time": (row["custom_deliver_time"] if "custom_deliver_time" in row.keys() else "14:00") or "14:00",
                "delivery_timeout_sec": int(row["delivery_timeout_sec"]) if "delivery_timeout_sec" in row.keys() and row["delivery_timeout_sec"] is not None else 45,
                "schedule_start_date": (row["schedule_start_date"] if "schedule_start_date" in row.keys() else "") or "",
                "schedule_end_date": (row["schedule_end_date"] if "schedule_end_date" in row.keys() else "") or "",
                "skip_non_workdays": bool(row["skip_non_workdays"]) if "skip_non_workdays" in row.keys() and row["skip_non_workdays"] is not None else True,
                "feishu_enable_report": bool(row["feishu_enable_report"]) if "feishu_enable_report" in row.keys() and row["feishu_enable_report"] is not None else True,
                "feishu_enable_alert": bool(row["feishu_enable_alert"]) if "feishu_enable_alert" in row.keys() and row["feishu_enable_alert"] is not None else True,
            }
        return {
            "cron_time": "09:00",
            "auto_deliver_grades": ["C", "D", "F"],
            "auto_deliver_platforms": ["boss", "liepin", "51job", "zhilian"],
            "is_enabled": True,
            "batch_limit": 20,
            "platform_configs": {
                "boss": {"limit": 0, "keyword": "", "city": "全国", "salary": "不限"},
                "xiaohongshu": {"limit": 0, "keyword": "", "sort_by": "general"},
                "liepin": {"limit": 0, "keyword": "", "city": "全国", "salary": "不限"},
                "zhilian": {"limit": 0, "keyword": "", "city": "全国", "salary": "不限"},
                "51job": {"limit": 0, "keyword": "", "city": "全国", "salary": "不限"}
            },
            "mass_apply_resume_id": "",
            "rewrite_base_resume_id": "",
            "mass_apply_max_headcount": 1000,
            "mass_apply_greeting": "",
            "greeting_platforms": dict(_DEFAULT_GREETING_PLATFORMS),
            "eval_concurrency": 5,
            "enable_company_search": True,
            "rewrite_skill_id": "resume_rewrite",
            "rewrite_include_diagnosis": True,
            "greeting_prompt_mode": "official",
            "custom_greeting_prompt": "",
            "mass_deliver_time": "09:30",
            "custom_deliver_mode": "immediate",
            "custom_deliver_time": "14:00",
            "delivery_timeout_sec": 45,
            "schedule_start_date": "",
            "schedule_end_date": "",
            "skip_non_workdays": True,
            "feishu_enable_report": True,
            "feishu_enable_alert": True,
        }

def update_autopilot_config(
    cron_time: str = None,
    auto_deliver_grades: list[str] = None,
    auto_deliver_platforms: list[str] = None,
    is_enabled: bool = None,
    platform_configs: dict[str, Any] = None,
    batch_limit: int = None,
    mass_apply_resume_id: str = None,
    rewrite_base_resume_id: str = None,
    mass_apply_max_headcount: int = None,
    mass_apply_greeting: str = None,
    greeting_platforms: dict[str, bool] = None,
    eval_concurrency: int = None,
    enable_company_search: bool = None,
    rewrite_skill_id: str = None,
    rewrite_include_diagnosis: bool = None,
    greeting_prompt_mode: str = None,
    custom_greeting_prompt: str = None,
    mass_deliver_time: str = None,
    custom_deliver_mode: str = None,
    custom_deliver_time: str = None,
    delivery_timeout_sec: int = None,
    schedule_start_date: str = None,
    schedule_end_date: str = None,
    skip_non_workdays: bool = None,
    feishu_enable_report: bool = None,
    feishu_enable_alert: bool = None,
) -> bool:
    """PATCH 语义：仅更新显式传入（非 None）的字段，其余保持库中现值。

    各配置面板只回传自己负责的字段；若此处做全量 UPDATE，
    未回传的字段会被静默重置为默认值，导致跨面板互相覆盖。
    """
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
        updates: dict[str, Any] = {}
        if cron_time is not None:
            updates["cron_time"] = cron_time
        if auto_deliver_grades is not None:
            updates["auto_deliver_grades"] = json.dumps(auto_deliver_grades)
        if auto_deliver_platforms is not None:
            updates["auto_deliver_platforms"] = json.dumps(auto_deliver_platforms)
        if is_enabled is not None:
            updates["is_enabled"] = 1 if is_enabled else 0
        if platform_configs is not None:
            updates["platform_configs"] = json.dumps(platform_configs)
        if batch_limit is not None:
            updates["batch_limit"] = batch_limit
        if mass_apply_resume_id is not None:
            updates["mass_apply_resume_id"] = mass_apply_resume_id or ""
        if rewrite_base_resume_id is not None:
            updates["rewrite_base_resume_id"] = rewrite_base_resume_id or ""
        if mass_apply_max_headcount is not None:
            updates["mass_apply_max_headcount"] = int(mass_apply_max_headcount or 1000)
        if mass_apply_greeting is not None:
            updates["mass_apply_greeting"] = mass_apply_greeting or ""
        if greeting_platforms is not None:
            updates["greeting_platforms"] = json.dumps(
                greeting_platforms if isinstance(greeting_platforms, dict) else _DEFAULT_GREETING_PLATFORMS,
                ensure_ascii=False,
            )
        if eval_concurrency is not None:
            updates["eval_concurrency"] = int(eval_concurrency or 5)
        if enable_company_search is not None:
            updates["enable_company_search"] = 1 if enable_company_search else 0
        if rewrite_skill_id is not None:
            updates["rewrite_skill_id"] = rewrite_skill_id or "resume_rewrite"
        if rewrite_include_diagnosis is not None:
            updates["rewrite_include_diagnosis"] = 1 if rewrite_include_diagnosis else 0
        if greeting_prompt_mode is not None:
            updates["greeting_prompt_mode"] = greeting_prompt_mode or "official"
        if custom_greeting_prompt is not None:
            updates["custom_greeting_prompt"] = custom_greeting_prompt or ""
        if mass_deliver_time is not None:
            updates["mass_deliver_time"] = mass_deliver_time or "09:30"
        if custom_deliver_mode is not None:
            updates["custom_deliver_mode"] = custom_deliver_mode or "immediate"
        if custom_deliver_time is not None:
            updates["custom_deliver_time"] = custom_deliver_time or "14:00"
        if delivery_timeout_sec is not None:
            updates["delivery_timeout_sec"] = int(delivery_timeout_sec or 45)
        if schedule_start_date is not None:
            updates["schedule_start_date"] = schedule_start_date or ""
        if schedule_end_date is not None:
            updates["schedule_end_date"] = schedule_end_date or ""
        if skip_non_workdays is not None:
            updates["skip_non_workdays"] = 1 if skip_non_workdays else 0
        if feishu_enable_report is not None:
            updates["feishu_enable_report"] = 1 if feishu_enable_report else 0
        if feishu_enable_alert is not None:
            updates["feishu_enable_alert"] = 1 if feishu_enable_alert else 0

        if not updates:
            return True
        set_clause = ", ".join(f"{col} = ?" for col in updates)
        cursor.execute(
            f"UPDATE automation_configs SET {set_clause} WHERE id = 1",
            tuple(updates.values()),
        )
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"更新 autopilot 配置失败: {e}", exc_info=True)
        return False

def mark_job_approved(record_id: str) -> bool:
    """登记老板已放行的岗位（审批放行标记，供定时发射波次双保险校验）。"""
    if not record_id:
        return False
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO boss_approvals (record_id, approved_at) VALUES (?, ?)",
                (record_id, datetime.now().isoformat()),
            )
            conn.commit()
            return True
    except Exception as e:
        logger.error(f"登记审批放行标记失败: {e}", exc_info=True)
        return False


def has_approval_mark(record_id: str) -> bool:
    """查询岗位是否已获得老板审批放行标记。查询异常时按已放行处理，避免把真岗位卡死。"""
    if not record_id:
        return False
    try:
        with sqlite3.connect(DB_PATH) as conn:
            row = conn.execute(
                "SELECT 1 FROM boss_approvals WHERE record_id = ? LIMIT 1", (record_id,)
            ).fetchone()
            return bool(row)
    except Exception as e:
        logger.error(f"查询审批放行标记失败: {e}", exc_info=True)
        return True


def get_approval_times(record_ids: list[str]) -> dict[str, str]:
    """批量查询岗位的老板放行时间（record_id -> approved_at），供看板待投递快照按放行时间排序。

    查询异常时返回空 dict，调用方退回抓取时间兜底，不影响快照出数。
    """
    if not record_ids:
        return {}
    try:
        with sqlite3.connect(DB_PATH) as conn:
            placeholders = ",".join("?" for _ in record_ids)
            rows = conn.execute(
                f"SELECT record_id, approved_at FROM boss_approvals WHERE record_id IN ({placeholders})",
                list(record_ids),
            ).fetchall()
            return {row[0]: row[1] for row in rows}
    except Exception as e:
        logger.error(f"批量查询审批放行时间失败: {e}", exc_info=True)
        return {}


def add_jobs_to_pending_pool(records: list[dict[str, Any]]) -> int:
    """把定时链路停在审批断点的岗位登记进海投发射池（重复登记按主键去重）。"""
    if not records:
        return 0
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            cursor.executemany(
                "INSERT OR IGNORE INTO pending_delivery_pool "
                "(record_id, job_name, company_name, platform, grade, task_id, parked_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        r.get("record_id", ""), r.get("job_name", ""), r.get("company_name", ""),
                        r.get("platform", ""), str(r.get("grade", "")).upper(), r.get("task_id", ""), now,
                    )
                    for r in records
                ],
            )
            conn.commit()
            return cursor.rowcount if cursor.rowcount and cursor.rowcount > 0 else 0
    except Exception as e:
        logger.error(f"登记海投发射池失败: {e}", exc_info=True)
        return 0


def get_pending_pool(max_age_days: int = 7) -> list[dict[str, Any]]:
    """读取发射池内的岗位；超过 max_age_days 的陈旧记录自动清理（避免僵尸累积）。"""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cutoff = (datetime.now() - timedelta(days=max_age_days)).isoformat()
            cursor.execute("DELETE FROM pending_delivery_pool WHERE parked_at < ?", (cutoff,))
            conn.commit()
            cursor.execute(
                "SELECT record_id, job_name, company_name, platform, grade, task_id, parked_at "
                "FROM pending_delivery_pool ORDER BY parked_at"
            )
            return [dict(r) for r in cursor.fetchall()]
    except Exception as e:
        logger.error(f"读取海投发射池失败: {e}", exc_info=True)
        return []


def remove_from_pending_pool(record_ids: list[str]) -> None:
    """从发射池移除岗位（已投出/已放行走T3/已拒绝/断点已消失）。"""
    if not record_ids:
        return
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.executemany(
                "DELETE FROM pending_delivery_pool WHERE record_id = ?",
                [(rid,) for rid in record_ids],
            )
            conn.commit()
    except Exception as e:
        logger.error(f"移除海投发射池记录失败: {e}", exc_info=True)


def append_autopilot_log(task_id: str, status: str, jobs_processed: int = 0, details: str = ""):
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            started_at = datetime.now().isoformat()
            cursor.execute(
                "INSERT INTO automation_logs (task_id, started_at, status, jobs_processed, details) VALUES (?, ?, ?, ?, ?)",
                (task_id, started_at, status, jobs_processed, details)
            )
            conn.commit()
    except Exception as e:
        logger.error(f"记录 autopilot 日志失败: {e}", exc_info=True)

def complete_autopilot_log(task_id: str, status: str, jobs_processed: int = 0, details: str = ""):
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            finished_at = datetime.now().isoformat()
            cursor.execute(
                "UPDATE automation_logs SET finished_at = ?, status = ?, jobs_processed = ?, details = ? WHERE task_id = ?",
                (finished_at, status, jobs_processed, details, task_id)
            )
            conn.commit()
    except Exception as e:
        logger.error(f"完成 autopilot 日志记录失败: {e}", exc_info=True)

def get_recent_autopilot_logs(limit: int = 50) -> list[dict[str, Any]]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM automation_logs ORDER BY started_at DESC LIMIT ?", (limit,))
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
