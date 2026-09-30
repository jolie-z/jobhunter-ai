"""launch_edge 加固单测（2026-09-26 唤起卡死排查配套）。

覆盖三件事：
1. 端口已有监听者 → 复用返回，绝不二次拉起（防 Chromium 单例竞态）；
2. 拉起后 CDP 就绪轮询：就绪返回成功；超时如实抛 RuntimeError 并附日志尾部；
3. 双叉监护进程真实运行：Edge(替身) 的 stdout/stderr 落盘 + [edge exit] code=N 退出标记。
"""
import os
import sys
import time
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.session import browser  # noqa: E402
from app.session.models import PlatformConfig  # noqa: E402


def _mk_cfg(name: str = "liepin", port: int = 9226) -> PlatformConfig:
    return PlatformConfig(
        name=name,
        display_name="猎聘" if name == "liepin" else name,
        browser_type="drissionpage",
        profile_dir=f"/tmp/does-not-matter/{name}",
        port=port,
        login_check_url=f"https://www.{name}.example.com/",
    )


@pytest.fixture
def fast_timeout(monkeypatch):
    """把 CDP 就绪轮询上限压到 1s，用例秒级收场。"""
    monkeypatch.setattr(browser, "_CDP_READY_TIMEOUT_SECS", 1)


@pytest.fixture
def tmp_edge_log(monkeypatch, tmp_path):
    """把 Edge 日志指到 tmp 目录，并回传路径便于断言。"""
    log_file = tmp_path / "edge_liepin.log"
    monkeypatch.setattr(browser, "edge_log_path", lambda name: log_file)
    return log_file


def test_launch_edge_reuses_when_port_open(monkeypatch, tmp_edge_log):
    """端口已有监听者：直接复用返回，绝不二次拉起（防单例竞态双实例并存）。"""
    cfg = _mk_cfg()
    monkeypatch.setattr("app.session.health_checker.probe_port", lambda port, **kw: True)

    def _boom(*args, **kwargs):
        raise AssertionError("端口已占用时严禁二次拉起")

    monkeypatch.setattr(browser, "_launch_edge_daemon", _boom)
    monkeypatch.setattr(browser, "find_edge_path", lambda: "/bin/true")

    res = browser.launch_edge(cfg)
    assert res["status"] == "success"
    assert res.get("reused") is True
    assert str(cfg.port) in res["message"]
    assert not tmp_edge_log.exists(), "复用路径不应产生新的启动日志"


def test_launch_edge_success_after_cdp_ready(monkeypatch, tmp_edge_log, fast_timeout):
    """exec 后 CDP 端口就绪 → 返回成功；启动头已写入日志文件。"""
    cfg = _mk_cfg()
    calls = {"n": 0}

    def _probe(port, **kw):
        calls["n"] += 1
        return calls["n"] >= 2  # 复用检查=False，首轮轮询起=True

    monkeypatch.setattr("app.session.health_checker.probe_port", _probe)
    monkeypatch.setattr(browser, "find_edge_path", lambda: "/bin/true")
    monkeypatch.setattr(browser, "_launch_edge_daemon", lambda cmd, log_path: None)

    res = browser.launch_edge(cfg)
    assert res["status"] == "success"
    assert "reused" not in res
    assert tmp_edge_log.exists()
    assert "[launch" in tmp_edge_log.read_text(encoding="utf-8")


def test_launch_edge_raises_with_log_tail_on_cdp_timeout(monkeypatch, tmp_edge_log, fast_timeout):
    """CDP 30s 未就绪 → 抛 RuntimeError，错误信息带日志路径与尾部（临终遗言可见）。"""
    cfg = _mk_cfg()
    monkeypatch.setattr("app.session.health_checker.probe_port", lambda port, **kw: False)
    monkeypatch.setattr(browser, "find_edge_path", lambda: "/bin/true")

    def _fake_daemon(cmd, log_path):
        with open(log_path, "a", encoding="utf-8") as f:
            f.write("[devtools] FATAL something_bad_happened\n")

    monkeypatch.setattr(browser, "_launch_edge_daemon", _fake_daemon)

    with pytest.raises(RuntimeError) as ei:
        browser.launch_edge(cfg)
    msg = str(ei.value)
    assert "未就绪" in msg
    assert "edge_liepin.log" in msg
    assert "something_bad_happened" in msg
    assert str(browser._CDP_READY_TIMEOUT_SECS) in msg or "1" in msg


@pytest.mark.skipif(not hasattr(os, "fork"), reason="双叉监护路径仅 POSIX")
def test_daemon_supervisor_captures_output_and_exit_marker(tmp_path):
    """真跑双叉监护：替身进程 stdout 落盘、异常退出码写入 [edge exit] 标记。"""
    log_file = tmp_path / "edge_fake.log"
    fake_browser = [sys.executable, "-c", "print('hello-edge-marker'); raise SystemExit(3)"]

    browser._launch_edge_daemon(fake_browser, str(log_file))

    deadline = time.time() + 10
    content = ""
    while time.time() < deadline:
        content = log_file.read_text(encoding="utf-8", errors="replace") if log_file.exists() else ""
        if "[edge exit]" in content:
            break
        time.sleep(0.2)

    assert "hello-edge-marker" in content, "替身进程 stdout 应被接入日志文件"
    assert "[edge exit] code=3" in content, "退出标记必须落盘（临终遗言闭环）"
