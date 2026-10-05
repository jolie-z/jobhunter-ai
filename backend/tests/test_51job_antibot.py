# -*- coding: utf-8 -*-
"""51job 反爬改造（2026-09-24，plan-review R2 PASS）单元测试。

覆盖四块：
1. engine_lock 单一持有者模型：抢锁/拒绝/stale 接管/心跳/释放/登录标记；
2. risk_guard L0-L3 全分级判定表 + 降级边界（仅 L1 可降级 DOM，L2/L3 严禁）；
3. progress_tracker 词级检查点：DDL/复合键规范/24h 跳过/幂等 upsert；
4. api_client：totalCount 末页收窄、HTTP 分级（5xx=L1、403=L3）、JSON 异常=L1。

注意：测试环境无浏览器，全部为纯逻辑/mock 级测试（不触碰 patchright driver）。
"""
import importlib
import os
import sqlite3
import sys
import time

os.environ["no_proxy"] = "*"; os.environ["NO_PROXY"] = "*"
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRAPER_DIR = os.path.join(_BACKEND_DIR, "51job_scraper")
for p in (_SCRAPER_DIR, _BACKEND_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

import pytest

risk_guard = importlib.import_module("risk_guard")
engine_lock = importlib.import_module("engine_lock")
progress_tracker = importlib.import_module("progress_tracker")
api_client = importlib.import_module("api_client")
RiskLevel = risk_guard.RiskLevel


# ============================================================
# 1. engine_lock 单一持有者模型
# ============================================================

class TestEngineLock:
    def _fresh_dir(self, tmp_path):
        d = tmp_path / "profile"
        d.mkdir()
        return str(d)

    def test_acquire_and_release(self, tmp_path):
        d = self._fresh_dir(tmp_path)
        ok, reason = engine_lock.acquire_lock(d, purpose="test")
        assert ok, reason
        # 二次抢锁（同进程 pid 存活、心跳新鲜）必须被拒 —— 单一持有者
        ok2, reason2 = engine_lock.acquire_lock(d, purpose="test2")
        assert not ok2
        assert "被其他进程持有" in reason2
        engine_lock.release_lock(d)
        # 释放后可再抢
        ok3, _ = engine_lock.acquire_lock(d, purpose="test3")
        assert ok3
        engine_lock.release_lock(d)

    def test_stale_lock_takeover_when_pid_dead(self, tmp_path):
        d = self._fresh_dir(tmp_path)
        lock_file = engine_lock.lock_path(d)
        os.makedirs(d, exist_ok=True)
        with open(lock_file, "w", encoding="utf-8") as f:
            import json
            json.dump({"pid": 999999999, "purpose": "ghost", "started_at": 0, "heartbeat": time.time()}, f)
        # pid 已死 → stale 接管成功
        ok, _ = engine_lock.acquire_lock(d, purpose="takeover")
        assert ok

    def test_stale_lock_takeover_when_heartbeat_expired(self, tmp_path):
        d = self._fresh_dir(tmp_path)
        lock_file = engine_lock.lock_path(d)
        import json
        with open(lock_file, "w", encoding="utf-8") as f:
            # pid 活着（本进程）但心跳远超阈值 → 仍应接管（孤儿锁自愈，覆盖 R2 P2）
            json.dump({"pid": os.getpid(), "purpose": "zombie", "started_at": 0,
                       "heartbeat": time.time() - engine_lock.LOCK_STALE_SECS - 10}, f)
        ok, _ = engine_lock.acquire_lock(d, purpose="takeover2")
        assert ok

    def test_heartbeat_refresh_and_release_safety(self, tmp_path):
        d = self._fresh_dir(tmp_path)
        engine_lock.acquire_lock(d, purpose="hb")
        engine_lock.heartbeat(d)
        import json
        with open(engine_lock.lock_path(d), encoding="utf-8") as f:
            data = json.load(f)
        assert data["pid"] == os.getpid()
        engine_lock.release_lock(d)
        assert not os.path.exists(engine_lock.lock_path(d))
        # 重复释放不抛错
        engine_lock.release_lock(d)

    def test_lock_pid_reprisin_host(self, tmp_path):
        """R1 P0 回归：锁必须可记另一进程 pid（登录守护 worker）。
        Web 服务（父进程）不能误删 worker 的锁；worker 自身用 pid=proc.pid 释放。"""
        import os as _os
        d = self._fresh_dir(tmp_path)
        worker_pid = _os.getpid() + 100000  # 模拟另一个进程
        ok, _ = engine_lock.acquire_lock(d, purpose="login_guard", pid=worker_pid)
        assert ok
        import json
        with open(engine_lock.lock_path(d), encoding="utf-8") as f:
            data = json.load(f)
        assert data["pid"] == worker_pid
        # 父进程（本测试进程）直接释放：pid 不匹配 → 锁保留（防误删）
        engine_lock.release_lock(d)
        assert _os.path.exists(engine_lock.lock_path(d))
        # worker 以自身 pid 释放：成功删除
        engine_lock.release_lock(d, pid=worker_pid)
        assert not _os.path.exists(engine_lock.lock_path(d))

    def test_login_state_roundtrip(self, tmp_path):
        d = self._fresh_dir(tmp_path)
        assert not engine_lock.read_login_state(d)
        engine_lock.write_login_state(d)
        assert engine_lock.read_login_state(d)
        # 过期判定
        assert not engine_lock.read_login_state(d, max_age_secs=-1)

    def test_invalidate_login_state(self, tmp_path):
        """2026-09-25 登录门加固：DOM 实测证伪后清标记，防 7 天快速通道带病上岗。"""
        d = self._fresh_dir(tmp_path)
        engine_lock.write_login_state(d)
        assert engine_lock.read_login_state(d)
        engine_lock.invalidate_login_state(d)
        assert not engine_lock.read_login_state(d)
        engine_lock.invalidate_login_state(d)  # 幂等：文件缺失不抛


# ============================================================
# 1.5 引擎登录门：deliver 用途强制 DOM 实测（2026-09-25 真机教训）
# 服务端会话可先于 cookie 过期；采集快速标记照旧，投递必须实测。
# ============================================================

class TestEngineLoginGate:
    """纯 mock：伪造 patchright.sync_api 与 DOM 探测，验证 launch_or_fail 登录门分支。

    语义（2026-09-25 用户裁决）：deliver 强制 DOM 实测、失败 raise + 清带病标记；
    collect 标记有效走快速通道，无标记/标记失效且 DOM 实测失败 → 警告放行匿名采集
    （搜索页实测匿名可抓，采集流量不再绑定账号）。
    """

    @pytest.fixture
    def launch_env(self, monkeypatch, tmp_path):
        """搭建可跑 launch_or_fail 的全桩环境，返回探针计数器字典。"""
        import types
        engine = importlib.import_module("engine")
        profile = tmp_path / "profile"
        profile.mkdir()
        monkeypatch.setattr(engine, "PROFILE_DIR", str(profile))
        monkeypatch.setattr(engine, "acquire_lock", lambda *a, **k: (True, ""))
        monkeypatch.setattr(engine, "release_lock", lambda *a, **k: None)

        calls = {"dom_confirmed": 0, "probe": 0, "invalidated": 0}

        class _FakeContext:
            pages = []

            def cookies(self, urls):
                return [{"name": "acw_tc"}]  # 非空 → 跳过 legacy 迁移

            def close(self):
                pass

        class _FakeMgr:
            def start(self):
                return self

            @property
            def chromium(self):
                return self

            def launch_persistent_context(self, **kw):
                return _FakeContext()

            def stop(self):
                pass

        fake_pw = types.ModuleType("patchright.sync_api")
        fake_pw.sync_playwright = lambda: _FakeMgr()
        monkeypatch.setitem(sys.modules, "patchright.sync_api", fake_pw)
        return engine, profile, calls

    def test_deliver_forces_dom_check_and_invalidates_stale_mark(self, launch_env, monkeypatch):
        """deliver + 7 天内标记 + DOM 实测失败 → 必须 raise 且清掉带病标记。"""
        engine, profile, calls = launch_env
        engine_lock.write_login_state(profile)  # 标记未过期（假阳性来源）
        monkeypatch.setattr(engine, "_login_dom_confirmed", lambda ctx: calls.__setitem__("dom_confirmed", calls["dom_confirmed"] + 1) or False)
        monkeypatch.setattr(engine, "_verify_login_via_page", lambda ctx: calls.__setitem__("probe", calls["probe"] + 1) or False)
        real_invalidate = engine.invalidate_login_state
        monkeypatch.setattr(engine, "invalidate_login_state",
                            lambda p: calls.__setitem__("invalidated", calls["invalidated"] + 1) or real_invalidate(p))

        with pytest.raises(RuntimeError, match="登录态失效"):
            engine.launch_or_fail(purpose="deliver")
        assert calls["dom_confirmed"] == 1 and calls["probe"] == 1  # 标记被跳过，DOM 实测跑了
        assert calls["invalidated"] == 1 and not engine_lock.read_login_state(str(profile))

    def test_deliver_with_healthy_login_passes_gate(self, launch_env, monkeypatch):
        """deliver：跳过快速标记、DOM 实测确认登录 → 放行。"""
        engine, profile, calls = launch_env
        engine_lock.write_login_state(profile)
        monkeypatch.setattr(engine, "_login_dom_confirmed", lambda ctx: False)
        monkeypatch.setattr(engine, "_verify_login_via_page", lambda ctx: True)
        ctx_mgr = engine.launch_or_fail(purpose="deliver")
        assert ctx_mgr is not None

    def test_collect_keeps_fast_mark_path(self, launch_env, monkeypatch):
        """collect + 7 天内标记 → 快速通道照旧，不做 DOM 探测（零额外开页）。"""
        engine, profile, calls = launch_env
        engine_lock.write_login_state(profile)
        monkeypatch.setattr(engine, "_login_dom_confirmed", lambda ctx: calls.__setitem__("dom_confirmed", calls["dom_confirmed"] + 1) or False)
        monkeypatch.setattr(engine, "_verify_login_via_page", lambda ctx: calls.__setitem__("probe", calls["probe"] + 1) or True)
        engine.launch_or_fail(purpose="collect")
        assert calls["dom_confirmed"] == 0 and calls["probe"] == 0

    def test_collect_anonymous_degrade_when_login_dead(self, launch_env, monkeypatch, capsys):
        """collect + 无有效标记 + DOM 实测失败 → 警告放行匿名采集（2026-09-25 用户裁决，不再 raise）。"""
        engine, profile, calls = launch_env
        monkeypatch.setattr(engine, "_login_dom_confirmed", lambda ctx: False)
        monkeypatch.setattr(engine, "_verify_login_via_page", lambda ctx: False)
        ctx_mgr = engine.launch_or_fail(purpose="collect")
        assert ctx_mgr is not None, "采集不得被登录态卡死"
        assert "匿名模式" in capsys.readouterr().out

    def test_collect_anonymous_degrade_no_mark_side_effect(self, launch_env, monkeypatch):
        """collect 匿名放行路径：无标记场景不触发清除（零副作用）。"""
        engine, profile, calls = launch_env
        calls["invalidated"] = 0
        monkeypatch.setattr(engine, "invalidate_login_state",
                            lambda p: calls.__setitem__("invalidated", calls["invalidated"] + 1))
        monkeypatch.setattr(engine, "_login_dom_confirmed", lambda ctx: False)
        monkeypatch.setattr(engine, "_verify_login_via_page", lambda ctx: False)
        engine.launch_or_fail(purpose="collect")
        assert calls["invalidated"] == 0


# ============================================================
# 2. risk_guard L0-L3 全分级 + 降级边界
# ============================================================

class TestRiskGuard:
    @pytest.mark.parametrize("status,ct,body,expected", [
        (200, "application/json", '{"status":1}', RiskLevel.L0_OK),
        # 滑块/验证 → L3（大小写不敏感）
        (200, "text/html", "<html>请按住滑块，拖动到最右侧</html>", RiskLevel.L3_BLOCKED),
        (200, "text/html", "Access Verification", RiskLevel.L3_BLOCKED),
        (200, "application/json", '{"msg":"captcha required"}', RiskLevel.L3_BLOCKED),
        # 限流 → L2
        (200, "application/json", '{"msg":"今日投递太多"}', RiskLevel.L2_THROTTLE),
        # 5xx → L1（服务端抖动）
        (502, "text/html", "Bad Gateway", RiskLevel.L1_SOFT),
        (500, "application/json", "{}", RiskLevel.L1_SOFT),
        # 403/429 → L3（风控）
        (403, "text/html", "Forbidden", RiskLevel.L3_BLOCKED),
        (429, "application/json", "{}", RiskLevel.L3_BLOCKED),
        # R1 P1 修复锁定：页内 fetch 执行异常/网络故障（status<=0）→ L1 技术异常，绝不误判 L3
        (-1, "", "TypeError: Cannot read properties of undefined", RiskLevel.L1_SOFT),
        (0, "", "network timeout", RiskLevel.L1_SOFT),
    ])
    def test_classify_http_response(self, status, ct, body, expected):
        assert risk_guard.classify_http_response(status, ct, body) == expected

    @pytest.mark.parametrize("body,expected", [
        # L0：正常有岗位
        ({"status": 1, "resultbody": {"job": {"items": [{"jobName": "x"}], "totalCount": 100}}}, RiskLevel.L0_OK),
        # L0：合法零结果
        ({"status": 1, "resultbody": {"job": {"items": [], "totalCount": 0}}}, RiskLevel.L0_OK),
        # L2：status 异常但 totalCount>0（有效词被限流）
        ({"status": 1001, "resultbody": {"job": {"items": [], "totalCount": 50}}}, RiskLevel.L2_THROTTLE),
        # L2：status 异常且无 totalCount（无法证明合法空结果）
        ({"status": 1001, "resultbody": {"job": {"items": []}}}, RiskLevel.L2_THROTTLE),
        # L1：结构解析不出
        ({"weird": True}, RiskLevel.L1_SOFT),
        ("not-a-dict", RiskLevel.L1_SOFT),
    ])
    def test_classify_api_body(self, body, expected):
        level, _reason = risk_guard.classify_api_body(body)
        assert level == expected

    def test_page_signal(self):
        assert risk_guard.classify_page_signal("正常岗位列表") is None
        assert risk_guard.classify_page_signal("请按住滑块") == RiskLevel.L3_BLOCKED
        assert risk_guard.classify_page_signal("您今日投递太多") == RiskLevel.L2_THROTTLE

    def test_degrade_boundary_fail_closed(self):
        """关键约束（R1 修正项）：仅 L1 允许降级 DOM；L2/L3 必须 fail-closed 终止。"""
        assert risk_guard.should_degrade_to_dom(RiskLevel.L1_SOFT) is True
        assert risk_guard.should_degrade_to_dom(RiskLevel.L0_OK) is False
        assert risk_guard.should_degrade_to_dom(RiskLevel.L2_THROTTLE) is False
        assert risk_guard.should_degrade_to_dom(RiskLevel.L3_BLOCKED) is False
        assert risk_guard.should_terminate_task(RiskLevel.L3_BLOCKED) is True
        assert risk_guard.should_terminate_task(RiskLevel.L2_THROTTLE) is False


# ============================================================
# 3. progress_tracker 词级检查点
# ============================================================

class TestProgressTracker:
    def _conn(self, tmp_path):
        conn = sqlite3.connect(str(tmp_path / "job_hunter.db"))
        progress_tracker.ensure_table(conn)
        return conn

    def test_combo_key_normalization(self):
        # None/空串统一 "any"，防同词不同 key
        assert progress_tracker.combo_key("python", None, "") == "python:any:any"
        assert progress_tracker.combo_key("python", "030200", "07") == "python:030200:07"
        assert progress_tracker.combo_key(" python ", "", None) == "python:any:any"

    def test_should_skip_and_mark(self, tmp_path):
        conn = self._conn(tmp_path)
        key = "python:030200:07"
        assert progress_tracker.should_skip(conn, key) is False
        progress_tracker.mark_collected(conn, key)
        assert progress_tracker.should_skip(conn, key) is True
        # 24h 前的记录 → 不跳过
        conn.execute("UPDATE collect_progress_51job SET last_collected_at = ? WHERE combo_key = ?",
                     ((time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - 25 * 3600))), key))
        conn.commit()
        assert progress_tracker.should_skip(conn, key) is False
        conn.close()

    def test_upsert_idempotent(self, tmp_path):
        conn = self._conn(tmp_path)
        key = "go:040000:any"
        progress_tracker.mark_collected(conn, key)
        first = progress_tracker.get_last_collected(conn, key)
        time.sleep(1.1)
        progress_tracker.mark_collected(conn, key)
        second = progress_tracker.get_last_collected(conn, key)
        assert second >= first and first is not None
        conn.close()


