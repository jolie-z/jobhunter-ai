"""L2 自愈动作库 + L3 AI 诊断官的单元测试。

覆盖 2026-08-28 落地的自愈体系：
- self_heal.pick_heal_action: 错误文本 → 自愈动作映射；
- diag_agent._parse_json_loose / _extract_relevant_log / needs_diagnosis: 诊断官的纯函数部分。
LLM 调用与浏览器重启涉及外部依赖，不在单测覆盖范围（由真实波次验证）。
"""
import asyncio
import time

import app.automation.self_heal as heal
import app.automation.diag_agent as diag


# ---------------- L2: 平台名归一化 ----------------

def test_restart_platform_browser_accepts_display_name(monkeypatch):
    """飞书展示名（猎聘/BOSS直聘）必须归一化到 registry 规范键（2026-10-30 工单）。

    病灶：resolve_platform("猎聘") 恒为 None，自愈台账只留「未知平台 猎聘，无法重启浏览器」，
    L2 自愈对中文平台名全线失效。
    """
    from app.session import browser

    monkeypatch.setattr(time, "sleep", lambda _s: None)
    launched: list[str] = []
    monkeypatch.setattr(browser, "close_edge", lambda cfg: True)
    monkeypatch.setattr(browser, "launch_edge", lambda cfg, url=None: launched.append(cfg.name))

    ok, detail = asyncio.run(heal.restart_platform_browser("猎聘"))

    assert ok is True
    assert "猎聘" in detail
    assert launched == ["liepin"], "中文展示名必须归一化到 liepin 才能重启专用浏览器"


def test_restart_platform_browser_still_rejects_unknown(monkeypatch):
    ok, detail = asyncio.run(heal.restart_platform_browser("不存在的平台"))
    assert ok is False
    assert "未知平台" in detail


def test_restart_platform_browser_handles_empty_platform():
    """空值防御等价性（替代旧 `(platform or "").lower()`）：None/空串不得抛异常。

    platform_display_to_key 内部 `str(name or "")` 已做兜底，本用例锁定该契约，
    防止未来重写归一化函数时把空值防御弄丢。
    """
    for bad in (None, ""):
        ok, detail = asyncio.run(heal.restart_platform_browser(bad))
        assert ok is False
        assert "未知平台" in detail


# ---------------- L2: pick_heal_action ----------------

def test_heal_tab_error_maps_to_restart_browser():
    assert heal.pick_heal_action("投递异常: The specified tab was not found") == "restart_browser"


def test_heal_generic_engine_failure_maps_to_restart_browser():
    # 引擎吞掉细节统一报「执行失败」时，重启浏览器无害且大概率有效
    assert heal.pick_heal_action("❌ 智联投递引擎执行失败，请检查相关日志") == "restart_browser"


def test_heal_persistent_errors_need_no_heal():
    assert heal.pick_heal_action("❌ 缺少 PDF 简历附件") == ""
    assert heal.pick_heal_action("岗位已下架") == ""
    assert heal.pick_heal_action("") == ""


# ---------------- L3: needs_diagnosis ----------------

def test_needs_diagnosis_below_threshold():
    assert diag.needs_diagnosis({"failure_count": 1}) is False


def test_needs_diagnosis_triggered_at_threshold():
    assert diag.needs_diagnosis({"failure_count": 2}) is True


def test_needs_diagnosis_skipped_when_already_done_for_same_count():
    failure = {"failure_count": 3, "diagnosis": {"for_failure_count": 3, "root_cause": "x"}}
    assert diag.needs_diagnosis(failure) is False


def test_needs_diagnosis_reruns_when_count_grew():
    failure = {"failure_count": 4, "diagnosis": {"for_failure_count": 3}}
    assert diag.needs_diagnosis(failure) is True


# ---------------- L3: JSON 解析与日志抽取 ----------------

def test_parse_json_loose_plain():
    assert diag._parse_json_loose('{"a": 1}') == {"a": 1}


def test_parse_json_loose_codefence_wrapped():
    raw = "```json\n{\"root_cause\": \"标签页丢失\", \"category\": \"环境故障\"}\n```"
    parsed = diag._parse_json_loose(raw)
    assert parsed["category"] == "环境故障"


def test_parse_json_loose_with_trailing_text():
    raw = '前置说明 {"category": "引擎缺陷"} 后置说明'
    assert diag._parse_json_loose(raw)["category"] == "引擎缺陷"


def test_extract_relevant_log_anchored_context():
    log_text = "\n".join(
        [f"info line {i}" for i in range(100)]
        + ["    raise RuntimeError(NO_SUCH_TAB)", "RuntimeError: ", "    ❌ 引擎执行失败"]
    )
    chunk = diag._extract_relevant_log(log_text, platform="智联")
    assert "NO_SUCH_TAB" in chunk
    assert "info line 99" in chunk  # 锚点前上下文被带上
    assert "info line 0" not in chunk  # 远处无关行被裁掉


def test_extract_relevant_log_falls_back_to_tail():
    chunk = diag._extract_relevant_log("plain log without anchors", platform="boss")
    assert chunk == "plain log without anchors"


# ---------------- L2: append_heal_log 台账追加 ----------------

def test_append_heal_log_writes_into_failure_entry(monkeypatch):
    import app.automation.run_snapshot as run_snapshot
    monkeypatch.setattr(run_snapshot, "_save_to_db", lambda: None)
    run_snapshot._delivery_failures.clear()
    run_snapshot.record_delivery_failure("rec_h", error="tab not found", job_name="岗位H")

    heal.append_heal_log("rec_h", {"action": "restart_browser", "success": True, "detail": "智联招聘 浏览器已重启", "at": "2026-08-28 18:00:00"})
    entry = run_snapshot._delivery_failures["rec_h"]
    assert len(entry["heal_log"]) == 1
    assert entry["heal_log"][0]["success"] is True

    # 不存在的岗位静默忽略；空 heal 忽略
    heal.append_heal_log("rec_missing", {"action": "restart_browser", "success": True})
    heal.append_heal_log("rec_h", {})
    assert len(run_snapshot._delivery_failures["rec_h"]["heal_log"]) == 1

    run_snapshot._delivery_failures.clear()
