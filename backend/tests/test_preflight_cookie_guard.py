"""preflight 免登录平台 Cookie 文件守卫测试（2026-09-26 新机体验小批）。

背景：猎聘 requires_login=False 全豁免 vs 抓取引擎硬依赖 liepin_cookies.json
（缺文件直接 0 条收工）的设计断裂，导致新克隆机器整轮链路空转"快速结束"。
修复后：豁免分支对配置了 legacy_cookie_file 的平台做文件存在性检查，
缺失 → 进等待窗口（飞书通知指引扫码 + hot-polling 文件落盘即放行 + 超时跳过）。

2026-10-28 四平台行为统一：文件缺失且无登录实证时，预检内自动唤起专用浏览器
（与 requires_login 平台同通道），用户在等待窗口内直接扫码登录；
拉起后补一次 CDP 实证复检，离线读库漏判的既有登录态当场放行。
"""
import asyncio
import json
import os
import threading
import time

from app.session import preflight
from app.session.models import PlatformConfig


def _write_cookie_file(path: str, *, valid: bool = True) -> None:
    """写猎聘 cookie 文件；valid=False 时写「存在但凭证已过期」的内容。

    2026-10-31 事故根治：预检对猎聘按「存在且凭证未过期」判定，空壳/过期
    文件必须走「失效」通道（实证复检 → 唤起等待窗），不再直接放行。
    """
    if not valid:
        with open(path, "w", encoding="utf-8") as f:
            json.dump([
                {"name": "lt_auth", "value": "expired", "expires": time.time() - 100},
                {"name": "liepin_login_valid", "value": "1", "expires": time.time() - 100},
            ], f)
        return
    with open(path, "w", encoding="utf-8") as f:
        json.dump([
            {"name": "lt_auth", "value": "valid", "expires": time.time() + 7 * 24 * 3600},
            {"name": "liepin_login_valid", "value": "1", "expires": time.time() + 7 * 24 * 3600},
        ], f)


def _make_config(tmp_path, cookie_exists: bool, cookie_valid: bool = True) -> PlatformConfig:
    cookie_file = os.path.join(str(tmp_path), "liepin_cookies.json")
    if cookie_exists:
        _write_cookie_file(cookie_file, valid=cookie_valid)
    return PlatformConfig(
        name="liepin",
        display_name="猎聘",
        port=9226,
        requires_login=False,
        legacy_cookie_file=cookie_file,
    )


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _fake_emit_log(messages: list):
    async def emit(msg: str):
        messages.append(msg)
    return emit


def _fake_browser_ready(calls: list, ok: bool = True):
    async def _ready(config, emit_log=None, out_reason=None):
        calls.append(config.name)
        if out_reason is not None:
            out_reason.clear()
            out_reason["reason"] = "alive"  # 浏览器温启动：稳定期路径不触发
        return ok

    return _ready


def test_cookie_file_present_passes_through(tmp_path, monkeypatch):
    """文件存在（现行为回归）：豁免登录判定，但仍需保障浏览器就绪。"""
    config = _make_config(tmp_path, cookie_exists=True)
    monkeypatch.setattr(preflight, "resolve_platform", lambda key: config)

    launched: list[str] = []
    monkeypatch.setattr(preflight, "_ensure_browser_ready", _fake_browser_ready(launched, ok=True))

    logs: list[str] = []
    result = _run(preflight.ensure_platforms_ready(["liepin"], emit_log=_fake_emit_log(logs)))

    assert result == {"liepin": True}
    assert launched == ["liepin"]  # 2026-10-31：Cookie 存在也走浏览器就绪
    assert any("豁免预检登录校验" in m for m in logs)


