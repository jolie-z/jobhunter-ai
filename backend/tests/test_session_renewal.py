"""会话续期心跳单测：按平台独立跳过，常驻浏览器不再拖死其他平台的续期。"""
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.session import renewal  # noqa: E402
from app.session.models import PlatformConfig  # noqa: E402


def _mk_cfg(name: str, port: int) -> PlatformConfig:
    return PlatformConfig(
        name=name,
        display_name=name,
        browser_type="drissionpage",
        profile_dir=f"/tmp/does-not-matter/{name}",
        port=port,
        login_check_url=f"https://www.{name}.example.com/",
    )


class _ProbeStub:
    """probe_port 打桩：busy_ports 中的端口视为被占用。"""

    def __init__(self, busy_ports: set[int]):
        self.busy_ports = busy_ports
        self.calls: list[int] = []

    def __call__(self, port: int, host: str = "127.0.0.1", timeout: float = 2.0) -> bool:
        self.calls.append(port)
        return port in self.busy_ports


@pytest.fixture
def teardown_module_state(monkeypatch):
    """防止用例间复用 monkeypatch 残留（本文件各用例自备打桩）。"""
    yield


def test_busy_platform_skipped_but_others_renewed(monkeypatch):
    """关键回归：智联常驻（9250 占用）时，BOSS/51job/猎聘必须照常续期。"""
    probe = _ProbeStub(busy_ports={9250})
    monkeypatch.setattr(renewal, "probe_port", probe)

    launched = []
    monkeypatch.setattr(
        renewal, "launch_edge", lambda cfg, url=None: launched.append(cfg.name) or {}
    )
    closed = []
    monkeypatch.setattr(
        renewal, "_close_port_gracefully", lambda port: closed.append(port)
    )
    # 续期等待 25s 缩到 0，用例秒回
    monkeypatch.setattr(renewal.time, "sleep", lambda _s: None)

    cfgs = {
        "boss": _mk_cfg("boss", 19222),
        "zhilian": _mk_cfg("zhilian", 9250),
        "51job": _mk_cfg("51job", 9227),
        "liepin": _mk_cfg("liepin", 9226),
    }
    monkeypatch.setattr(
        renewal, "PLATFORM_CONFIGS", cfgs | renewal.PLATFORM_CONFIGS
    )

    renewal.renew_all_sessions()

    # 智联被跳过：不拉起；其余 3 平台都完成拉起+优雅关闭
    assert "zhilian" not in launched, "被占用平台不应拉起浏览器"
    assert sorted(launched) == ["51job", "boss", "liepin"]
    assert sorted(closed) == [9226, 9227, 19222]
    assert 9250 not in closed, "被占用平台不应发起关闭指令"


def test_all_platforms_busy_none_launched(monkeypatch):
    """全部端口被占用：一个都不拉起，静默收场。"""
    probe = _ProbeStub(busy_ports={19222, 9250, 9227, 9226})
    monkeypatch.setattr(renewal, "probe_port", probe)

    launched = []
    monkeypatch.setattr(
        renewal, "launch_edge", lambda cfg, url=None: launched.append(cfg.name) or {}
    )
    monkeypatch.setattr(
        renewal, "_close_port_gracefully", lambda port: None
    )

    cfgs = {k: _mk_cfg(k, p) for k, p in
            [("boss", 19222), ("zhilian", 9250), ("51job", 9227), ("liepin", 9226)]}
    monkeypatch.setattr(
        renewal, "PLATFORM_CONFIGS", cfgs | renewal.PLATFORM_CONFIGS
    )

    renewal.renew_all_sessions()
    assert launched == []


def test_launch_failure_does_not_break_remaining(monkeypatch):
    """某平台拉起抛异常：兜底关闭后继续处理后续平台。"""
    monkeypatch.setattr(renewal, "probe_port", _ProbeStub(busy_ports=set()))

    def fake_launch(cfg, url=None):
        if cfg.name == "boss":
            raise RuntimeError("Edge 可执行文件缺失")
        return {}

    launched = []
    monkeypatch.setattr(renewal, "launch_edge", lambda cfg, url=None:
                        launched.append(cfg.name) or fake_launch(cfg, url))
    closed = []
    monkeypatch.setattr(
        renewal, "_close_port_gracefully", lambda port: closed.append(port)
    )
    monkeypatch.setattr(renewal.time, "sleep", lambda _s: None)

    cfgs = {k: _mk_cfg(k, p) for k, p in
            [("boss", 19222), ("zhilian", 9250), ("51job", 9227), ("liepin", 9226)]}
    monkeypatch.setattr(
        renewal, "PLATFORM_CONFIGS", cfgs | renewal.PLATFORM_CONFIGS
    )

    renewal.renew_all_sessions()

    # boss 异常但兜底关闭已执行；其余平台照常续期
    assert 19222 in closed
    assert sorted(launched) == ["51job", "boss", "liepin", "zhilian"]
    assert {9250, 9227, 9226}.issubset(set(closed))