# ============================================================
# 4. api_client：末页收窄 + 分级接线
# ============================================================

class TestApiClient:
    def test_real_last_page_narrowing(self):
        assert api_client.real_last_page(0) == 1
        assert api_client.real_last_page(-5) == 1
        assert api_client.real_last_page(1) == 1
        assert api_client.real_last_page(20) == 1
        assert api_client.real_last_page(21) == 2
        assert api_client.real_last_page(720) == 36
        # fallback 收窄：totalCount 很大也封顶 50
        assert api_client.real_last_page(100000) == api_client.HARD_MAX_PAGES
        # 有效末页小于 fallback 时取小（BossHunter 误停修复的核心）
        assert api_client.real_last_page(720, fallback=10) == 10

    def test_fetch_search_page_dom_layer(self, monkeypatch):
        """DOM 提取层分级接线（2026-09-24 SSR-DOM 修正版）。

        fetch_search_page 现从 page.evaluate 的 sensorsdata 提取结果分级：
        卡片未渲染（wait_for_selector 抛错）+ 页面无验证文案 → L1；
        卡片渲染但提取空 → L1（结构改版嫌疑）；正常 → L0 + items。
        """
        class FakePage:
            def __init__(self, eval_ret=None, fail_selector=False):
                self._ret = eval_ret or {}
                self._fail = fail_selector
            def wait_for_selector(self, *a, **k):
                if self._fail:
                    raise TimeoutError("selector timeout")
            def evaluate(self, js): return self._ret
            def inner_text(self, *a, **k): return "正常岗位列表文本"

        monkeypatch.setattr(api_client, "_rate_limit_wait", lambda: 0.0)

        # 正常提取 → L0 + items
        r = api_client.fetch_search_page(FakePage({"items": [{"jobId": "1"}], "total": 40, "bodyHead": "岗位列表"}), "py", "030200", "", 1)
        assert r["level"] == RiskLevel.L0_OK
        assert r["total"] == 40 and len(r["items"]) == 1

        # 卡片渲染但 sensorsdata 空 → L1（结构改版嫌疑，允许降级）
        r = api_client.fetch_search_page(FakePage({"items": [], "total": 40, "bodyHead": "岗位列表"}), "py", "030200", "", 1)
        assert r["level"] == RiskLevel.L1_SOFT

        # 卡片未渲染 + 页面无验证文案 → L1
        r = api_client.fetch_search_page(FakePage(fail_selector=True), "py", "030200", "", 1)
        assert r["level"] == RiskLevel.L1_SOFT

        # 卡片未渲染 + 页面有验证墙文案 → L3
        class WalledPage(FakePage):
            def inner_text(self, *a, **k): return "请按住滑块，拖动到最右侧"
        r = api_client.fetch_search_page(WalledPage(fail_selector=True), "py", "030200", "", 1)
        assert r["level"] == RiskLevel.L3_BLOCKED

    def test_rate_limit_window(self, monkeypatch):
        """滑动窗口：超 RPM 后要求等待。"""
        monkeypatch.setattr(api_client, "_RATE_WINDOW", [])
        monkeypatch.setattr(api_client, "API_MAX_RPM", 2)
        assert api_client._rate_limit_wait() == 0.0
        assert api_client._rate_limit_wait() == 0.0
        assert api_client._rate_limit_wait() > 0  # 第 3 次（超限）→ 需等待


