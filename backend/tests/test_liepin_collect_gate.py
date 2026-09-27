"""猎聘采集门双判据 + Cookie 自愈回写测试（2026-09-27 双判据批）。

覆盖两段引擎侧改动：
1. nl_controller.process_liepin_scraping_request 的采集门——原「Cookie 文件硬门」
   改为 liepin_collect_ready 双判据（文件 OR Edge profile 登录实证）；
2. liepin_crawler 的自愈回写——profile 登录确认后把浏览器 cookie 以 playwright
   兼容格式原子回写 COOKIE_FILE（expiry→expires 映射、sameSite 归一、bool 化）。
"""
import asyncio
import importlib.util
import json
import os
import sys
import types
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
LIEPIN_DIR = BACKEND_DIR / "liepin_scraper"


def _load_crawler_module():
    """liepin_crawler 模块级 import DrissionPage，测试环境用桩模块替代。"""
    if "DrissionPage" not in sys.modules:
        stub = types.ModuleType("DrissionPage")
        stub.ChromiumPage = object
        stub.ChromiumOptions = object
        sys.modules["DrissionPage"] = stub
    spec = importlib.util.spec_from_file_location("liepin_crawler_under_test", LIEPIN_DIR / "liepin_crawler.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["liepin_crawler_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


def _load_nl_controller():
    if str(LIEPIN_DIR) not in sys.path:
        sys.path.insert(0, str(LIEPIN_DIR))
    import liepin_nl_controller as nlc
    return nlc


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _FakePage:
    def __init__(self, raw):
        self._raw = raw

    def cookies(self, all_info=False):
        return self._raw


# ==========================================
# cookie 字段映射（DrissionPage → playwright 兼容格式）
# ==========================================

crawler = _load_crawler_module()


def test_dump_maps_fields_and_normalizes():
    raw = [
        {"name": "lt_auth", "value": "v1", "domain": ".liepin.com", "path": "/",
         "expires": 1790000000.5, "httpOnly": 1, "secure": 1, "sameSite": "Lax"},
        {"name": "sid", "value": "v2", "domain": ".liepin.com", "path": "/",
         "expires": None, "httpOnly": 0, "secure": 0, "sameSite": "no_restriction"},
        {"name": "expiry_keyed", "value": "v3", "domain": ".liepin.com", "path": "/",
         "expiry": 1790000000, "httpOnly": 1, "secure": 0, "sameSite": "Strict"},
        {"name": "", "value": "skip-empty-name"},
        "not-a-dict",
    ]
    out = crawler._dump_cookies_drissionpage_to_playwright(_FakePage(raw))

    assert len(out) == 3
    assert out[0]["httpOnly"] is True and out[0]["secure"] is True
    assert out[0]["expires"] == 1790000000.5 and out[0]["sameSite"] == "Lax"
    # expires None → -1；sameSite 不在 {Lax, Strict, None} 内归一为 Lax
    assert out[1]["expires"] == -1
    assert out[1]["httpOnly"] is False and out[1]["sameSite"] == "Lax"
    # DrissionPage 部分版本以 expiry 为过期键名：双键兼容，防过期时间静默丢失退化为 -1
    assert out[2]["expires"] == 1790000000 and out[2]["sameSite"] == "Strict"


def test_self_heal_writes_atomically(monkeypatch, tmp_path):
    target = tmp_path / "liepin_cookies.json"
    monkeypatch.setattr(crawler, "COOKIE_FILE", str(target))
    raw = [{"name": "lt_auth", "value": "v", "domain": ".liepin.com", "path": "/",
            "expires": 1790000000, "httpOnly": 1, "secure": 1, "sameSite": "Lax"}]

    crawler._self_heal_cookie_file(_FakePage(raw))

    assert target.exists()
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data[0]["name"] == "lt_auth"
    assert not list(tmp_path.glob("*.tmp"))  # 原子替换后不留临时文件


def test_self_heal_skips_empty_and_swallows_errors(monkeypatch, tmp_path):
    target = tmp_path / "liepin_cookies.json"
    monkeypatch.setattr(crawler, "COOKIE_FILE", str(target))

    # 空 cookie：不落盘
    crawler._self_heal_cookie_file(_FakePage([]))
    assert not target.exists()

    # page.cookies 抛异常：不冒泡、不落盘
    class _BoomPage:
        def cookies(self, all_info=False):
            raise RuntimeError("browser gone")

    crawler._self_heal_cookie_file(_BoomPage())
    assert not target.exists()


# ==========================================
# 采集门（nl_controller 入口双判据接线）
# ==========================================

nlc = _load_nl_controller()


def test_gate_blocks_when_no_file_and_no_evidence(monkeypatch):
    monkeypatch.setattr(nlc, "liepin_collect_ready", lambda path: False)
    notified = []

    async def fake_notify(chat_id, message):
        notified.append(message)

    engine_calls = []

    def fake_engine(*a, **k):
        engine_calls.append(a)
        return 0

    monkeypatch.setattr(nlc, "_notify_feishu_liepin", fake_notify)
    monkeypatch.setattr(nlc, "run_scraping_task", fake_engine)

    _run(nlc.process_liepin_scraping_request(
        chat_id="agent_cli", city="上海", keyword="生物信息", salary="20-30K",
        start_page=1, target_jobs=10,
    ))

    assert not engine_calls  # 双判据皆否：引擎不得被调用
    assert any("唤起浏览器" in m for m in notified)
    assert any("liepin_cookie_harvester" in m for m in notified)


def test_gate_allows_on_evidence_and_reaches_engine(monkeypatch):
    monkeypatch.setattr(nlc, "liepin_collect_ready", lambda path: True)
    notified = []

    async def fake_notify(chat_id, message):
        notified.append(message)

    engine_calls = []

    def fake_engine(*a, **k):
        engine_calls.append(a)
        return 0

    monkeypatch.setattr(nlc, "_notify_feishu_liepin", fake_notify)
    monkeypatch.setattr(nlc, "run_scraping_task", fake_engine)

    _run(nlc.process_liepin_scraping_request(
        chat_id="agent_cli", city="上海", keyword="生物信息", salary="20-30K",
        start_page=1, target_jobs=10,
    ))

    assert len(engine_calls) == 1  # 实证有效：放行并触达引擎
    assert not any("缺少猎聘 Cookie" in m for m in notified)
