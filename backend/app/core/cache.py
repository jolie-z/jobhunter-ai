import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

from app.core.config import BASE_DIR


class JobCache:
    """岗位列表缓存：内存 + 磁盘快照 + 脏标记。

    设计目标（性能提速改造）：
    - get()      只返回"新鲜"数据（TTL 内），供极速路径命中。
    - get_stale() 返回任何可用数据（内存优先，冷启动时自动加载磁盘快照），
                  配合后台静默刷新实现 stale-while-revalidate：读请求永不阻塞等飞书。
    - patch_record / remove_records  写操作后原地补丁单条记录，替代"整表清空重拉"。
    - mark_dirty  外部变动（飞书事件/webhook）只打脏标记，下次读取时后台刷新。
    - set()      全量刷新后写入，同时持久化磁盘快照（原子替换），后端重启秒恢复。
    - clear()    彻底清空（内存+磁盘），仅用于手动硬刷新 force=1 / refresh-cache。
    """

    _data: list[dict[str, Any]] | None = None
    _timestamp: float = 0
    _ttl: int = 300  # 缓存 5 分钟：兼顾页面切换性能与飞书侧改动的及时性（手动刷新走 force 直连）
    _dirty: bool = False
    _lock: asyncio.Lock = asyncio.Lock()

    _snapshot_path: Path = BASE_DIR / "data" / "job_cache_snapshot.json"
    _disk_loaded: bool = False
    _last_disk_write: float = 0
    _DISK_WRITE_INTERVAL: float = 10.0  # 补丁类更新的落盘节流（秒），全量 set() 不节流

    # ---------- 读取 ----------

    @classmethod
    def get(cls) -> Any | None:
        if cls._data is not None and time.time() - cls._timestamp < cls._ttl:
            return cls._data
        return None

    @classmethod
    def get_stale(cls) -> Any | None:
        """返回任何可用数据（不管新旧）。内存没有时尝试加载磁盘快照（仅一次）。"""
        if cls._data is not None:
            return cls._data
        cls._load_disk()
        return cls._data

    # ---------- 写入 ----------

    @classmethod
    def set(cls, data: Any) -> None:
        cls._data = data
        cls._timestamp = time.time()
        cls._dirty = False
        cls._persist(force=True)

    @classmethod
    def patch_record_fields(cls, record_id: str, fields: dict[str, Any]) -> bool:
        """原地更新单条记录的特定字段；如果内存中有该记录则更新并返回 True。"""
        if cls._data is None or not record_id:
            return False
        for i, existing in enumerate(cls._data):
            if existing.get("record_id") == record_id:
                cls._data[i].update(fields)
                cls._touch()
                return True
        return False

    @classmethod
    def patch_record(cls, job: dict[str, Any]) -> None:
        """单条记录原地更新；缓存中不存在则插到最前（新抓取的岗位）。"""
        if cls._data is None:
            return
        record_id = job.get("record_id")
        if not record_id:
            return
        for i, existing in enumerate(cls._data):
            if existing.get("record_id") == record_id:
                cls._data[i] = job
                cls._touch()
                return
        cls._data.insert(0, job)
        cls._touch()

    @classmethod
    def remove_records(cls, record_ids: list[str]) -> None:
        if cls._data is None or not record_ids:
            return
        id_set = set(record_ids)
        before = len(cls._data)
        cls._data = [j for j in cls._data if j.get("record_id") not in id_set]
        if len(cls._data) != before:
            cls._touch()

    # ---------- 脏标记 ----------

    @classmethod
    def mark_dirty(cls) -> None:
        cls._dirty = True

    @classmethod
    def is_dirty(cls) -> bool:
        return cls._dirty

    @classmethod
    def _reset_for_tests(cls) -> None:
        """仅测试使用：清空全部内存态（含脏标记与磁盘快照加载标志），不触磁盘。"""
        cls._data = None
        cls._timestamp = 0
        cls._dirty = False
        cls._disk_loaded = False

    @classmethod
    def clear(cls) -> None:
        """彻底清空内存与磁盘快照，下次读取强制从飞书全量拉取。"""
        cls._data = None
        cls._timestamp = 0
        cls._dirty = False
        try:
            if cls._snapshot_path.exists():
                cls._snapshot_path.unlink()
        except OSError:
            pass

    # ---------- 内部 ----------

    @classmethod
    def _touch(cls) -> None:
        cls._timestamp = time.time()
        cls._dirty = False
        cls._persist(force=False)

    @classmethod
    def _persist(cls, force: bool) -> None:
        """落盘快照（原子替换）。补丁类更新按间隔节流，避免频繁大文件写。"""
        now = time.time()
        if not force and now - cls._last_disk_write < cls._DISK_WRITE_INTERVAL:
            return
        cls._last_disk_write = now
        if cls._data is None:
            return
        try:
            cls._snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = cls._snapshot_path.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps({"timestamp": cls._timestamp, "jobs": cls._data}, ensure_ascii=False),
                encoding="utf-8",
            )
            os.replace(tmp, cls._snapshot_path)
        except Exception:
            # 落盘失败不影响内存缓存工作，仅损失重启后的秒开能力
            pass

    @classmethod
    def _load_disk(cls) -> None:
        if cls._disk_loaded:
            return
        cls._disk_loaded = True
        try:
            if not cls._snapshot_path.exists():
                return
            payload = json.loads(cls._snapshot_path.read_text(encoding="utf-8"))
            jobs = payload.get("jobs")
            if isinstance(jobs, list) and jobs:
                cls._data = jobs
                cls._timestamp = float(payload.get("timestamp", 0))
                print(f"⚡ 已从磁盘快照恢复岗位缓存 {len(jobs)} 条（快照时间 {_format_ts(cls._timestamp)}），将后台静默刷新")
        except Exception:
            # 快照损坏时静默放弃，走正常全量拉取
            pass


def _format_ts(ts: float) -> str:
    if not ts:
        return "未知"
    try:
        from datetime import datetime

        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return "未知"
