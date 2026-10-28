"""engine_guard 单测（Q24 引擎环境守卫）+ 5 接入点行为测试。

全 mock（subprocess / 探测原语 / sync_playwright），绝不真开浏览器、绝不触碰生产端口占用者。
判定矩阵与退出码语义见 backend/engine_guard.py docstring（方案 plan-review round3 PASS）。
"""

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_BACKEND_ROOT),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import engine_guard as eg
from engine_guard import EngineGuardError, verify_browser_identity

_FAKE_PROF = "/Users/fakeproj/backend/data/profiles/boss"


def _load_scraper(rel_path: str, alias: str):
    """按文件路径显式加载 scraper 模块。

    resume_editor/platforms/boss_collector.py 与 boss_scraper/boss_collector.py
    同名（Q24 实测：全量跑时前者先占 sys.modules 缓存致 import 错包），
    故统一走文件路径加载，不依赖 sys.path 顺序。
    """
    spec = importlib.util.spec_from_file_location(alias, _BACKEND_ROOT / rel_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[alias] = mod
    spec.loader.exec_module(mod)
    return mod


def _mock_primitives(monkeypatch, http_ok, pids, commands=None):
    """mock 探测原语层：commands 为 {pid: 命令行}，缺省 PID 视为 ps 失败(None)。

    http_ok 传 _probe_http 的三态字符串："refused" / "ok" / "untrusted"。
    """
    monkeypatch.setattr(eg, "_probe_http", lambda port: http_ok)
    monkeypatch.setattr(eg, "_lsof_pids", lambda port: pids)
    monkeypatch.setattr(eg, "_ps_command", lambda pid: (commands or {}).get(pid))


def _primitives_must_not_run(monkeypatch):
    """豁免/绝对路径短路场景：任何探测都不应发生。"""
    monkeypatch.setattr(eg, "_probe_http", lambda port: (_ for _ in ()).throw(AssertionError("探测不应发生")))
    monkeypatch.setattr(eg, "_lsof_pids", lambda port: (_ for _ in ()).throw(AssertionError("lsof 不应发生")))


# ============================================================
# 判定矩阵（五格，编号对齐 engine_guard docstring）
# ============================================================

def test_port_free_allows_launch(monkeypatch):
    """矩阵①：lsof 无监听 + HTTP 立即拒绝(RST) → 放行（端口空闲，由本引擎自起）。"""
    _mock_primitives(monkeypatch, http_ok="refused", pids=[])
    ok, reason = verify_browser_identity(19222, _FAKE_PROF, platform="boss")
    assert ok and reason == "port_free"


def test_lsof_blindspot_rejected(monkeypatch):
    """矩阵②：lsof 无监听但 HTTP 2xx（疑跨用户监听盲区）→ 宁可错杀。"""
    _mock_primitives(monkeypatch, http_ok="ok", pids=[])
    ok, reason = verify_browser_identity(19222, _FAKE_PROF, platform="boss")
    assert not ok
    assert "盲区" in reason


def test_probe_untrusted_rejected(monkeypatch):
    """矩阵③：lsof 无监听但 HTTP 超时/非2xx → 超时是「有监听者未应答」信号，绝不放行（岗哨3 P1）。

    2026-10-08 复探语义：两次探测都 untrusted 维持 fail-closed（_mock_primitives 的
    固定桩天然模拟此场景）；sleep 打桩避免测试真等 1.5s。
    """
    monkeypatch.setattr(eg.time, "sleep", lambda s: None)
    _mock_primitives(monkeypatch, http_ok="untrusted", pids=[])
    ok, reason = verify_browser_identity(19222, _FAKE_PROF, platform="boss")
    assert not ok
    assert "不可信" in reason


def test_untrusted_then_refused_reprobe_allows_launch(monkeypatch):
    """矩阵③复探放行：首探 untrusted、1.5s 后复探 refused（关停竞态吞 RST）→ port_free。

    2026-10-08 15:30 猎聘事故：浏览器确已退出却报「探测不可信」，投递引擎 fail-closed
    拒绝且不自拉。复探给这类偶发误判一条确定性出路——只有复探 refused 才放行。
    """
    seq = iter(["untrusted", "refused"])
    monkeypatch.setattr(eg, "_probe_http", lambda port: next(seq))
    monkeypatch.setattr(eg, "_lsof_pids", lambda port: [])
    monkeypatch.setattr(eg.time, "sleep", lambda s: None)
    ok, reason = verify_browser_identity(9226, _FAKE_PROF, platform="liepin")
    assert ok and reason == "port_free"


def test_untrusted_reprobe_still_untrusted_rejected(monkeypatch):
    """矩阵③复探拒绝：两次 untrusted → 维持 fail-closed（盲区语义不弱化）。"""
    seq = iter(["untrusted", "untrusted"])
    monkeypatch.setattr(eg, "_probe_http", lambda port: next(seq))
    monkeypatch.setattr(eg, "_lsof_pids", lambda port: [])
    monkeypatch.setattr(eg.time, "sleep", lambda s: None)
    ok, reason = verify_browser_identity(9226, _FAKE_PROF, platform="liepin")
    assert not ok
    assert "不可信" in reason


def test_profile_match_allows_attach(monkeypatch):
    """矩阵④：占用者 --user-data-dir 值与预期相等 → 放行。"""
    cmd = f"/usr/bin/edge --flag1 --user-data-dir={_FAKE_PROF} --disable-gpu"
    _mock_primitives(monkeypatch, http_ok="ok", pids=["100"], commands={"100": cmd})
    ok, reason = verify_browser_identity(19222, _FAKE_PROF, platform="boss")
    assert ok and reason == "profile_match"


def test_prefix_collision_rejected(monkeypatch):
    """P1-2 前缀碰撞：预期 …/profiles/boss，占用者 …/profiles/boss_test → 拒绝。"""
    cmd = f"edge --user-data-dir=/Users/fakeproj/backend/data/profiles/boss_test"
    _mock_primitives(monkeypatch, http_ok="ok", pids=["100"], commands={"100": cmd})
    ok, reason = verify_browser_identity(19222, _FAKE_PROF, platform="boss")
    assert not ok


def test_expected_path_in_other_argv_rejected(monkeypatch):
    """P1-2 绑定关系：预期路径出现在其他 argv，但 user-data-dir 指向别处 → 拒绝。"""
    cmd = f"edge --load-extension=/Users/fakeproj/backend/data/profiles/boss/ext --user-data-dir=/elsewhere"
    _mock_primitives(monkeypatch, http_ok="ok", pids=["100"], commands={"100": cmd})
    ok, reason = verify_browser_identity(19222, _FAKE_PROF, platform="boss")
    assert not ok


def test_no_user_data_dir_rejected(monkeypatch):
    """矩阵④：占用者命令行无 --user-data-dir（默认 profile 浏览器）→ 拒绝。"""
    _mock_primitives(monkeypatch, http_ok="ok", pids=["100"], commands={"100": "/Applications/Edge --headless"})
    ok, reason = verify_browser_identity(19222, _FAKE_PROF, platform="boss")
    assert not ok
    assert "无 --user-data-dir" in reason


def test_lsof_failure_fail_closed(monkeypatch):
    """矩阵⑤：lsof 探测异常 → fail-closed。"""
    _mock_primitives(monkeypatch, http_ok="refused", pids=None)
    ok, reason = verify_browser_identity(19222, _FAKE_PROF, platform="boss")
    assert not ok
    assert "fail-closed" in reason


def test_ps_failure_fail_closed(monkeypatch):
    """矩阵⑤：有监听 PID 但 ps 查询失败 → fail-closed。"""
    _mock_primitives(monkeypatch, http_ok="ok", pids=["100"], commands={"100": None})
    ok, reason = verify_browser_identity(19222, _FAKE_PROF, platform="boss")
    assert not ok


def test_multiple_pids_any_match_allows(monkeypatch):
    """多个监听 PID，任一匹配即放行。"""
    cmds = {
        "1": "edge --user-data-dir=/elsewhere",
        "2": f"edge --user-data-dir={_FAKE_PROF}",
    }
    _mock_primitives(monkeypatch, http_ok="ok", pids=["1", "2"], commands=cmds)
    ok, reason = verify_browser_identity(19222, _FAKE_PROF, platform="boss")
    assert ok and reason == "profile_match"


# ============================================================
# 路径归一 / 豁免 / 配置防御
# ============================================================

def test_symlink_realpath_match(monkeypatch, tmp_path):
    """realpath 归一：符号链接与真实路径视为同一目录（测试内自建链接，平台无关）。"""
    real = tmp_path / "real_profile"
    real.mkdir()
    link = tmp_path / "linked_profile"
    link.symlink_to(real)
    cmd = f"edge --user-data-dir={real}"
    _mock_primitives(monkeypatch, http_ok="ok", pids=["100"], commands={"100": cmd})
    ok, _ = verify_browser_identity(19222, str(link), platform="test")
    assert ok


def test_exempt_env_bypasses_all_probes(monkeypatch):
    """显式豁免：放行且不发生任何探测。"""
    _primitives_must_not_run(monkeypatch)
    monkeypatch.setenv(eg.EXEMPT_ENV, "1")
    ok, reason = verify_browser_identity(19222, _FAKE_PROF, platform="boss")
    assert ok and reason == "exempted_by_env"


def test_relative_profile_rejected(monkeypatch):
    """expected_profile 非绝对路径 = 配置错误，直接拒绝（realpath cwd 语义不可靠）。"""
    _primitives_must_not_run(monkeypatch)
    ok, reason = verify_browser_identity(19222, "data/profiles/boss", platform="boss")
    assert not ok
    assert "非绝对路径" in reason


# ============================================================
# 探测原语层（lsof/ps 退出码语义、HTTP 探测）
# ============================================================

def _run_proc(returncode=0, stdout=""):
    proc = subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")
    return proc


def test_lsof_exit_semantics(monkeypatch):
    """lsof 退出码：0=有匹配；1+空输出=正常查无匹配；≥2/缺失=异常。"""
    cases = [
        (0, "123\n456\n", ["123", "456"]),
        (1, "", []),
        (2, "", None),
    ]
    for rc, out, expected in cases:
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: _run_proc(rc, out))
        assert eg._lsof_pids(19222) == expected, f"rc={rc}"
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError()))
    assert eg._lsof_pids(19222) is None