def test_cookie_file_stale_intercepts_as_expired(tmp_path, monkeypatch):
    """2026-10-31 事故根治回归：文件存在但凭证过期 → 不再放行，按「失效」进等待窗。

    当天事故：过期文件放行 → 引擎降级访客态深页抓取 → 被登录墙整轮拦截 →
    静默 0 条收场还报成功。新契约：失效文件与缺失文件同通道，但文案明确
    区分「已失效」。
    """
    config = _make_config(tmp_path, cookie_exists=True, cookie_valid=False)
    monkeypatch.setattr(preflight, "resolve_platform", lambda key: config)
    monkeypatch.setattr(preflight, "_wait_seconds", lambda: 0)
    monkeypatch.setattr(preflight, "check_liepin_login_evidence", lambda: False)

    launched: list[str] = []
    monkeypatch.setattr(preflight, "_ensure_browser_ready", _fake_browser_ready(launched, ok=True))

    notified: list[tuple] = []

    async def fake_notify(items, wait_s, launched=None):
        for cfg, status, kind in items:
            assert kind == preflight._PENDING_KIND_COOKIE_FILE
            assert "已失效" in status.message
            notified.append(cfg.name)

    monkeypatch.setattr(preflight, "_notify_login_needed", fake_notify)

    logs: list[str] = []
    result = _run(preflight.ensure_platforms_ready(["liepin"], emit_log=_fake_emit_log(logs)))

    assert result == {"liepin": False}
    assert launched == ["liepin"]
    assert notified == ["liepin"]
    assert any("Cookie 文件已失效" in m for m in logs)
    assert not any("豁免预检登录校验" in m for m in logs)


def test_cookie_file_stale_but_evidence_valid_passes(tmp_path, monkeypatch):
    """文件失效但 profile 登录实证有效 → 放行（引擎启动后自愈回写新文件）。"""
    config = _make_config(tmp_path, cookie_exists=True, cookie_valid=False)
    monkeypatch.setattr(preflight, "resolve_platform", lambda key: config)
    monkeypatch.setattr(preflight, "check_liepin_login_evidence", lambda: True)

    launched: list[str] = []
    monkeypatch.setattr(preflight, "_ensure_browser_ready", _fake_browser_ready(launched, ok=True))

    logs: list[str] = []
    result = _run(preflight.ensure_platforms_ready(["liepin"], emit_log=_fake_emit_log(logs)))

    assert result == {"liepin": True}
    assert launched == []  # 实证放行无需唤起浏览器
    assert any("登录实证有效" in m for m in logs)


def test_cookie_file_missing_intercepts_with_guide(tmp_path, monkeypatch):
    """文件缺失：自动唤起浏览器后拦截进等待窗口，通知文案含扫码脚本指引。"""
    config = _make_config(tmp_path, cookie_exists=False)
    monkeypatch.setattr(preflight, "resolve_platform", lambda key: config)
    monkeypatch.setattr(preflight, "_wait_seconds", lambda: 0)  # 窗口=0，直接走超时跳过分支
    monkeypatch.setattr(preflight, "check_liepin_login_evidence", lambda: False)  # 实证也否，防真机端口探测

    launched: list[str] = []
    monkeypatch.setattr(preflight, "_ensure_browser_ready", _fake_browser_ready(launched, ok=True))

    notified: list[tuple] = []

    async def fake_notify(items, wait_s, launched=None):
        for cfg, _status, kind in items:
            assert kind == preflight._PENDING_KIND_COOKIE_FILE
            notified.append((f"{cfg.display_name}:{kind}", set(launched or set())))

    monkeypatch.setattr(preflight, "_notify_login_needed", fake_notify)

    logs: list[str] = []
    result = _run(preflight.ensure_platforms_ready(["liepin"], emit_log=_fake_emit_log(logs)))

    assert result == {"liepin": False}  # 超时跳过该平台
    assert launched == ["liepin"]  # 四平台行为统一：预检内自动唤起浏览器
    assert notified == [("猎聘:cookie_file", {"liepin"})]
    assert any("缺少 Cookie 文件" in m and "liepin_cookie_harvester" in m for m in logs)
    assert any("已自动唤起专用浏览器" in m for m in logs)
    assert any("等待超时仍未生成 Cookie 文件" in m for m in logs)


