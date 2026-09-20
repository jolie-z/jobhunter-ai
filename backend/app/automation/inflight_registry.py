"""
进行中评估登记表：跨重启的「岗位评估正在跑」事实源。

流水线启动时登记 (chat_id, record_id, card_msg_id, started_epoch)，正常结束/失败后注销；
进程被杀时来不及注销，恰好留下断点现场——服务重启后由启动恢复执行器
（job_entry_chat.resume_inflight_evaluations）按本表续跑评估或把孤儿进度卡标红。

JSON 落盘 + 原子写（tmp + os.replace）。加载时按 TTL 兜底清理，防止永久残留。
"""

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

from app.core.config import BASE_DIR

logger = logging.getLogger(__name__)

_REGISTRY_PATH = Path(BASE_DIR) / "data" / "inflight_pipelines.json"
# 兜底 TTL：超过该时长的登记项在加载时静默清理（正常生命周期由注销负责，这只是防残留）
_REGISTRY_TTL_SECONDS = 24 * 3600

_lock = threading.Lock()
_cache: dict[str, dict[str, Any]] | None = None


def _load() -> dict[str, dict[str, Any]]:
    global _cache
    if _cache is not None:
        return _cache
    try:
        if _REGISTRY_PATH.exists():
            raw = json.loads(_REGISTRY_PATH.read_text())
            now = time.time()
            data = {
                rid: entry for rid, entry in raw.items()
                if isinstance(entry, dict) and now - float(entry.get("started_epoch", 0)) < _REGISTRY_TTL_SECONDS
            }
        else:
            data = {}
    except Exception as e:
        logger.warning(f"[评估登记表] 加载失败（按空表处理）: {e}")
        data = {}
    _cache = data
    return _cache


def _save(data: dict[str, dict[str, Any]]) -> None:
    try:
        _REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _REGISTRY_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        os.replace(tmp, _REGISTRY_PATH)
    except Exception as e:
        logger.warning(f"[评估登记表] 保存失败（忽略）: {e}")


def register(record_id: str, chat_id: str, card_msg_id: str = "",
             company: str = "", job: str = "", started_epoch: float | None = None) -> None:
    """登记一次进行中的评估。started_epoch 用墙钟时间，保证跨重启计时连续。"""
    with _lock:
        data = _load()
        data[str(record_id)] = {
            "chat_id": str(chat_id or ""),
            "card_msg_id": str(card_msg_id or ""),
            "company": str(company or ""),
            "job": str(job or ""),
            "started_epoch": float(started_epoch if started_epoch is not None else time.time()),
            "materials_delivered": False,
        }
        _save(data)


def unregister(record_id: str) -> None:
    with _lock:
        data = _load()
        if data.pop(str(record_id), None) is not None:
            _save(data)


def has(record_id: str) -> bool:
    with _lock:
        return str(record_id) in _load()


def get(record_id: str) -> dict[str, Any] | None:
    with _lock:
        entry = _load().get(str(record_id))
        return dict(entry) if entry else None


def mark_materials_delivered(record_id: str) -> None:
    """物料已送达聊天框后调用：恢复器据此跳过补发，避免物料重复投递。"""
    with _lock:
        data = _load()
        entry = data.get(str(record_id))
        if entry is not None:
            entry["materials_delivered"] = True
            _save(data)


def list_entries() -> dict[str, dict[str, Any]]:
    with _lock:
        return {rid: dict(entry) for rid, entry in _load().items()}


def reset_for_test(path: Path | None = None) -> None:
    """仅测试用：重置内存缓存并指向临时文件。"""
    global _cache, _REGISTRY_PATH
    with _lock:
        _cache = None
        if path is not None:
            _REGISTRY_PATH = Path(path)
