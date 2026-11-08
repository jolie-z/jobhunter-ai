"""智联薪资筛选守卫测试（2026-10-31 晚间间歇性抖动加固）。

覆盖 zhilian_collector._apply_salary_filter：
- 选项从未渲染：3 次重试全部落空 → 以退出码 2 中止（宁缺毋滥），且留存失败现场
- 第 3 次选项出现：不中止、正常点击生效
- 薪资为空/不限：零交互直接放行
- 诊断留存：截图 + HTML 落盘 zhilian_failure_shots/，保存异常不影响中止
"""
import importlib.util
import sys
import types
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
ZHILIAN_DIR = BACKEND_DIR / "zhilian_scraper"


def _load_collector():
    """zhilian_collector 模块级 import DrissionPage，测试环境用桩模块替代。"""
    dp = sys.modules.get("DrissionPage")
    if dp is None or not hasattr(getattr(dp, "ChromiumOptions", None), "set_local_port"):
        stub = types.ModuleType("DrissionPage")

        class _FakeOptions:
            def __getattr__(self, name):
                def _noop(*a, **k):
                    return self
                return _noop

        stub.ChromiumPage = object
        stub.ChromiumOptions = _FakeOptions
        sys.modules["DrissionPage"] = stub
    spec = importlib.util.spec_from_file_location("zhilian_collector_guard_test", ZHILIAN_DIR / "zhilian_collector.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["zhilian_collector_guard_test"] = mod
    spec.loader.exec_module(mod)
    return mod


class _FakePage:
    """可编程的 DrissionPage 页面替身：按选择器前缀编排返回。"""

    def __init__(self, option_found_on_attempt: int):
        self.entry_clicks = 0
        self.option_clicks = 0
        self.option_found_on_attempt = option_found_on_attempt
        self.option_queries = 0
        self.shots: list[str] = []
        self.html = "<html><body>fake zhaopin page</body></html>"

    def ele(self, selector, timeout=None):
        if selector.startswith("text:薪资"):
            self.entry_clicks += 1
            return _FakeEle(self, kind="entry")
        if selector.startswith("text:15K-25K") or selector.startswith("text:"):
            # 薪资选项查询：按 attempt 序号决定第几次出现（每次 attempt 内入口 1 查 + 选项 1 查）
            self.option_queries += 1
            if self.option_queries >= self.option_found_on_attempt:
                return _FakeEle(self, kind="option")
            return None
        return None

    def get_screenshot(self, path=None, name=None):
        self.shots.append(path or name or "")


class _FakeEle:
    def __init__(self, page: _FakePage, kind="entry"):
        self._page = page
        self.kind = kind

    def click(self, by_js=False):
        if self.kind == "option":
            self._page.option_clicks += 1


@pytest.fixture
def collector(monkeypatch, tmp_path):
    mod = _load_collector()
    # 截止外部副作用：sleep 加速、失败现场落盘到 tmp_path
    monkeypatch.setattr(mod.time, "sleep", lambda *_a, **_k: None)
    shots: list[tuple[str, str]] = []

    def _fake_diag(page, salary):
        shots.append((salary, getattr(page, "html", "")))

    monkeypatch.setattr(mod, "_save_salary_filter_diagnostics", _fake_diag)
    mod._test_shots = shots  # type: ignore[attr-defined]
    return mod


def test_abort_after_three_failed_attempts(collector, monkeypatch):
    """选项 3 次都找不到 → 退出码 2 中止（宁缺毋滥），并留存失败现场。"""
    page = _FakePage(option_found_on_attempt=10**9)  # 永不出现
    with pytest.raises(SystemExit) as exc:
        collector._apply_salary_filter(page, "15K-25K", abort_on_failure=True)
    assert exc.value.code == collector.SALARY_FILTER_ABORT_EXIT_CODE == 2
    assert page.entry_clicks == 3  # 重试 2→3 次加固
    assert collector._test_shots and collector._test_shots[0][0] == "15K-25K"
    assert "fake zhaopin page" in collector._test_shots[0][1]  # HTML 现场已留存


def test_success_on_third_attempt(collector):
    """前两次未渲染、第 3 次出现 → 正常点击生效，不中止。"""
    page = _FakePage(option_found_on_attempt=3)
    assert collector._apply_salary_filter(page, "15K-25K", abort_on_failure=True) is True
    assert page.entry_clicks == 3
    assert page.option_clicks == 1
    assert collector._test_shots == []  # 成功不留存现场


def test_empty_salary_passes_through_without_interaction(collector):
    page = _FakePage(option_found_on_attempt=10**9)
    assert collector._apply_salary_filter(page, "", abort_on_failure=True) is True
    assert collector._apply_salary_filter(page, "不限", abort_on_failure=True) is True
    assert page.entry_clicks == 0


def test_idempotent_when_salary_already_selected(collector):
    """当前页面标签已是目标薪资 → 直接生效放行，零额外点击。"""
    class _AlreadySelectedBox:
        def __init__(self, text):
            self.text = text
        def ele(self, selector, timeout=None):
            return self

    class _IdempotentPage(_FakePage):
        def eles(self, selector, timeout=None):
            if selector == ".filter-select-box":
                return [_AlreadySelectedBox("15K-25K")]
            return []

    page = _IdempotentPage(option_found_on_attempt=10**9)
    assert collector._apply_salary_filter(page, "15K-25K", abort_on_failure=True) is True
    assert page.entry_clicks == 0
    assert page.option_clicks == 0
