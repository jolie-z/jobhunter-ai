"""猎聘访客态登录墙如实上报测试（2026-10-31 事故根治）。

事故：Cookie 文件过期 → 预检放行 → 引擎降级访客态 → 深页搜索被登录墙拦截
→ 「未截获数据包」被误判为到底/滑块 → 静默 0 条收场还报成功。

本文件锁定三条契约：
1. 引擎 GUEST_MODE 下未截获数据包必须输出 [LIEPIN_GUEST_BLOCKED] 契约行；
   登录态正常时绝不输出（避免把真到底/滑块误标成登录源失效）。
2. 控制器 _process_crawler_output 识别该行置位 LAST_GUEST_BLOCKED；
3. 契约行不影响 hit_bottom 中断语义（先中断翻页，再按登录源失效计失败）。
"""
import importlib.util
import sys
import types
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
LIEPIN_DIR = BACKEND_DIR / "liepin_scraper"


def _load_crawler_module():
    """liepin_crawler 模块级 import DrissionPage，测试环境用桩模块替代。

    外审 R2-P1（C2）：桩写入 sys.modules 必须用后恢复——否则按字母序紧随其后的
    test_liepin_delivery_fixes.py 会拿到残缺桩（破坏 HAS_ENGINE 门禁或遮蔽真实库）。
    """
    dp_backup = sys.modules.get("DrissionPage")
    injected = False
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
        injected = True
    try:
        spec = importlib.util.spec_from_file_location("liepin_crawler_guest_test", LIEPIN_DIR / "liepin_crawler.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules["liepin_crawler_guest_test"] = mod
        spec.loader.exec_module(mod)
    finally:
        if injected:
            if dp_backup is None:
                sys.modules.pop("DrissionPage", None)
            else:
                sys.modules["DrissionPage"] = dp_backup
    return mod


def _load_nl_controller():
    if str(LIEPIN_DIR) not in sys.path:
        sys.path.insert(0, str(LIEPIN_DIR))
    import liepin_nl_controller as nlc
    return nlc


class _FakeProcess:
    def __init__(self, lines):
        self.stdout = iter(lines)
        self.returncode = 0

    def wait(self):
        return 0


# ==========================================
# 引擎侧：访客态契约行
# ==========================================

def test_guest_packet_miss_prints_contract_marker(monkeypatch, capsys):
    crawler = _load_crawler_module()
    monkeypatch.setattr(crawler, "GUEST_MODE", True)
    monkeypatch.setattr(crawler, "_intercept_job_packet", lambda page, url: (None, None))

    crawler._execute_single_task(
        {"keyword": "AI产品经理", "city": "广州", "salary": "15-20K"},
        0, 1, page=None, target_page=18, target=3, real_page_index=17,
    )

    out = capsys.readouterr().out
    assert "未截获到包含" in out  # 原有中断语义保持（控制器据此 break 翻页）
    assert "LIEPIN_GUEST_BLOCKED" in out  # 契约行：控制器据此计登录源失效


def test_logged_in_packet_miss_has_no_marker(monkeypatch, capsys):
    crawler = _load_crawler_module()
    monkeypatch.setattr(crawler, "GUEST_MODE", False)
    monkeypatch.setattr(crawler, "_intercept_job_packet", lambda page, url: (None, None))

    crawler._execute_single_task(
        {"keyword": "AI产品经理", "city": "广州", "salary": "15-20K"},
        0, 1, page=None, target_page=1, target=3, real_page_index=0,
    )

    out = capsys.readouterr().out
    assert "未截获到包含" in out
    assert "LIEPIN_GUEST_BLOCKED" not in out  # 登录态正常：到底/滑块语义不变


# ==========================================
# 控制器侧：契约行 → LAST_GUEST_BLOCKED
# ==========================================

def test_controller_sets_guest_blocked_flag(monkeypatch):
    nlc = _load_nl_controller()
    monkeypatch.setattr(nlc, "GLOBAL_STOP_FLAG", False)
    monkeypatch.setattr(nlc, "LAST_GUEST_BLOCKED", False)

    proc = _FakeProcess([
        "🚀 启动猎聘【全自动纯净版】采集器 | 锁定抓取页码: P18\n",
        "❌ 在 30 秒内未截获到包含 'jobCardList' 的核心数据包。\n",
        "🚫 [LIEPIN_GUEST_BLOCKED] 当前为访客态（登录源失效/缺失），深页搜索被登录墙拦截——本轮按登录源失效处理。\n",
    ])
    inserted, hit_bottom, search_total = nlc._process_crawler_output(proc, None, None, 3, 18, 0)

    assert (inserted, hit_bottom, search_total) == (0, True, 0)
    assert nlc.LAST_GUEST_BLOCKED is True


def test_controller_clean_run_leaves_flag_false(monkeypatch):
    nlc = _load_nl_controller()
    monkeypatch.setattr(nlc, "GLOBAL_STOP_FLAG", False)
    monkeypatch.setattr(nlc, "LAST_GUEST_BLOCKED", False)

    proc = _FakeProcess([
        "🚀 启动猎聘【全自动纯净版】采集器 | 锁定抓取页码: P1\n",
        "   🕷️ [抓取成功] 🏢 某公司 | 💼 某岗位 | 💰 15-20K\n",
    ])
    inserted, hit_bottom, search_total = nlc._process_crawler_output(proc, None, None, 3, 1, 0)

    assert hit_bottom is False
    assert nlc.LAST_GUEST_BLOCKED is False