def test_cookie_file_hot_poll_releases_when_created(tmp_path, monkeypatch):
    """hot-polling：等待窗口内文件被扫码脚本落盘的瞬间放行，不做 DOM 判定。"""
    config = _make_config(tmp_path, cookie_exists=False)
    monkeypatch.setattr(preflight, "resolve_platform", lambda key: config)
    monkeypatch.setattr(preflight, "_wait_seconds", lambda: 8)
    monkeypatch.setattr(preflight, "_poll_seconds", lambda: 1)
    monkeypatch.setattr(preflight, "check_liepin_login_evidence", lambda: False)  # 实证恒否，专测文件路径
    monkeypatch.setattr(preflight, "_ensure_browser_ready", _fake_browser_ready([], ok=True))

    def _touch_later():
        time.sleep(1.2)
        with open(config.legacy_cookie_file, "w", encoding="utf-8") as f:
            f.write("{}")

    threading.Thread(target=_touch_later, daemon=True).start()

    logs: list[str] = []
    result = _run(preflight.ensure_platforms_ready(["liepin"], emit_log=_fake_emit_log(logs)))

    assert result == {"liepin": True}
    assert any("登录已恢复" in m for m in logs)


def test_cookie_file_check_never_crashes_on_io_error(tmp_path, monkeypatch):
    """文件检查 IO 异常（权限等）按缺失处理，预检不 crash。"""
    config = _make_config(tmp_path, cookie_exists=True)
    monkeypatch.setattr(preflight, "resolve_platform", lambda key: config)
    monkeypatch.setattr(preflight, "_wait_seconds", lambda: 0)
    monkeypatch.setattr(preflight, "check_liepin_login_evidence", lambda: False)  # 实证也否，防真机端口探测
    monkeypatch.setattr(preflight, "_ensure_browser_ready", _fake_browser_ready([], ok=False))

    def _boom(path):
        raise OSError("permission denied")

    monkeypatch.setattr(preflight.os.path, "exists", _boom)

    logs: list[str] = []
    result = _run(preflight.ensure_platforms_ready(["liepin"], emit_log=_fake_emit_log(logs)))

    assert result == {"liepin": False}  # 按缺失走等待窗口→超时跳过，而非异常冒泡


# ==========================================
# 双判据新增用例（2026-09-27：文件 OR Edge profile 登录实证）
# ==========================================

def test_cookie_file_missing_but_evidence_ok_passes(tmp_path, monkeypatch):
    """双判据：文件缺失但 Edge profile 登录实证有效 → 直接放行，不进等待窗口。"""
    config = _make_config(tmp_path, cookie_exists=False)
    monkeypatch.setattr(preflight, "resolve_platform", lambda key: config)

    evidence_calls = []

    def fake_evidence():
        evidence_calls.append(1)
        return True

    monkeypatch.setattr(preflight, "check_liepin_login_evidence", fake_evidence)

    logs: list[str] = []
    result = _run(preflight.ensure_platforms_ready(["liepin"], emit_log=_fake_emit_log(logs)))

    assert result == {"liepin": True}
    assert len(evidence_calls) == 1  # 守卫期一次实证即放行，不拉起浏览器、不进等待循环
    assert any("登录实证有效" in m for m in logs)


def test_cookie_file_missing_and_evidence_false_intercepts(tmp_path, monkeypatch):
    """双判据皆否：维持原拦截路径（等待窗口+飞书通知+超时跳过）。

    本用例取浏览器唤起失败场景：文案保留「会话条手动唤起」兜底指引双通道。"""
    config = _make_config(tmp_path, cookie_exists=False)
    monkeypatch.setattr(preflight, "resolve_platform", lambda key: config)
    monkeypatch.setattr(preflight, "_wait_seconds", lambda: 0)
    monkeypatch.setattr(preflight, "check_liepin_login_evidence", lambda: False)
    monkeypatch.setattr(preflight, "_ensure_browser_ready", _fake_browser_ready([], ok=False))

    notified: list[int] = []

    async def fake_notify(items, wait_s, launched=None):
        notified.append(len(items))

    monkeypatch.setattr(preflight, "_notify_login_needed", fake_notify)

    logs: list[str] = []
    result = _run(preflight.ensure_platforms_ready(["liepin"], emit_log=_fake_emit_log(logs)))

    assert result == {"liepin": False}
    assert notified == [1]
    # 文案双通道指引：会话条登录 与 harvester 脚本并列
    assert any("唤起浏览器" in m and "liepin_cookie_harvester" in m for m in logs)


