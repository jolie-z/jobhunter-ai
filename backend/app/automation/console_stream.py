"""
后端实时日志流（指挥页右侧「实时日志」面板的数据源）
====================================================
- 把 sys.stdout（各爬虫/引擎的 print）与 logging（app 各模块 logger）
  统一 tee 进一个环形缓冲（最近 800 行），并扇形分发给 SSE 订阅者。
- 线程安全：爬虫跑在 to_thread/子线程里，用 call_soon_threadsafe 投递。
- SSE 端点：GET /api/automation/console-stream，先回放快照再实时推送。
"""
import asyncio
import collections
import json
import logging
import sys
import threading

_buffer: collections.deque = collections.deque(maxlen=800)
_lock = threading.Lock()
_subscribers: "set[asyncio.Queue]" = set()
_loop: "asyncio.AbstractEventLoop | None" = None


def _fanout(line: str):
    line = line.rstrip("\n")
    if not line.strip():
        return
    with _lock:
        _buffer.append(line)
        subs = list(_subscribers)
    if subs and _loop:
        for q in subs:
            try:
                _loop.call_soon_threadsafe(q.put_nowait, line)
            except Exception:
                pass


class _StdoutTee:
    """把 print 输出同时写入原 stdout 与日志流。"""

    def __init__(self, original):
        self._orig = original

    def write(self, s):
        try:
            if s and s.strip():
                _fanout(s)
        except Exception:
            pass
        try:
            return self._orig.write(s)
        except Exception:
            return 0

    def flush(self):
        try:
            return self._orig.flush()
        except Exception:
            return None

    def __getattr__(self, name):
        return getattr(self._orig, name)


class _LogHandler(logging.Handler):
    """把 logging 记录喂进同一条日志流。"""

    def emit(self, record):
        try:
            _fanout(self.format(record))
        except Exception:
            pass


def install():
    """在 FastAPI startup 调用：接管 stdout + 挂 root logging handler。"""
    global _loop
    try:
        _loop = asyncio.get_running_loop()
    except Exception:
        _loop = None
    if not isinstance(sys.stdout, _StdoutTee):
        sys.stdout = _StdoutTee(sys.stdout)
    root = logging.getLogger()
    if not any(isinstance(h, _LogHandler) for h in root.handlers):
        handler = _LogHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(name)s | %(message)s", "%H:%M:%S"))
        root.addHandler(handler)
    # 🌟 root 默认 WARNING 会把编排层所有 logger.info 在发射前就丢掉——白盒控制台因此
    # 一直看不到投递大盘/每岗发射进度/落幕战报。显式放开 app 模块日志到 INFO。
    logging.getLogger("app").setLevel(logging.INFO)
    # 🌟 策略层历史 logger 名不在 app.* 命名空间下，继承 root 的 WARNING 级，INFO 全被
    # 发射前丢弃——ATS 靶向链路（strategy_ai_diagnosis 等）的分段计时/Step 日志因此一直
    # 不可见。显式放开这批既有命名空间。
    for name in (
        "strategy_ai_diagnosis",
        "strategy_service",
        "strategy_config_service",
        "resume_structurer",
    ):
        logging.getLogger(name).setLevel(logging.INFO)


def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=2000)
    with _lock:
        _subscribers.add(q)
    return q


def unsubscribe(q: asyncio.Queue):
    with _lock:
        _subscribers.discard(q)


def snapshot():
    with _lock:
        return list(_buffer)


def sse_line(line: str) -> str:
    return f"data: {json.dumps({'line': line}, ensure_ascii=False)}\n\n"