# ============================================================
# 1.7 会话 cookie 持久化（2026-09-25 真机破案：关窗即死 cookie）
# ============================================================

class TestPersistSessionCookies:
    def _ctx(self, cookies, batch_fail=False, bad_names=()):
        added = []

        class _FakeContext:
            def cookies(self, domains=None):
                return cookies

            def add_cookies(self, cs):
                if batch_fail and len(cs) > 1:
                    raise RuntimeError("批量校验被脏 cookie 拖垮")
                for c in cs:
                    if c["name"] in bad_names:
                        raise RuntimeError(f"非法属性: {c['name']}")
                    added.append(c)

        return _FakeContext(), added

    def test_session_cookies_get_persisted_expiry_and_domain_filter(self):
        import time as _time
        engine = importlib.import_module("engine")
        cookies = [
            {"name": "sess", "domain": ".51job.com", "path": "/", "expires": -1, "httpOnly": True},
            {"name": "nokey", "domain": "we.51job.com", "path": "/"},
            {"name": "perm", "domain": ".51job.com", "path": "/", "expires": 1800000000},
            {"name": "ads", "domain": ".adnetwork.com", "path": "/", "expires": -1},
        ]
        ctx, added = self._ctx(cookies)
        n = engine.persist_session_cookies(ctx)
        assert n == 2 and len(added) == 2, "只改写 51job 域的会话 cookie，第三方域不动"
        assert all(c["expires"] > _time.time() + 29 * 86400 for c in added), "改写后应为 30 天持久"
        assert added[0]["httpOnly"] is True and added[0]["name"] == "sess", "字段必须原样保留"
        assert all(c["name"] not in ("perm", "ads") for c in added)

    def test_batch_failure_falls_back_to_per_item(self):
        """R1 P1：批量回注被单个脏 cookie 拖垮时必须逐条降级，核心会话不能全军覆没。"""
        engine = importlib.import_module("engine")
        cookies = [
            {"name": "dirty", "domain": ".51job.com", "path": "/", "expires": -1},
            {"name": "core_session", "domain": ".51job.com", "path": "/", "expires": -1},
        ]
        ctx, added = self._ctx(cookies, batch_fail=True, bad_names=("dirty",))
        n = engine.persist_session_cookies(ctx)
        assert n == 1 and [c["name"] for c in added] == ["core_session"], "脏 cookie 被跳过，核心会话保住"

    def test_error_and_empty_paths_return_zero(self):
        engine = importlib.import_module("engine")

        class _Dead:
            def cookies(self):
                raise RuntimeError("context gone")

        assert engine.persist_session_cookies(_Dead()) == 0
        ctx, added = self._ctx([])
        assert engine.persist_session_cookies(ctx) == 0
        assert added == []
