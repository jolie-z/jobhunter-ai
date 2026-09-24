"""
简历解析快照服务（原文底稿 + 待确认标记 + 修正回流）。

快照目录：backend/data/resume_snapshots/{snapshot_id}/
  source.{ext}   原始上传文件（解析管线阅后即焚前拷贝留存）
  original.md    解析中间文本（markitdown 产出、AI 结构化的输入）
  parsed.json    初始结构化结果（含 personalInfo，不含 _meta；重试后覆盖）
  meta.json      { snapshot_id, source_filename, feishu_file_token?, created_at, confidence }

snapshot_id = 上传 task_id（uuid），随 structured 的 _meta.snapshot_id 前端流转；
用户保存简历时经 /save 透传回后端，写飞书「原件快照ID/原件附件」字段并记录修正差异。
"""

import hashlib
import json
import logging
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.db_bootstrap import resolve_main_db_path
from app.core.resume_confidence import score_resume_confidence

logger = logging.getLogger("resume_snapshot_service")

SNAPSHOT_ROOT = Path(__file__).resolve().parents[2] / "data" / "resume_snapshots"

# snapshot_id 只允许 uuid 形态字符，路由层同样校验（防路径穿越双保险）
_SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9_-]+$")

# 飞书简历表快照字段
FIELD_SNAPSHOT_ID = "原件快照ID"
FIELD_SNAPSHOT_FILE = "原件附件"

