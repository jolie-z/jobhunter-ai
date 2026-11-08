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
import types

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


def test_has_valid_auth_cookies_from_browser_list():
    now = time.time()
    both = [
        {"name": "lt_auth", "value": "v1", "expires": now + 3600},
        {"name": "liepin_login_valid", "value": "v2", "expires": now + 3600},
    ]
    assert hc.has_valid_liepin_auth_cookies(both) is True
    assert hc.has_valid_liepin_auth_cookies(both[:1]) is False  # 缺键
    assert hc.has_valid_liepin_auth_cookies([
        {"name": "lt_auth", "expires": now - 10},
        {"name": "liepin_login_valid", "expires": now + 3600},
    ]) is False  # 过期
    assert hc.has_valid_liepin_auth_cookies([
        {"name": "lt_auth", "expires": -1},
        {"name": "liepin_login_valid", "expires": 0},
    ]) is True  # 会话 cookie
    assert hc.has_valid_liepin_auth_cookies([
        {"name": "lt_auth", "expires": "not-a-time"},
        {"name": "liepin_login_valid", "expires": now + 3600},
    ]) is False  # 无法解析按失效处理
    assert hc.has_valid_liepin_auth_cookies([None, "x", {"name": ""}]) is False


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


def test_port_up_cdp_unreadable_falls_back_to_profile_db(monkeypatch):
    """2026-10-30：DrissionPage 拉起的 Edge 与 Playwright context 不兼容时，
    端口 UP 但 CDP 读不到 cookie，必须回退离线 profile 库，不能误判未登录。"""
    now = time.time()
    monkeypatch.setattr(hc, "probe_port", lambda port, timeout=2.0: True)
    monkeypatch.setattr(hc, "_read_login_keys_via_cdp", lambda port: None)
    monkeypatch.setattr(
        hc, "_read_login_keys_via_profile_db",
        lambda profile_dir: {"lt_auth": now + 3600, "liepin_login_valid": now + 3600},
    )
    assert hc.check_liepin_login_evidence(port=9226, profile_dir="/x") is True


def test_read_login_keys_via_cdp_uses_browser_session(monkeypatch):
    """CDP 取数走 browser 级 Storage.getCookies，不遍历 contexts（避免 setDownloadBehavior 报错）。"""
    now = time.time()
    calls = {}

    class _Session:
        def send(self, method):
            calls["method"] = method
            return {"cookies": [
                {"name": "lt_auth", "expires": now + 3600},
                {"name": "liepin_login_valid", "expires": now + 3600},
                {"name": "unrelated", "expires": now + 3600},
            ]}

        def detach(self):
            calls["detached"] = True

    class _Browser:
        def new_browser_cdp_session(self):
            return _Session()

        @property
        def contexts(self):
            raise AssertionError("不得遍历 browser.contexts")

        def close(self):
            calls["closed"] = True

    class _Chromium:
        def connect_over_cdp(self, *a, **k):
            calls["connected"] = True
            return _Browser()

    class _Playwright:
        chromium = _Chromium()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    import playwright.sync_api as ps
    monkeypatch.setattr(ps, "sync_playwright", lambda: _Playwright())

    found = hc._read_login_keys_via_cdp(9226)

    assert set(found) == {"lt_auth", "liepin_login_valid"}
    assert calls["method"] == "Storage.getCookies"
    assert calls["detached"] is True and calls["closed"] is True


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
    """文件有效（存在且凭证未过期）→ 直接放行，不触发实证探测。

    2026-10-31 事故根治：短路条件从「存在」升级为「有效」——空壳/过期文件
    曾让本门放行、引擎访客态跑完全程静默 0 条。
    """
    cookie_file = os.path.join(str(tmp_path), "liepin_cookies.json")
    future = time.time() + 7 * 24 * 3600
    with open(cookie_file, "w", encoding="utf-8") as f:
        import json
        json.dump([
            {"name": "lt_auth", "value": "valid", "expires": future},
            {"name": "liepin_login_valid", "value": "1", "expires": future},
        ], f)

    def _boom(*a, **k):
        raise AssertionError("文件有效时不得触发实证探测")

    monkeypatch.setattr(hc, "check_liepin_login_evidence", _boom)
    assert hc.liepin_collect_ready(cookie_file) is True


