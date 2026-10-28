"""cdp_probe 单测：CDP 命令通道三态探活（alive / zombie / down）。

全 mock（HTTP 层与 websocket 连接均可注入），绝不真开浏览器/真连端口。
背景：2026-10-08 51job 僵尸 Edge 事故——HTTP /json 活着但 CDP 命令永不响应，
TCP/HTTP 探活全绿，必须发真实 CDP 命令才能识别。
"""

import sys
from pathlib import Path

import pytest

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_BACKEND_ROOT),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from app.session import cdp_probe
from app.session.cdp_probe import probe_cdp_channel


# ---------- HTTP 层三态 ----------

def test_down_on_connection_refused(monkeypatch):
    """连接被立即拒绝（RST）= 确定无监听者 → down（走拉起路径）。"""
    def _refused(port, host):
        raise ConnectionRefusedError("refused")
    monkeypatch.setattr(cdp_probe, "_http_get_version", _refused)
    assert probe_cdp_channel(9227) == "down"


def test_down_on_urLError_wrapped_refused(monkeypatch):
    import urllib.error
    def _wrapped(port, host):
        raise urllib.error.URLError(ConnectionRefusedError(111, "refused"))
    monkeypatch.setattr(cdp_probe, "_http_get_version", _wrapped)
    assert probe_cdp_channel(9227) == "down"


def test_zombie_on_http_timeout(monkeypatch):
    """HTTP 超时（TCP 被受理但服务不应答）= 有监听者而服务不可用 → zombie（重启是唯一修复）。"""
    def _timeout(port, host):
        raise TimeoutError("timed out")
    monkeypatch.setattr(cdp_probe, "_http_get_version", _timeout)
    assert probe_cdp_channel(9227) == "zombie"


def test_zombie_on_http_500(monkeypatch):
    def _err(port, host):
        raise RuntimeError("HTTP 500")
    monkeypatch.setattr(cdp_probe, "_http_get_version", _err)
    assert probe_cdp_channel(9227) == "zombie"


# ---------- websocket 命令层（HTTP 200 之后） ----------

def test_alive_when_ws_responds(monkeypatch):
    """HTTP 2xx + CDP 命令在时限内应答 → alive。"""
    monkeypatch.setattr(cdp_probe, "_http_get_version", lambda port, host: {"webSocketDebuggerUrl": "ws://fake"})

    class _FakeWs:
        def send(self, payload):
            assert "Target.getTargets" in payload
        def recv(self):
            return '{"id":1,"result":{}}'
        def close(self):
            pass

    def _fake_connect(url, timeout=None):
        assert timeout == cdp_probe._WS_CMD_TIMEOUT_S
        return _FakeWs()

    assert probe_cdp_channel(9227, create_connection=_fake_connect) == "alive"


def test_zombie_when_ws_never_responds(monkeypatch):
    """HTTP 2xx 但 CDP 命令永不响应（51job 僵尸事故的精确特征）→ zombie。"""
    monkeypatch.setattr(cdp_probe, "_http_get_version", lambda port, host: {"webSocketDebuggerUrl": "ws://fake"})

    class _ZombieWs:
        def send(self, payload):
            pass
        def recv(self):
            raise TimeoutError("recv timed out")
        def close(self):
            pass

    def _zombie_connect(url, timeout=None):
        return _ZombieWs()

    assert probe_cdp_channel(9227, create_connection=_zombie_connect) == "zombie"


def test_zombie_when_ws_connect_fails(monkeypatch):
    """websocket 握手失败（HTTP 层活着但 ws 端点拒绝）→ zombie。"""
    monkeypatch.setattr(cdp_probe, "_http_get_version", lambda port, host: {"webSocketDebuggerUrl": "ws://fake"})

    def _dead_connect(url, timeout=None):
        raise ConnectionResetError("handshake failed")

    assert probe_cdp_channel(9227, create_connection=_dead_connect) == "zombie"


def test_zombie_when_no_ws_url(monkeypatch):
    """/json/version 返回 2xx 但缺 webSocketDebuggerUrl（非典型 CDP 服务）→ zombie。"""
    monkeypatch.setattr(cdp_probe, "_http_get_version", lambda port, host: {"Browser": "fake"})
    assert probe_cdp_channel(9227) == "zombie"
