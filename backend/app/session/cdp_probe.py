"""CDP 通道真实探活 — 端口通 ≠ 浏览器可用。

背景（2026-10-08 51job 事故）：专用 Edge 僵死后 HTTP /json 仍可应答（会话健康
检查全程 healthy），但 CDP websocket 命令永不响应，采集器 connect_over_cdp 每次
挂满超时、调度器逐页连烧 40 分钟。TCP 探活（probe_port）与 HTTP 状态码都识别不了
这种「半死」态，必须发一条真实 CDP 命令看它答不答。

三态判定（勿坍缩）：
- "alive"  : HTTP /json/version 2xx 且 websocket 命令在时限内收到应答
- "zombie" : 有监听者但 CDP 命令通道不可用——websocket 连得上不应答、HTTP 超时/
             非 2xx/无 webSocketDebuggerUrl 都算。监听在而服务不可用，唯一正确的
             修复动作是重启浏览器（拉起没有意义，端口明明被占着）
- "down"   : 连接被立即拒绝（RST）——确定无监听者，走拉起路径

本模块不 import app.*（仅标准库 + websocket-client，后者 browser.py 已依赖），
保持可独立单测；websocket 层允许测试注入 fake connection。
"""

import json
import logging
import urllib.request

logger = logging.getLogger(__name__)

_HTTP_TIMEOUT_S = 1.5
_WS_CMD_TIMEOUT_S = 3.0
_WS_CMD = {"id": 1, "method": "Target.getTargets", "params": {}}


def _http_get_version(port: int, host: str) -> dict | None:
    """GET /json/version。返回解析后的 JSON；确定无监听抛 ConnectionRefusedError；
    其他失败（超时/非2xx/坏 JSON）抛异常由调用方按僵尸归类。"""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(f"http://{host}:{port}/json/version", timeout=_HTTP_TIMEOUT_S) as resp:
        if not (200 <= resp.status < 300):
            raise RuntimeError(f"HTTP {resp.status}")
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def _ws_roundtrip(ws_url: str, create_connection=None) -> None:
    """发一条真实 CDP 命令并等应答；任何异常=通道不可用。create_connection 可注入供单测。"""
    import websocket
    connect = create_connection or websocket.create_connection
    ws = connect(ws_url, timeout=_WS_CMD_TIMEOUT_S)
    try:
        ws.send(json.dumps(_WS_CMD))
        ws.recv()
    finally:
        try:
            ws.close()
        except Exception:
            pass


def probe_cdp_channel(port: int, host: str = "127.0.0.1", create_connection=None) -> str:
    """探测 CDP 命令通道是否真实可用。返回 "alive" / "zombie" / "down"。

    create_connection 参数仅供单测注入（签名同 websocket.create_connection）。
    """
    try:
        info = _http_get_version(port, host)
    except ConnectionRefusedError:
        return "down"
    except urllib.error.URLError as e:
        if isinstance(getattr(e, "reason", None), ConnectionRefusedError):
            return "down"
        # 超时/其他：TCP 被受理（否则是 RST）但 HTTP 不可用 → 有监听者而服务不可用
        logger.warning("[cdp_probe] 端口 %s HTTP 探测不可用（僵尸特征）: %r", port, e)
        return "zombie"
    except Exception as e:
        logger.warning("[cdp_probe] 端口 %s HTTP 探测不可用（僵尸特征）: %r", port, e)
        return "zombie"

    ws_url = (info or {}).get("webSocketDebuggerUrl") if isinstance(info, dict) else None
    if not ws_url:
        logger.warning("[cdp_probe] 端口 %s /json/version 缺 webSocketDebuggerUrl，按僵尸处理", port)
        return "zombie"

    try:
        _ws_roundtrip(ws_url, create_connection=create_connection)
        return "alive"
    except Exception as e:
        logger.warning("[cdp_probe] 端口 %s CDP 命令通道无响应（僵尸特征）: %r", port, e)
        return "zombie"