def test_ps_exit_semantics(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _run_proc(0, "  edge --x  \n"))
    assert eg._ps_command("1") == "edge --x"
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _run_proc(1, ""))
    assert eg._ps_command("1") is None
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError()))
    assert eg._ps_command("1") is None


def test_win_netstat_pids(monkeypatch):
    """2026-10-06 Windows 适配：netstat LISTENING 行解析；仅匹配指定端口与 LISTENING 态。"""
    netstat_out = (
        "  TCP    127.0.0.1:9227     0.0.0.0:0      LISTENING    4321\n"
        "  TCP    [::]:9227          [::]:0         LISTENING    4321\n"
        "  TCP    127.0.0.1:19222    0.0.0.0:0      LISTENING    8765\n"
        "  TCP    127.0.0.1:9227     1.2.3.4:5555   ESTABLISHED  9999\n"
        "  TCP    127.0.0.1:139      0.0.0.0:0      LISTENING    1111\n"
    )
    monkeypatch.setattr(eg.sys, "platform", "win32")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _run_proc(0, netstat_out))
    assert eg._lsof_pids(9227) == ["4321"]  # IPv4+IPv6 去重；ESTABLISHED 不算监听
    assert eg._lsof_pids(19222) == ["8765"]
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _run_proc(0, ""))
    assert eg._lsof_pids(9227) == []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _run_proc(1, ""))
    assert eg._lsof_pids(9227) is None  # 非 0 退出码且无结果 = 探测异常 fail-closed
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _run_proc(1, netstat_out))
    assert eg._lsof_pids(9227) is None  # R1 P2：非 0 退出码即便解析出结果也不信任（fail-closed）


