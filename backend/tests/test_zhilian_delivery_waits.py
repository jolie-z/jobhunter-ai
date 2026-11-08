"""智联投递条件等待辅助函数回归测试（2026-10-29 沙箱事故根治）。

背景：Windows 沙箱等慢机器上固定 sleep+短查找随机翻车——
①删完简历 1s 后列表还没重渲染就去点上传（第二次失败：找不到 input[type=file]）；
②点完「立即投递」只等 8s 弹窗未渲染即保守中止（第一次失败）。
本轮改造：删后等列表真的少一条、找 input 轮询 20s（8s 未现重点一次上传按钮）、
弹窗等待 8s→20s。此处用假时钟/假页面验证各辅助函数的等待与补救行为。
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_ENGINE_DIR = _BACKEND_DIR / "zhilian_scraper"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))
if str(_ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(_ENGINE_DIR))

import zhilian_auto_delivery


class FakeTime:
    """可控时钟：sleep 即推进，避免真实等待拖慢测试。"""

    def __init__(self, step=0.5):
        self.now = 0.0
        self.step = step

    def time(self):
        return self.now

    # helper 已改用 monotonic（防系统时钟回拨），假时钟同一推进
    monotonic = time

    def sleep(self, seconds):
        self.now += max(seconds, self.step)


def _make_tab(ele_results=None, ele_predicate=None):
    """假标签页：.ele() 按脚本列表或谓词返回，.click() 记录调用。"""
    tab = MagicMock()
    calls = {"ele": 0, "click": 0}

    def _ele(spec, timeout=1, *args, **kwargs):
        idx = calls["ele"]
        calls["ele"] += 1
        if ele_predicate is not None:
            return ele_predicate(spec, idx)
        if ele_results is None:
            return None
        return ele_results[idx] if idx < len(ele_results) else None

    tab.ele.side_effect = _ele
    tab.click.side_effect = lambda *a, **k: calls.__setitem__("click", calls["click"] + 1)
    tab.calls = calls
    return tab


def test_wait_resume_gone_returns_true_when_absent_immediately(monkeypatch):
    ft = FakeTime()
    monkeypatch.setattr(zhilian_auto_delivery, "time", ft)
    monkeypatch.setattr(zhilian_auto_delivery, "_safe_eles", lambda tab, sel, timeout=3, retries=3: [])

    tab = MagicMock()
    assert zhilian_auto_delivery._wait_resume_gone(tab, "融科联创", timeout_s=8) is True
    assert ft.now == 0.0, "列表里已无目标时不应空等"


def test_wait_resume_gone_waits_until_item_disappears(monkeypatch):
    ft = FakeTime()
    monkeypatch.setattr(zhilian_auto_delivery, "time", ft)

    remaining = {"count": 2}

    def fake_safe_eles(tab, sel, timeout=3, retries=3):
        remaining["count"] -= 1
        if remaining["count"] > 0:
            return [MagicMock(text="融科联创(天津)_AI交付经理")]
        return []

    monkeypatch.setattr(zhilian_auto_delivery, "_safe_eles", fake_safe_eles)
    tab = MagicMock()
    assert zhilian_auto_delivery._wait_resume_gone(tab, "融科联创", timeout_s=8) is True


def test_wait_resume_gone_times_out_when_item_never_disappears(monkeypatch):
    ft = FakeTime()
    monkeypatch.setattr(zhilian_auto_delivery, "time", ft)
    monkeypatch.setattr(
        zhilian_auto_delivery, "_safe_eles",
        lambda tab, sel, timeout=3, retries=3: [MagicMock(text="融科联创(天津)_AI交付经理")],
    )
    tab = MagicMock()
    assert zhilian_auto_delivery._wait_resume_gone(tab, "融科联创", timeout_s=2) is False
    assert ft.now >= 2.0


def test_wait_slot_below_polls_until_below_limit(monkeypatch):
    ft = FakeTime()
    monkeypatch.setattr(zhilian_auto_delivery, "time", ft)

    states = [[MagicMock()] * 3, [MagicMock()] * 2]

    def fake_safe_eles(tab, sel, timeout=3, retries=3):
        return states.pop(0) if len(states) > 1 else states[0]

    monkeypatch.setattr(zhilian_auto_delivery, "_safe_eles", fake_safe_eles)
    assert zhilian_auto_delivery._wait_slot_below(MagicMock(), 3, timeout_s=8) is True


def test_wait_file_input_found_without_reclick(monkeypatch):
    ft = FakeTime()
    monkeypatch.setattr(zhilian_auto_delivery, "time", ft)

    tab = _make_tab(ele_results=[None, None, "INPUT_EL"])
    clicks = []
    found = zhilian_auto_delivery._wait_file_input_with_reclick(
        tab, lambda: clicks.append(1), timeout_s=20)
    assert found == "INPUT_EL"
    assert clicks == [], "控件正常出现时不应触发重点补救"


def test_wait_file_input_reclicks_once_then_finds(monkeypatch):
    ft = FakeTime()
    monkeypatch.setattr(zhilian_auto_delivery, "time", ft)

    # 前 30 次探测（~15s，跨越 retry_at_s=8s 的重点时点）都落空，之后返回控件
    tab = _make_tab(ele_predicate=lambda spec, idx: "input" if idx >= 30 else None)
    clicks = []
    found = zhilian_auto_delivery._wait_file_input_with_reclick(
        tab, lambda: clicks.append(1), timeout_s=20, retry_at_s=8)
    assert found == "input"
    assert clicks == [1], "超 8s 未渲染应触发一次重点补救"


def test_wait_file_input_reclick_survives_stale_handle(monkeypatch):
    """补救 callable 内部句柄失效自行兜底是调用方职责；helper 只保证补救异常不击穿轮询"""
    ft = FakeTime()
    monkeypatch.setattr(zhilian_auto_delivery, "time", ft)

    tab = _make_tab(ele_predicate=lambda spec, idx: "input" if idx >= 30 else None)

    def _stale_reclick():
        raise RuntimeError("stale element")

    found = zhilian_auto_delivery._wait_file_input_with_reclick(
        tab, _stale_reclick, timeout_s=20, retry_at_s=8)
    assert found == "input", "补救调用抛异常应被吞掉并继续轮询"


def test_wait_file_input_swallows_ele_exception(monkeypatch):
    """页面重渲染期 tab.ele 偶发抛异常不应击穿等待循环"""
    ft = FakeTime()
    monkeypatch.setattr(zhilian_auto_delivery, "time", ft)

    tab = MagicMock()
    flips = {"n": 0}

    def _ele(spec, timeout=1, *a, **k):
        flips["n"] += 1
        if flips["n"] < 5:
            raise RuntimeError("DOM.performSearch searchId")
        return "INPUT_EL"

    tab.ele.side_effect = _ele
    assert zhilian_auto_delivery._wait_file_input_with_reclick(
        tab, lambda: None, timeout_s=20) == "INPUT_EL"


def test_wait_file_input_timeout_returns_none(monkeypatch):
    ft = FakeTime()
    monkeypatch.setattr(zhilian_auto_delivery, "time", ft)

    tab = _make_tab(ele_predicate=lambda spec, idx: None)
    clicks = []
    found = zhilian_auto_delivery._wait_file_input_with_reclick(
        tab, lambda: clicks.append(1), timeout_s=10, retry_at_s=3)
    assert found is None
    assert clicks == [1], "超时路径也只补救一次，绝不无限重点"
    assert ft.now >= 10.0


def test_wait_for_resume_center_any_probe_hits(monkeypatch):
    ft = FakeTime()
    monkeypatch.setattr(zhilian_auto_delivery, "time", ft)

    tab = _make_tab(ele_predicate=lambda spec, idx: "BTN" if "上传新附件" in str(spec) else None)
    assert zhilian_auto_delivery._wait_for_resume_center(tab, timeout_s=12) is True


def test_wait_for_resume_center_timeout_is_non_fatal(monkeypatch):
    ft = FakeTime()
    monkeypatch.setattr(zhilian_auto_delivery, "time", ft)

    tab = _make_tab(ele_predicate=lambda spec, idx: None)
    assert zhilian_auto_delivery._wait_for_resume_center(tab, timeout_s=3) is False