def test_wait_window_recheck_releases_on_evidence(tmp_path, monkeypatch):
    """等待窗口复检双判据：文件始终缺失，实证中途转真 → 放行（拉起后扫码登录解锁路径）。"""
    config = _make_config(tmp_path, cookie_exists=False)
    monkeypatch.setattr(preflight, "resolve_platform", lambda key: config)
    monkeypatch.setattr(preflight, "_wait_seconds", lambda: 8)
    monkeypatch.setattr(preflight, "_poll_seconds", lambda: 1)
    monkeypatch.setattr(preflight, "_ensure_browser_ready", _fake_browser_ready([], ok=True))

    seq = [False, False, True]  # 守卫期实证否 → 拉起后复检仍否 → 窗口内复检实证转真（模拟用户完成登录）

    def fake_evidence():
        return seq.pop(0) if seq else True

    monkeypatch.setattr(preflight, "check_liepin_login_evidence", fake_evidence)

    notified: list[int] = []

    async def fake_notify(items, wait_s, launched=None):
        notified.append(len(items))

    monkeypatch.setattr(preflight, "_notify_login_needed", fake_notify)

    logs: list[str] = []
    result = _run(preflight.ensure_platforms_ready(["liepin"], emit_log=_fake_emit_log(logs)))

    assert result == {"liepin": True}
    assert any("登录已恢复" in m for m in logs)


# ==========================================
# 四平台行为统一：自动唤起专用浏览器（2026-10-28）
# ==========================================

def test_cookie_file_missing_auto_launches_browser(tmp_path, monkeypatch):
    """文件缺失且实证为否：预检内自动唤起专用浏览器，不再干等用户去会话条手动唤起。"""
    config = _make_config(tmp_path, cookie_exists=False)
    monkeypatch.setattr(preflight, "resolve_platform", lambda key: config)
    monkeypatch.setattr(preflight, "_wait_seconds", lambda: 0)
    monkeypatch.setattr(preflight, "check_liepin_login_evidence", lambda: False)

    launched: list[str] = []
    monkeypatch.setattr(preflight, "_ensure_browser_ready", _fake_browser_ready(launched, ok=True))

    async def fake_notify(items, wait_s, launched=None):
        pass

    monkeypatch.setattr(preflight, "_notify_login_needed", fake_notify)

    logs: list[str] = []
    result = _run(preflight.ensure_platforms_ready(["liepin"], emit_log=_fake_emit_log(logs)))

    assert result == {"liepin": False}  # 唤起后仍无人登录 → 窗口（0s）到跳过
    assert launched == ["liepin"]  # 浏览器被自动唤起一次
    assert any("已自动唤起专用浏览器" in m for m in logs)


def test_evidence_revealed_after_launch_passes_without_wait(tmp_path, monkeypatch):
    """拉起浏览器后 CDP 直读翻出既有登录态 → 当场放行，不进等待窗口、不发通知。"""
    config = _make_config(tmp_path, cookie_exists=False)
    monkeypatch.setattr(preflight, "resolve_platform", lambda key: config)
    monkeypatch.setattr(preflight, "_wait_seconds", lambda: 60)

    seq = [False, True]  # 守卫期（端口 DOWN，离线读库）否 → 拉起后 CDP 直读转真

    def fake_evidence():
        return seq.pop(0) if seq else True

    monkeypatch.setattr(preflight, "check_liepin_login_evidence", fake_evidence)
    monkeypatch.setattr(preflight, "_ensure_browser_ready", _fake_browser_ready([], ok=True))

    notified: list[int] = []

    async def fake_notify(items, wait_s, launched=None):
        notified.append(len(items))

    monkeypatch.setattr(preflight, "_notify_login_needed", fake_notify)

    logs: list[str] = []
    result = _run(preflight.ensure_platforms_ready(["liepin"], emit_log=_fake_emit_log(logs)))

    assert result == {"liepin": True}
    assert notified == []  # 未进等待窗口
    assert any("登录实证有效" in m for m in logs)


