"""
飞书消息幂等防重锁（webhook 与 WS 长连接共用）。

两条收消息通道可能同时在线（事件订阅方式切换期/兜底并存），
同一 message_id 必须只处理一次，防止重复触发 Agent/建岗。

防重锁三层加固（2026-09 重复回复专项）：
- 进程内存 + 磁盘持久化双层：后端重启后仍能拦截飞书 at-least-once 重投
  （旧实现纯内存，重启即清空，重投落在 300s 时间守卫窗口内就会重复处理）；
- LRU 淘汰（OrderedDict），替代旧实现的「超限整表清空」——整表清空会让
  清空瞬间所有近期消息瞬间失去防重保护；
- TTL 30 分钟：飞书重投窗口为分钟级（时间守卫已滤 300s 外的旧消息），
  超龄条目无保护价值，持久化文件也不会无限膨胀。
"""

import json
import threading
import time
from collections import OrderedDict
from pathlib import Path

_MAX_SEEN = 5000
_TTL_SECONDS = 30 * 60

# backend/app/core/feishu_msg_dedup.py → parents[2] = backend/
_PERSIST_PATH = Path(__file__).resolve().parents[2] / "data" / "feishu_seen_msg_ids.json"

_seen: "OrderedDict[str, float]" = OrderedDict()
_lock = threading.Lock()
_loaded = False


def _load_locked() -> None:
    """首次使用时从磁盘恢复（进程内仅加载一次，须持有 _lock）。"""
    global _loaded
    _loaded = True
    try:
        if _PERSIST_PATH.exists():
            data = json.loads(_PERSIST_PATH.read_text() or "{}")
            now = time.time()
            for mid, ts in (data.get("seen") or {}).items():
                if now - float(ts) <= _TTL_SECONDS:
                    _seen[str(mid)] = float(ts)
    except Exception:
        pass  # 防重锁文件损坏时降级为纯内存模式，绝不阻塞消息主链路


def _persist_locked() -> None:
    """把当前防重状态原子落盘（须持有 _lock；失败静默，内存层仍在工作）。"""
    try:
        _PERSIST_PATH.parent.mkdir(parents=True, exist_ok=True)
        now = time.time()
        data = {"seen": {mid: ts for mid, ts in _seen.items() if now - ts <= _TTL_SECONDS}}
        tmp = _PERSIST_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False))
        tmp.replace(_PERSIST_PATH)
    except Exception:
        pass


def check_and_mark(message_id: str) -> bool:
    """消息未处理过返回 True 并记录；已处理过（TTL 内）返回 False。"""
    if not message_id:
        return True
    now = time.time()
    with _lock:
        if not _loaded:
            _load_locked()
        prev = _seen.get(message_id)
        if prev is not None and now - prev <= _TTL_SECONDS:
            return False
        _seen[message_id] = now
        _seen.move_to_end(message_id)
        while len(_seen) > _MAX_SEEN:
            _seen.popitem(last=False)
        _persist_locked()
        return True