def test_win_commandline_and_quoted_profile(monkeypatch):
    """Windows：PowerShell CIM 查命令行；--user-data-dir 引号包裹路径需完整提取（否则假拒绝）。"""
    monkeypatch.setattr(eg.sys, "platform", "win32")
    quoted = 'msedge.exe --user-data-dir="C:\\Users\\Jo hn\\AppData\\Roaming\\jobhunter-desktop\\profiles\\51job" --flag'
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _run_proc(0, quoted))
    assert eg._ps_command("123") == quoted
    extracted = eg._extract_user_data_dir(quoted)
    assert extracted == "C:\\Users\\Jo hn\\AppData\\Roaming\\jobhunter-desktop\\profiles\\51job"

    unquoted = 'msedge.exe --user-data-dir=C:\\Users\\Administrator\\AppData\\Roaming\\jobhunter-desktop\\profiles\\51job --flag'
    assert eg._extract_user_data_dir(unquoted) == "C:\\Users\\Administrator\\AppData\\Roaming\\jobhunter-desktop\\profiles\\51job"
    assert eg._extract_user_data_dir("msedge.exe --other=1") is None

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _run_proc(1, ""))
    assert eg._ps_command("123") is None  # 查询失败 fail-closed
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _run_proc(0, ""))
    assert eg._ps_command("123") is None  # 进程已死（空输出）fail-closed


def test_probe_http_three_states(monkeypatch):
    """HTTP 探测三态：2xx=ok；立即拒绝=refused；超时/非2xx/其他异常=untrusted，不坍缩。"""

    class _Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class _Resp404(_Resp):
        status = 404

    def _opener_with(result_or_exc):
        opener = MagicMock()
        if isinstance(result_or_exc, BaseException):
            opener.open.side_effect = result_or_exc
        else:
            opener.open.return_value = result_or_exc
        return opener

    import urllib.error as _ue

    cases = [
        (_Resp(), "ok"),
        (_Resp404(), "untrusted"),
        (_ue.URLError(ConnectionRefusedError(61, "Connection refused")), "refused"),
        (ConnectionRefusedError(61, "Connection refused"), "refused"),
        (_ue.HTTPError("http://x", 503, "unavail", None, None), "untrusted"),
        (TimeoutError("busy"), "untrusted"),
        (_ue.URLError(TimeoutError("t")), "untrusted"),
    ]
    for side_effect_or_resp, expected in cases:
        monkeypatch.setattr(
            eg.urllib.request, "build_opener", lambda *a, s=side_effect_or_resp: _opener_with(s)
        )
        got = eg._probe_http(19222)
        assert got == expected, f"{side_effect_or_resp!r} → {got}，预期 {expected}"


