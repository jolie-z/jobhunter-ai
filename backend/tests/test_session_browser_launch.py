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


@pytest.fixture(autouse=True)
def _allow_launch_semantics(monkeypatch):
    """解禁 launch_edge 测试熔断（2026-11-06）：本文件的用例全部 mock 了
    _launch_edge_daemon（或 probe_port 先行短路复用/失败路径），唯一真跑守护进程的
    用例（test_daemon_supervisor_*）执行的是 /bin/true 替身而非 Edge——不产生真实
    浏览器进程。定点 monkeypatch _testing_fuse_active 解禁（agy round1 P2）：
    不污染全局 RUN_LIVE_E2E 开关（它同时控制 live E2E 收集白名单 / conftest 库阀门 /
    熔断三处语义），避免开关混用。熔断本身是「意外漏 mock」用例的兜底，熔断回归
    用例（test_launch_edge_fused_*）在用例内恢复默认判定。"""
    monkeypatch.setattr(browser, "_testing_fuse_active", lambda: False)
    yield


@pytest.fixture
def tmp_edge_log(monkeypatch, tmp_path):
    """把 Edge 日志指到 tmp 目录，并回传路径便于断言。"""
    log_file = tmp_path / "edge_liepin.log"
    monkeypatch.setattr(browser, "edge_log_path", lambda name: log_file)
    return log_file


def test_launch_edge_reuses_when_port_open(monkeypatch, tmp_edge_log):
    """端口已有监听者：身份校验通过后直接复用返回，绝不二次拉起（防单例竞态双实例并存）。"""
    cfg = _mk_cfg()
    monkeypatch.setattr("app.session.health_checker.probe_port", lambda port, **kw: True)
    monkeypatch.setattr(
        "engine_guard.verify_browser_identity",
        lambda *a, **k: (True, "profile_match"),
    )

    def _boom(*args, **kwargs):
        raise AssertionError("端口已占用时严禁二次拉起")

    monkeypatch.setattr(browser, "_launch_edge_daemon", _boom)
    monkeypatch.setattr(browser, "find_edge_path", lambda: "/bin/true")

    res = browser.launch_edge(cfg)
    assert res["status"] == "success"
    assert res.get("reused") is True
    assert str(cfg.port) in res["message"]
    assert not tmp_edge_log.exists(), "复用路径不应产生新的启动日志"


def test_launch_edge_reuse_refuses_foreign_occupant(monkeypatch, tmp_edge_log):
    """复用路径身份校验失败：陌生占用者必须拒绝复用，且不得二次拉起。"""
    cfg = _mk_cfg()
    monkeypatch.setattr("app.session.health_checker.probe_port", lambda port, **kw: True)
    monkeypatch.setattr(
        "engine_guard.verify_browser_identity",
        lambda *a, **k: (False, "端口占用者非预期 profile"),
    )

    def _boom(*args, **kwargs):
        raise AssertionError("陌生占用者不得二次拉起")

    monkeypatch.setattr(browser, "_launch_edge_daemon", _boom)

    with pytest.raises(RuntimeError, match="拒绝复用"):
        browser.launch_edge(cfg)


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


# ---------------- 2026-11-06 测试熔断（智联 Edge 自动拉起事故根治） ----------------

def test_launch_edge_fused_in_testing_env(monkeypatch, tmp_edge_log):
    """测试进程内拉起/复用路径都必须被熔断拒绝（2026-11-06 事故兜底护栏）。

    事故链：batch1 发射用例的后台任务逃逸 → 真 _execute_pipeline → 预检探活
    → launch_edge 双重 fork 拉起智联 Edge（孤儿链常驻，pytest 退出后浏览器仍在）。
    熔断位置在复用检查之前（agy round1 P1 定稿）：宿主机恰好开着真实浏览器时，
    逃逸链路不得静默走复用接管真机浏览器。默认判定与飞书外发 testing_guard 同款，
    RUN_LIVE_E2E=1 显式解禁（真机 E2E 场景）。

    恢复真实熔断判定只 setattr _testing_fuse_active 自身（round2 P1）：不用
    monkeypatch.undo()——它会连坐撤掉 tmp_edge_log 等前置 fixture 的补丁，
    让「未写日志」断言沦为假阳性。
    """
    monkeypatch.setattr(browser, "_testing_fuse_active", browser._REAL_FUSE_ACTIVE)
    monkeypatch.setenv("JOBHUNTER_TESTING", "1")
    monkeypatch.setattr("app.session.health_checker.probe_port", lambda port, **kw: True)
    monkeypatch.setattr("engine_guard.verify_browser_identity", lambda *a, **k: (True, "profile_match"))
    cfg = _mk_cfg()

    with pytest.raises(RuntimeError, match="测试熔断"):
        browser.launch_edge(cfg)
    assert not tmp_edge_log.exists(), "熔断必须发生在写启动日志与 fork 之前"


def test_launch_edge_fuse_release_honors_run_live_e2e(monkeypatch, tmp_edge_log, fast_timeout):
    """RUN_LIVE_E2E=1 显式解禁后默认熔断判定放行，真机 E2E 场景可用。

    同上：恢复真实判定只动 _testing_fuse_active 自身（round2 P1），保证放行后
    launch_edge 的启动日志仍落在 tmp_edge_log（tmp_path），不污染宿主机真实日志。
    """
    monkeypatch.setattr(browser, "_testing_fuse_active", browser._REAL_FUSE_ACTIVE)
    monkeypatch.setenv("JOBHUNTER_TESTING", "1")
    monkeypatch.setenv("RUN_LIVE_E2E", "1")
    calls = {"n": 0}

    def _probe(port, **kw):
        calls["n"] += 1
        return calls["n"] >= 2

    monkeypatch.setattr("app.session.health_checker.probe_port", _probe)
    monkeypatch.setattr(browser, "find_edge_path", lambda: "/bin/true")
    monkeypatch.setattr(browser, "_launch_edge_daemon", lambda cmd, log_path: None)

    res = browser.launch_edge(_mk_cfg())
    assert res["status"] == "success"
    assert "reused" not in res
    assert tmp_edge_log.exists(), "放行路径的启动日志必须落在本用例 tmp 目录（不污染真实日志）"