def test_launch_failure_keeps_manual_guide(tmp_path, monkeypatch):
    """浏览器唤起失败：仍进等待窗口，通知走「会话条手动唤起」兜底文案，launched 集合为空。"""
    config = _make_config(tmp_path, cookie_exists=False)
    monkeypatch.setattr(preflight, "resolve_platform", lambda key: config)
    monkeypatch.setattr(preflight, "_wait_seconds", lambda: 0)
    monkeypatch.setattr(preflight, "check_liepin_login_evidence", lambda: False)
    monkeypatch.setattr(preflight, "_ensure_browser_ready", _fake_browser_ready([], ok=False))

    notified: list[set] = []

    async def fake_notify(items, wait_s, launched=None):
        notified.append(set(launched or set()))

    monkeypatch.setattr(preflight, "_notify_login_needed", fake_notify)

    logs: list[str] = []
    result = _run(preflight.ensure_platforms_ready(["liepin"], emit_log=_fake_emit_log(logs)))

    assert result == {"liepin": False}
    assert notified == [set()]
    assert any("唤起失败" in m for m in logs)


# ==========================================
# 抓取/投递在飞守卫（外审 round2 P2-b：预检不得干扰在飞操作）
# ==========================================

def _make_login_platform(tmp_path) -> PlatformConfig:
    return PlatformConfig(
        name="zhilian",
        display_name="智联招聘",
        port=9250,
        requires_login=True,
    )


def test_login_check_skipped_when_delivery_busy(tmp_path, monkeypatch):
    """投递在飞：全链路预检跳过 DOM 登录校验直接放行，绝不调用 check_login_with_fallback"""
    from app.automation import platform_mutex

    config = _make_login_platform(tmp_path)
    monkeypatch.setattr(preflight, "resolve_platform", lambda key: config)
    monkeypatch.setattr(preflight, "_ensure_browser_ready", _fake_browser_ready([], ok=True))
    called = {"n": 0}

    def _boom(config, page_factory=None):
        called["n"] += 1
        raise AssertionError("投递在飞时不应做 DOM 登录校验（会跨域导航干扰在飞投递）")

    monkeypatch.setattr(preflight, "check_login_with_fallback", _boom)
    platform_mutex.reset_for_test()
    platform_mutex._busy.setdefault("zhilian", {"scrape": None, "deliver": "rec_inflight"})
    try:
        logs = []
        result = _run(preflight.ensure_platforms_ready(["zhilian"], emit_log=_fake_emit_log(logs)))
        assert result["zhilian"] is True
        assert called["n"] == 0
        assert any("跳过 DOM 登录校验" in m for m in logs)
    finally:
        platform_mutex.reset_for_test()


def test_login_check_skipped_when_scrape_busy(tmp_path, monkeypatch):
    """抓取在飞：全链路预检同样跳过 DOM 登录校验（round1 P1-5 对称面）"""
    from app.automation import platform_mutex

    config = _make_login_platform(tmp_path)
    monkeypatch.setattr(preflight, "resolve_platform", lambda key: config)
    monkeypatch.setattr(preflight, "_ensure_browser_ready", _fake_browser_ready([], ok=True))

    def _boom(config, page_factory=None):
        raise AssertionError("抓取在飞时不应做 DOM 登录校验（会跨域导航干扰在飞抓取）")

    monkeypatch.setattr(preflight, "check_login_with_fallback", _boom)
    platform_mutex.reset_for_test()
    platform_mutex._busy.setdefault("zhilian", {"scrape": "spider_1", "deliver": None})
    try:
        logs = []
        result = _run(preflight.ensure_platforms_ready(["zhilian"], emit_log=_fake_emit_log(logs)))
        assert result["zhilian"] is True
        assert any("抓取/投递进行中" in m for m in logs)
    finally:
        platform_mutex.reset_for_test()


def test_delivery_preflight_skipped_when_busy(tmp_path, monkeypatch):
    """投递逐岗预检（ensure_delivery_platforms_ready）对在飞平台同样放行且不回退缓存"""
    from app.automation import platform_mutex

    config = _make_login_platform(tmp_path)
    monkeypatch.setattr(preflight, "resolve_platform", lambda key: config)

    def _boom(config):
        raise AssertionError("在飞时不应做 DOM 判定（_judge 会导航）")

    monkeypatch.setattr(preflight, "check_login_with_fallback", _boom)
    monkeypatch.setattr(preflight, "_ensure_browser_ready", _fake_browser_ready([], ok=True))
    platform_mutex.reset_for_test()
    platform_mutex._busy.setdefault("zhilian", {"scrape": "spider_1", "deliver": None})
    try:
        logs = []
        result = _run(preflight.ensure_delivery_platforms_ready(["zhilian"], emit_log=_fake_emit_log(logs)))
        assert result["zhilian"] is True
        assert preflight._ready_cache.get("zhilian") is not None, "放行应写入就绪 TTL 缓存"
        assert any("跳过 DOM 判定" in m for m in logs)
    finally:
        platform_mutex.reset_for_test()
        preflight._ready_cache.pop("zhilian", None)