# ============================================================
# 接入点行为（5 处）：守卫拒绝 → 不发生任何浏览器连接
# ============================================================

def _patch_engine_verify(monkeypatch, module, result):
    monkeypatch.setattr(module, "verify_browser_identity", lambda *a, **k: result)


def test_boss_delivery_reject(monkeypatch):
    bad = _load_scraper("boss_scraper/boss_auto_delivery.py", "q24_boss_auto_delivery")

    monkeypatch.setattr(bad, "_page", None)
    _patch_engine_verify(monkeypatch, bad, (False, "占用者陌生"))

    def _boom(*a, **k):
        raise AssertionError("ChromiumPage 不应被构造")

    monkeypatch.setattr(bad, "ChromiumPage", _boom)
    with pytest.raises(EngineGuardError):
        bad.get_browser_page()


def test_boss_collector_reject(monkeypatch, capsys):
    bc = _load_scraper("boss_scraper/boss_collector.py", "q24_boss_collector")

    monkeypatch.setattr(bc, "_page", None)
    _patch_engine_verify(monkeypatch, bc, (False, "占用者陌生"))

    def _boom(*a, **k):
        raise AssertionError("ChromiumPage 不应被构造")

    monkeypatch.setattr(bc, "ChromiumPage", _boom)

    import requests as _requests

    put_calls: list = []
    monkeypatch.setattr(_requests, "put", lambda *a, **k: put_calls.append(a))
    monkeypatch.setattr(
        _requests, "get",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("/json 探测不应在守卫拒绝后发出")),
    )

    with pytest.raises(SystemExit):
        bc.get_browser_page()
    assert put_calls == []
    assert "环境守卫" in capsys.readouterr().out


def test_liepin_reject(monkeypatch):
    ls = _load_scraper("liepin_scraper/liepin_session.py", "q24_liepin_session")

    monkeypatch.setattr(ls, "page", None)
    _patch_engine_verify(monkeypatch, ls, (False, "占用者陌生"))

    def _boom(*a, **k):
        raise AssertionError("ChromiumPage 不应被构造")

    monkeypatch.setattr(ls, "ChromiumPage", _boom)
    with pytest.raises(EngineGuardError):
        ls.get_browser_page()


def test_51job_delivery_reject(monkeypatch):
    """守卫拒绝语义回归：Q24 身份守卫拒绝（占用者陌生）时 _connect_browser 直接抛错。

    9/26 f4885c11 投递回退旧栈后，_connect_browser(p) 恢复 CDP-first 签名（p 为
    patchright/playwright 实例，仅在守卫放行后才使用），引擎锁拒绝由 engine.launch_or_fail
    在守卫放行后的连接兜底路径触发。本用例锁定第一道闸门：身份守卫 fail-closed。
    """
    j51 = _load_scraper("51job_scraper/51job_auto_delivery.py", "q24_51job_auto_delivery")

    _patch_engine_verify(monkeypatch, j51, (False, "占用者陌生"))

    # 守卫拒绝发生在 p 使用之前，传 None 即可；精确匹配桩原因，防其他 RuntimeError 假阳性
    with pytest.raises(EngineGuardError, match="占用者陌生"):
        j51._connect_browser(None)


def test_51job_collector_reject(monkeypatch):
    """2026-10-07 熔断语义升级：守卫拒绝时 collector sys.exit(1)（此前裸 return 以退出码 0
    结束，调度器感知不到环境故障，继续派页白烧翻页休眠——Windows 真机连烧 4 轮实证）。"""
    j51c = _load_scraper("51job_scraper/51job_collector.py", "q24_51job_collector")

    _patch_engine_verify(monkeypatch, j51c, (False, "占用者陌生"))

    pw = MagicMock()
    monkeypatch.setattr(j51c, "sync_playwright", lambda: pw)
    with pytest.raises(SystemExit) as exc_info:
        j51c.start_collector(1, keyword="python")
    assert exc_info.value.code == 1  # 非 0 退出码供调度器熔断
    pw.__enter__.assert_not_called()  # 守卫在 with 之外：拒绝时连 playwright driver 都不拉起
