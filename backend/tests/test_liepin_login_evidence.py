"""猎聘登录实证双模判据测试（2026-09-27 双判据批）。

背景：管线猎聘入口原为 Cookie 文件硬门，用户在会话条（Edge 9226 专用 profile）
登录后无法被识别，预检 300 秒超时跳过猎聘（0927 新机事故）。双判据修复后：
文件存在 OR profile 登录实证有效即放行。实证判据=lt_auth + liepin_login_valid
两键齐且未过期；取数双模——端口 UP 用 CDP 直读内存 cookie（零导航），
端口 DOWN 拷贝 profile Cookies 库（连同 -wal/-shm，规避漏读 WAL 的假阴性）；
任一环节失败 fail-closed 判 False。
"""
import asyncio
import os
import sqlite3
import time

from app.session import health_checker as hc

# Chrome epoch（1601-01-01）与 unix epoch 的秒差
_CHROME_EPOCH_OFFSET_S = 11644473600.0


def _chrome_epoch_utc(unix_s: float) -> int:
    return int((unix_s + _CHROME_EPOCH_OFFSET_S) * 1_000_000)


# ==========================================
# 判据函数
# ==========================================

def test_judge_requires_both_keys():
    now = time.time()
    assert hc._judge_login_keys({"lt_auth": now + 3600, "liepin_login_valid": now + 3600}) is True
    assert hc._judge_login_keys({"lt_auth": now + 3600}) is False
    assert hc._judge_login_keys({}) is False


def test_judge_rejects_expired_and_accepts_session():
    now = time.time()
    # 过期键 ≠ 登录态
    assert hc._judge_login_keys({"lt_auth": now - 10, "liepin_login_valid": now + 3600}) is False
    # 会话 cookie（expires<=0）落账即有效
    assert hc._judge_login_keys({"lt_auth": 0.0, "liepin_login_valid": 0.0}) is True


# ==========================================
# 双模取数分派
# ==========================================

def test_dispatch_port_up_uses_cdp(monkeypatch):
    calls = {}

    def fake_probe(port, timeout=2.0):
        calls["probed"] = port
        return True

    def fake_cdp(port):
        calls["cdp"] = port
        return {"lt_auth": time.time() + 3600, "liepin_login_valid": time.time() + 3600}

    def _fail_db(profile_dir):
        raise AssertionError("端口 UP 时不得走离线拷贝路径")

    monkeypatch.setattr(hc, "probe_port", fake_probe)
    monkeypatch.setattr(hc, "_read_login_keys_via_cdp", fake_cdp)
    monkeypatch.setattr(hc, "_read_login_keys_via_profile_db", _fail_db)

    assert hc.check_liepin_login_evidence(port=9226, profile_dir="/x") is True
    assert calls["probed"] == 9226
    assert calls["cdp"] == 9226


def test_dispatch_port_down_uses_profile_db(monkeypatch, tmp_path):
    def _fail_cdp(port):
        raise AssertionError("端口 DOWN 时不得走 CDP 路径")

    monkeypatch.setattr(hc, "probe_port", lambda port, timeout=2.0: False)
    monkeypatch.setattr(hc, "_read_login_keys_via_cdp", _fail_cdp)
    monkeypatch.setattr(
        hc, "_read_login_keys_via_profile_db", lambda p: {"lt_auth": 0.0, "liepin_login_valid": 0.0}
    )

    assert hc.check_liepin_login_evidence(port=9226, profile_dir=str(tmp_path)) is True


def test_fail_closed_when_cdp_unreadable(monkeypatch):
    monkeypatch.setattr(hc, "probe_port", lambda port, timeout=2.0: True)
    monkeypatch.setattr(hc, "_read_login_keys_via_cdp", lambda port: None)
    assert hc.check_liepin_login_evidence(port=9226, profile_dir="/x") is False


# ==========================================
# DOWN 模：profile Cookies 库拷贝读取
# ==========================================

def _make_profile_db(profile_dir, rows, with_wal=False):
    default_dir = os.path.join(str(profile_dir), "Default")
    os.makedirs(default_dir, exist_ok=True)
    db = os.path.join(default_dir, "Cookies")
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE cookies (name TEXT, expires_utc INTEGER)")
    conn.executemany("INSERT INTO cookies VALUES (?, ?)", rows)
    conn.commit()
    conn.close()
    if with_wal:
        with open(db + "-wal", "wb") as f:
            f.write(b"wal-companion-bytes")
    return db


def test_profile_db_copy_reads_keys(monkeypatch, tmp_path):
    future = _chrome_epoch_utc(time.time() + 86400 * 30)
    _make_profile_db(
        tmp_path,
        [("lt_auth", future), ("liepin_login_valid", future), ("unrelated", 1)],
        with_wal=True,
    )

    found = hc._read_login_keys_via_profile_db(str(tmp_path))

    assert found is not None
    assert set(found) == {"lt_auth", "liepin_login_valid"}
    assert hc._judge_login_keys(found) is True


def test_profile_db_missing_db_returns_none(tmp_path):
    assert hc._read_login_keys_via_profile_db(str(tmp_path)) is None


def test_profile_db_garbage_returns_none(tmp_path):
    default_dir = os.path.join(str(tmp_path), "Default")
    os.makedirs(default_dir, exist_ok=True)
    with open(os.path.join(default_dir, "Cookies"), "wb") as f:
        f.write(b"not a sqlite db")

    assert hc._read_login_keys_via_profile_db(str(tmp_path)) is None


# ==========================================
# 采集入口双判据（liepin_collect_ready）
# ==========================================

def test_collect_ready_file_short_circuits(monkeypatch, tmp_path):
    cookie_file = os.path.join(str(tmp_path), "liepin_cookies.json")
    with open(cookie_file, "w", encoding="utf-8") as f:
        f.write("[]")

    def _boom(*a, **k):
        raise AssertionError("文件存在时不得触发实证探测")

    monkeypatch.setattr(hc, "check_liepin_login_evidence", _boom)
    assert hc.liepin_collect_ready(cookie_file) is True


def test_collect_ready_falls_back_to_evidence(monkeypatch, tmp_path):
    monkeypatch.setattr(hc, "check_liepin_login_evidence", lambda *a, **k: True)
    missing = os.path.join(str(tmp_path), "missing.json")
    assert hc.liepin_collect_ready(missing) is True

    monkeypatch.setattr(hc, "check_liepin_login_evidence", lambda *a, **k: False)
    assert hc.liepin_collect_ready(missing) is False