_CORRECTIONS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS resume_parse_corrections (
  id TEXT PRIMARY KEY,
  snapshot_id TEXT NOT NULL,
  module_key TEXT NOT NULL,
  initial_text TEXT,
  corrected_text TEXT,
  corrected_hash TEXT,
  created_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_resume_corrections_dedup
  ON resume_parse_corrections(snapshot_id, module_key, corrected_hash);
"""

# 修正 diff 只看业务模块（_meta/personalInfo 等非业务键剔除）
_DIFF_MODULE_KEYS = ("summary", "workExperience", "personalProjects", "education", "additional", "customModules")
_DIFF_SKIP_KEYS = {"_meta", "personalInfo", "moduleOrder", "moduleTitles"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_snapshot_id(snapshot_id: str) -> str:
    if not snapshot_id or not _SAFE_ID_RE.fullmatch(snapshot_id):
        raise ValueError(f"非法快照 ID: {snapshot_id!r}")
    return snapshot_id


def snapshot_dir(snapshot_id: str) -> Path:
    """快照目录的规范化路径；越出根目录即拒绝（路径穿越双保险之二）。"""
    _validate_snapshot_id(snapshot_id)
    resolved = (SNAPSHOT_ROOT / snapshot_id).resolve()
    if resolved.parent != SNAPSHOT_ROOT.resolve():
        raise ValueError(f"快照路径越界: {snapshot_id!r}")
    return resolved


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def _read_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def save_snapshot(
    snapshot_id: str,
    source_bytes: bytes,
    source_filename: str,
    original_md: str,
    structured: dict,
) -> dict:
    """解析就绪时留存四件套并给 structured 挂 _meta；返回带 _meta 的新 structured。

    原文件已在调用方读入内存（阅后即焚前），此处只写盘不碰临时文件。
    structured 中的 personalInfo 会先摘出再写 parsed.json，保证与最终保存形态一致。
    """
    sdir = snapshot_dir(snapshot_id)
    sdir.mkdir(parents=True, exist_ok=True)

    ext = Path(source_filename or "resume.bin").suffix.lstrip(".") or "bin"
    safe_ext = re.sub(r"[^a-zA-Z0-9]", "", ext)[:8] or "bin"
    (sdir / f"source.{safe_ext}").write_bytes(source_bytes)
    (sdir / "original.md").write_text(original_md or "", encoding="utf-8")

    parsed_core = {k: v for k, v in structured.items() if k != "_meta"}
    _write_json(sdir / "parsed.json", parsed_core)

    confidence = score_resume_confidence(parsed_core)
    meta = {
        "snapshot_id": snapshot_id,
        "source_filename": source_filename or "",
        "feishu_file_token": None,
        "created_at": _now_iso(),
        "confidence": confidence,
    }
    _write_json(sdir / "meta.json", meta)

    out = dict(parsed_core)
    out["_meta"] = {"snapshot_id": snapshot_id, "confidence": confidence, "parsed_at": meta["created_at"]}
    logger.info(f"[resume_snapshot_service] 快照已留存 {snapshot_id}（source {len(source_bytes)}B）")
    return out


def update_snapshot_parsed(snapshot_id: str, structured: dict) -> dict:
    """重试解析成功后覆盖 parsed.json 与 meta.json 的置信度（snapshot_id/原件不变）。

    首轮解析未及落盘（目录不存在）时自动补建目录，保证重试后修正回流有基准可比。
    """
    sdir = snapshot_dir(snapshot_id)
    sdir.mkdir(parents=True, exist_ok=True)
    parsed_core = {k: v for k, v in structured.items() if k != "_meta"}
    _write_json(sdir / "parsed.json", parsed_core)

    meta = _read_json(sdir / "meta.json") or {}
    meta["confidence"] = score_resume_confidence(parsed_core)
    _write_json(sdir / "meta.json", meta)

    out = dict(parsed_core)
    out["_meta"] = {
        "snapshot_id": snapshot_id,
        "confidence": meta["confidence"],
        "parsed_at": meta.get("created_at") or _now_iso(),
    }
    return out


def get_snapshot(snapshot_id: str) -> dict | None:
    """读取快照元数据与中间文本；不存在返回 None。"""
    sdir = snapshot_dir(snapshot_id)
    meta = _read_json(sdir / "meta.json")
    original_path = sdir / "original.md"
    if meta is None and not original_path.exists():
        return None
    source_files = list(sdir.glob("source.*")) if sdir.exists() else []
    try:
        original_md = original_path.read_text(encoding="utf-8")
    except OSError:
        original_md = ""
    return {
        "snapshot_id": snapshot_id,
        "source_filename": (meta or {}).get("source_filename", ""),
        "source_available": bool(source_files),
        "original_markdown": original_md,
        "created_at": (meta or {}).get("created_at", ""),
        "confidence": (meta or {}).get("confidence", {}),
    }


def get_snapshot_file(snapshot_id: str) -> tuple[Path, str] | None:
    """返回 (原文件路径, 文件名)；无原件返回 None。"""
    sdir = snapshot_dir(snapshot_id)
    files = sorted(sdir.glob("source.*")) if sdir.exists() else []
    if not files:
        return None
    meta = _read_json(sdir / "meta.json") or {}
    filename = meta.get("source_filename") or files[0].name
    return files[0], filename


async def ensure_snapshot_feishu_token(snapshot_id: str) -> str | None:
    """确保飞书附件已上传：meta 有 token 直接用，无则读本地原件补传并回写 meta。

    供保存链路取附件 token；失败返回 None（降级为仅写「原件快照ID」文本字段）。
    """
    sdir = snapshot_dir(snapshot_id)
    meta = _read_json(sdir / "meta.json")
    if meta is None:
        return None
    if meta.get("feishu_file_token"):
        return meta["feishu_file_token"]

    file_info = get_snapshot_file(snapshot_id)
    if not file_info:
        return None
    path, filename = file_info
    try:
        from app.core.feishu_client import feishu_client

        token = await feishu_client.upload_bitable_attachment(path.read_bytes(), filename)
        meta["feishu_file_token"] = token
        _write_json(sdir / "meta.json", meta)
        return token
    except Exception:
        logger.exception(f"[resume_snapshot_service] 飞书附件补传失败 {snapshot_id}（降级：仅写快照ID字段）")
        return None


_fields_ensured = False


async def ensure_resume_snapshot_fields() -> bool:
    """幂等确保飞书简历表有快照两字段。

    返回 True=字段可用；False=创建失败（调用方必须跳过快照字段写入，否则
    飞书会因未知字段拒绝整条记录，阻塞简历保存）。进程内仅成功一次（失败不缓存，下次重试）。
    """
    global _fields_ensured
    if _fields_ensured:
        return True
    table_id = settings.FEISHU_TABLE_ID_RESUMES
    if not table_id:
        return False
    try:
        from app.core.feishu_client import feishu_client

        await feishu_client.create_bitable_field(table_id, FIELD_SNAPSHOT_ID, field_type=1)
        await feishu_client.create_bitable_field(table_id, FIELD_SNAPSHOT_FILE, field_type=17)
        _fields_ensured = True
        logger.info("[resume_snapshot_service] 飞书快照字段就绪")
        return True
    except Exception:
        logger.exception("[resume_snapshot_service] 飞书快照字段创建失败（本次保存跳过字段写入，下次重试）")
        return False


def _ensure_corrections_table(conn: sqlite3.Connection) -> None:
    conn.executescript(_CORRECTIONS_TABLE_SQL)


def _module_text(structured: dict, key: str) -> str:
    """模块内容规范化为可比对文本（dict/list 统一 JSON 序列化，剔除 _key 等渲染辅助键）。"""
    value = structured.get(key)
    if value is None:
        return ""
    if isinstance(value, list):
        cleaned = [
            {k: v for k, v in item.items() if k != "_key"} if isinstance(item, dict) else item
            for item in value
        ]
        return json.dumps(cleaned, ensure_ascii=False, sort_keys=True)
    if isinstance(value, dict):
        # dict 形态（如 customModules: Record<key, ExperienceV2[]>）的值多为列表条目，同样剔除 _key
        cleaned = {
            k: [{ik: iv for ik, iv in item.items() if ik != "_key"} if isinstance(item, dict) else item for item in items]
            if isinstance(items, list) else items
            for k, items in value.items()
        }
        return json.dumps(cleaned, ensure_ascii=False, sort_keys=True)
    return str(value)


def record_corrections(snapshot_id: str, final_structured: dict) -> int:
    """对比初始解析与最终保存，差异模块写错题本（同内容去重）。返回新增条数。

    旁路数据：任何失败只告警返回 0，绝不阻塞简历保存。
    """
    try:
        initial = _read_json(snapshot_dir(snapshot_id) / "parsed.json")
        if not isinstance(initial, dict) or not isinstance(final_structured, dict):
            return 0

        rows: list[tuple[str, str, str, str, str, str, str]] = []
        now = _now_iso()
        for key in _DIFF_MODULE_KEYS:
            if key in _DIFF_SKIP_KEYS:
                continue
            initial_text = _module_text(initial, key)
            corrected_text = _module_text(final_structured, key)
            if initial_text == corrected_text:
                continue
            digest = hashlib.sha256(corrected_text.encode("utf-8")).hexdigest()
            rows.append((uuid.uuid4().hex, snapshot_id, key, initial_text[:20000], corrected_text[:20000], digest, now))

        if not rows:
            return 0

        db_path = resolve_main_db_path()
        with sqlite3.connect(db_path) as conn:
            _ensure_corrections_table(conn)
            before = conn.total_changes
            conn.executemany(
                "INSERT OR IGNORE INTO resume_parse_corrections "
                "(id, snapshot_id, module_key, initial_text, corrected_text, corrected_hash, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            added = conn.total_changes - before
        if added:
            logger.info(f"[resume_snapshot_service] 错题本新增 {added} 条（{snapshot_id}）")
        return added
    except Exception:
        logger.exception(f"[resume_snapshot_service] 修正记录失败（忽略） {snapshot_id}")
        return 0


def list_corrections(limit: int = 100) -> list[dict]:
    """错题本列表（新→旧）。"""
    db_path = resolve_main_db_path()
    with sqlite3.connect(db_path) as conn:
        _ensure_corrections_table(conn)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, snapshot_id, module_key, initial_text, corrected_text, created_at "
            "FROM resume_parse_corrections ORDER BY created_at DESC LIMIT ?",
            (max(1, min(limit, 500)),),
        ).fetchall()
    return [dict(r) for r in rows]