def test_collect_ready_rejects_stale_file(monkeypatch, tmp_path):
    """文件存在但凭证过期/内容损坏 → 不再短路放行，转实证复检判据。

    2026-10-31 晚间事故回归：DrissionPage Edge 上 CDP 读 cookie 会闪断
    （预检通过、采集门 6 秒后翻转拦截），复检带界重试 3 次，全失败才判死。
    """
    import json

    stale_file = os.path.join(str(tmp_path), "stale.json")
    past = time.time() - 100
    with open(stale_file, "w", encoding="utf-8") as f:
        json.dump([
            {"name": "lt_auth", "value": "expired", "expires": past},
            {"name": "liepin_login_valid", "value": "1", "expires": past},
        ], f)

    corrupt_file = os.path.join(str(tmp_path), "corrupt.json")
    with open(corrupt_file, "w", encoding="utf-8") as f:
        f.write("{not-json")

    monkeypatch.setattr(hc, "_LIEPIN_EVIDENCE_RETRY_INTERVAL_S", 0)
    evidence_calls = {"n": 0}

    def _flaky_false(*a, **k):
        evidence_calls["n"] += 1
        return False

    monkeypatch.setattr(hc, "check_liepin_login_evidence", _flaky_false)
    assert hc.liepin_collect_ready(stale_file) is False
    assert evidence_calls["n"] == hc._LIEPIN_EVIDENCE_ATTEMPTS  # 重试预算烧完才 fail-closed

    # 任一次复检成功即放行（模拟闪断恢复：第 2 次成功）
    evidence_calls["n"] = 0

    def _flip_flop(*a, **k):
        evidence_calls["n"] += 1
        return evidence_calls["n"] >= 2

    monkeypatch.setattr(hc, "check_liepin_login_evidence", _flip_flop)
    assert hc.liepin_collect_ready(stale_file) is True

    # 实证有效时仍可放行（profile 带活登录态，引擎启动后自愈回写新文件）
    monkeypatch.setattr(hc, "check_liepin_login_evidence", lambda *a, **k: True)
    assert hc.liepin_collect_ready(stale_file) is True


def test_cookie_file_validity_unit(tmp_path):
    """is_liepin_cookie_file_valid：有效/过期/损坏/缺失四态。"""
    import json

    future = time.time() + 3600
    valid_file = os.path.join(str(tmp_path), "valid.json")
    with open(valid_file, "w", encoding="utf-8") as f:
        json.dump([
            {"name": "lt_auth", "value": "v", "expires": future},
            {"name": "liepin_login_valid", "value": "1", "expires": future},
        ], f)
    assert hc.is_liepin_cookie_file_valid(valid_file) is True

    expired_file = os.path.join(str(tmp_path), "expired.json")
    with open(expired_file, "w", encoding="utf-8") as f:
        json.dump([
            {"name": "lt_auth", "value": "v", "expires": time.time() - 10},
            {"name": "liepin_login_valid", "value": "1", "expires": time.time() + 3600},
        ], f)
    assert hc.is_liepin_cookie_file_valid(expired_file) is False

    corrupt_file = os.path.join(str(tmp_path), "corrupt.json")
    with open(corrupt_file, "w", encoding="utf-8") as f:
        f.write("not json at all")
    assert hc.is_liepin_cookie_file_valid(corrupt_file) is False

    assert hc.is_liepin_cookie_file_valid(os.path.join(str(tmp_path), "missing.json")) is False
    assert hc.is_liepin_cookie_file_valid("") is False


def test_collect_ready_falls_back_to_evidence(monkeypatch, tmp_path):
    monkeypatch.setattr(hc, "check_liepin_login_evidence", lambda *a, **k: True)
    missing = os.path.join(str(tmp_path), "missing.json")
    assert hc.liepin_collect_ready(missing) is True

    monkeypatch.setattr(hc, "check_liepin_login_evidence", lambda *a, **k: False)
    assert hc.liepin_collect_ready(missing) is False
