"""猎聘会话登录态持久化回归（2026-10-30 真机问题）。

锁定三件事：
1. `check_login_status` 不再只看 URL 前缀：c.liepin.com/login 不能被当成已登录；
2. `save_current_cookies` 只在含 lt_auth/liepin_login_valid 时回写，访客态不覆盖有效文件；
3. 文件注入会清洗字段，注入成功后能通过 cookie 实证并回写。
"""
import importlib.util
import json
import os
import sys
import time
import types
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
LIEPIN_DIR = BACKEND_DIR / "liepin_scraper"


def _load_session(monkeypatch, tmp_path):
    """按文件路径加载 liepin_session，并把 COOKIE_FILE 指向临时目录。"""
    monkeypatch.setenv("JOBHUNTER_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("JOBHUNTER_PROFILE_DIR", str(tmp_path / "profiles"))
    sys.modules.pop("liepin_session", None)

    # 其他用例可能把 DrissionPage 桩成 object（无 set_local_port 等）；本文件用
    # 可配置的假 ChromiumOptions 隔离加载，避免依赖真实浏览器。
    old_dp = sys.modules.get("DrissionPage")
    stub = types.ModuleType("DrissionPage")

    class _FakeOptions:
        def __getattr__(self, name):
            def _noop(*a, **k):
                return self

            return _noop

    stub.ChromiumOptions = _FakeOptions
    stub.ChromiumPage = object
    sys.modules["DrissionPage"] = stub
    try:
        spec = importlib.util.spec_from_file_location("liepin_session_under_test", LIEPIN_DIR / "liepin_session.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules["liepin_session_under_test"] = mod
        spec.loader.exec_module(mod)
    finally:
        if old_dp is not None:
            sys.modules["DrissionPage"] = old_dp
        else:
            sys.modules.pop("DrissionPage", None)
    monkeypatch.setattr(mod, "COOKIE_FILE", str(tmp_path / "liepin_cookies.json"))
    return mod


def _valid_cookies(expires=None):
    exp = expires if expires is not None else time.time() + 86400
    return [
        {"name": "lt_auth", "value": "v1", "domain": ".liepin.com", "path": "/",
         "expires": exp, "httpOnly": True, "secure": True, "sameSite": "None"},
        {"name": "liepin_login_valid", "value": "v2", "domain": ".liepin.com", "path": "/",
         "expires": exp, "httpOnly": False, "secure": True, "sameSite": "none"},
        {"name": "user_name", "value": "u", "domain": ".liepin.com", "path": "/", "expires": -1},
    ]


class _FakeSetter:
    def __init__(self, page):
        self.page = page

    def cookies(self, payload):
        self.page.injected = list(payload)
        self.page._cookies = list(payload)
        self.page.url = "https://c.liepin.com/"


class _FakePage:
    def __init__(self, cookies=None):
        self._cookies = list(cookies or [])
        self.url = "about:blank"
        self.injected = None
        self.set = _FakeSetter(self)

    def cookies(self, all_info=False, all_domains=False):
        return self._cookies

    def get(self, url, **kwargs):
        self.url = url
        return True

    def refresh(self):
        return True


def test_check_login_status_rejects_login_page(monkeypatch, tmp_path):
    sess = _load_session(monkeypatch, tmp_path)
    page = _FakePage()
    page.get = lambda url, **k: setattr(page, "url", "https://c.liepin.com/login?backUrl=x")
    monkeypatch.setattr(sess, "get_browser_page", lambda: page)
    monkeypatch.setattr(sess.time, "sleep", lambda s: None)

    assert sess.check_login_status() is False


def test_check_login_status_accepts_valid_cookies_without_navigation(monkeypatch, tmp_path):
    sess = _load_session(monkeypatch, tmp_path)
    page = _FakePage(_valid_cookies())
    page.get = lambda *a, **k: pytest.fail("已有登录凭证时不得导航")
    monkeypatch.setattr(sess, "get_browser_page", lambda: page)

    assert sess.check_login_status() is True


def test_save_current_cookies_refuses_guest_overwrite(monkeypatch, tmp_path):
    sess = _load_session(monkeypatch, tmp_path)
    target = Path(sess.COOKIE_FILE)
    target.write_text('{"valid": true}', encoding="utf-8")
    page = _FakePage([{"name": "user_name", "value": "guest", "domain": ".liepin.com"}])
    monkeypatch.setattr(sess, "get_browser_page", lambda: page)

    sess.save_current_cookies()

    assert json.loads(target.read_text(encoding="utf-8")) == {"valid": True}


def test_save_current_cookies_normalizes_and_writes_valid_auth(monkeypatch, tmp_path):
    sess = _load_session(monkeypatch, tmp_path)
    page = _FakePage(_valid_cookies())
    monkeypatch.setattr(sess, "get_browser_page", lambda: page)

    sess.save_current_cookies()

    data = json.loads(Path(sess.COOKIE_FILE).read_text(encoding="utf-8"))
    by_name = {c["name"]: c for c in data}
    assert set(by_name) == {"lt_auth", "liepin_login_valid", "user_name"}
    assert by_name["lt_auth"]["sameSite"] == "None"
    assert by_name["liepin_login_valid"]["sameSite"] == "None"
    assert isinstance(by_name["lt_auth"]["expires"], float)
    assert not list(Path(sess.COOKIE_FILE).parent.glob("*.tmp"))


def test_inject_cleans_payload_and_recovers(monkeypatch, tmp_path):
    sess = _load_session(monkeypatch, tmp_path)
    Path(sess.COOKIE_FILE).write_text(json.dumps(_valid_cookies()), encoding="utf-8")
    page = _FakePage()  # 初始无登录 cookie
    monkeypatch.setattr(sess, "get_browser_page", lambda: page)
    monkeypatch.setattr(sess.time, "sleep", lambda s: None)

    sess._inject_cookies_if_needed()

    assert page.injected is not None
    assert {c["name"] for c in page.injected} >= {"lt_auth", "liepin_login_valid"}
    assert all("expiry" not in c for c in page.injected)
    # 注入后 check_login_status 通过，文件被规范化回写
    data = json.loads(Path(sess.COOKIE_FILE).read_text(encoding="utf-8"))
    assert {c["name"] for c in data} >= {"lt_auth", "liepin_login_valid"}