def test_login_check_skipped_via_lease_when_delivery_inflight(tmp_path, monkeypatch):
    """round4-P1-1 行为集成测试：投递在飞且持续超租约等待上限时，全链路预检对
    check_login_with_fallback 零调用（租约超时 → False → 跳过导航存疑放行）。"""
    from app.automation import platform_mutex

    config = PlatformConfig(
        name="zhilian", display_name="智联招聘", port=9250, requires_login=True,
    )
    monkeypatch.setattr(preflight, "resolve_platform", lambda key: config)
    monkeypatch.setattr(preflight, "_ensure_browser_ready", _fake_browser_ready([], ok=True))

    def _boom(config, page_factory=None):
        raise AssertionError("投递在飞时租约应为 False，DOM 导航不得执行")

    monkeypatch.setattr(preflight, "check_login_with_fallback", _boom)
    platform_mutex.reset_for_test()
    platform_mutex._busy.setdefault("zhilian", {"scrape": None, "deliver": "rec_inflight", "preflight": None})
    try:
        logs = []
        result = _run(preflight.ensure_platforms_ready(["zhilian"], emit_log=_fake_emit_log(logs)))
        assert result["zhilian"] is True, "存疑放行"
        assert any("存疑放行" in m or "在飞" in m for m in logs)
        assert platform_mutex._state("zhilian")["preflight"] is None, "租约超时不得残留登记"
    finally:
        platform_mutex.reset_for_test()


def test_judge_lease_false_path_zero_navigation(tmp_path, monkeypatch):
    """round4-P1-1 行为集成测试（投递逐岗预检 _judge 的租约 False 分支）：

    守卫（is_delivery_busy/is_scrape_busy）与租约读同一事实源，两者不可能在同一次调用中
    一真一假——租约 False 只会出现在「守卫判定后、判定执行前」引擎抢跑的 TOCTOU 窗。
    模拟：busy 查询恒 False（守卫放行）+ _acquire 对 preflight 槽返回 False（抢跑），
    断言 _judge 存疑放行（HEALTHY + message 明示）且 check_login_with_fallback 零调用。
    """
    from unittest.mock import patch
    from app.automation import platform_mutex

    config = PlatformConfig(
        name="zhilian", display_name="智联招聘", port=9250, requires_login=True,
    )

    def _boom(config, page_factory=None):
        raise AssertionError("租约 False 后 DOM 判定不得执行")

    platform_mutex.reset_for_test()
    try:
        # busy 查询恒 False：守卫放行（模拟判定时刻引擎尚未登记）
        monkeypatch.setattr(platform_mutex, "is_delivery_busy", lambda raw: False)
        monkeypatch.setattr(platform_mutex, "is_scrape_busy", lambda raw: False)

        async def _deny(kind, key, owner, timeout_s):
            return None if kind == "preflight" else "fake-token"  # token 语义：拒绝=None

        monkeypatch.setattr(platform_mutex, "_acquire", _deny)
        monkeypatch.setattr(preflight, "resolve_platform", lambda key: config)
        monkeypatch.setattr(preflight, "check_login_with_fallback", _boom)
        monkeypatch.setattr(preflight, "_ensure_browser_ready", _fake_browser_ready([], ok=True))

        logs = []
        result = _run(preflight.ensure_delivery_platforms_ready(["zhilian"], emit_log=_fake_emit_log(logs)))
        assert result["zhilian"] is True
        assert any("存疑放行" in m for m in logs), f"应出现 _judge 租约 False 的存疑放行日志: {logs}"
    finally:
        platform_mutex.reset_for_test()
