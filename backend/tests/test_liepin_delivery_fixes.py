"""猎聘投递链路质检修复的回归测试（2026-09-15，无浏览器纯逻辑）。

覆盖本轮修复的关键行为：
1. 附件卡片选择器必须约束在 .attachment-view-box 主展示区（侧边栏 resume-analysis-card 虚增槽位回归防护）；
2. 槽位清理失败必须显式抛错，不得静默继续上传；低于上限时不得触发删除；
3. 模块 import 不得隐式拉起 Edge（page 懒加载）；
4. get_browser_page 探活：句柄失联自动重建，句柄存活直接复用；
5. 附件名消毒同源：上传入库与 IM 浮层匹配前缀必须来自同一消毒结果；
6. mass_apply 补传重试只补发简历，不得重复发送打招呼语；
7. 懒加载句柄禁止 from-import（质检抓出 liepin_editor 绑定 None 的回归）：全仓静态守卫 + editor 动态取句柄行为；
8. 通用简历汰旧换新闭环：清不干净必须抛错；浮层选择以"今日上传日期"断言为准，不依赖未契约的 DOM 排序；
9. 通用简历判定只认规范标记，裸「通用」子串会误伤「通用技术集团」等真实公司名。
"""
import importlib
import re
import subprocess
import sys
import textwrap
import time
import types
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
ENGINE_DIR = BACKEND_DIR / "liepin_scraper"
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))
try:
    import liepin_auto_delivery as lad
    import liepin_im_sender
    import liepin_resume_manager
    import liepin_session
    HAS_ENGINE = True
except Exception:
    HAS_ENGINE = False

pytestmark = pytest.mark.skipif(not HAS_ENGINE, reason="DrissionPage 不可用")


# ---------------- 1. 选择器收敛 ----------------

def test_resume_card_selector_scoped_to_main_box():
    assert lad.CSS_RESUME_CARD_CONTAINER.startswith("css:.attachment-view-box ")
    assert lad.CSS_RESUME_CARD_CONTAINER.endswith(".resume-card-container")


# ---------------- 2. 槽位清理失败显式化 ----------------

class _Card:
    def __init__(self, name, has_more=False):
        self.name = name
        self.has_more = has_more

    def ele(self, sel, timeout=1):
        if ".file-name" in sel:
            return types.SimpleNamespace(text=self.name)
        if ".more-icon" in sel and self.has_more:
            return types.SimpleNamespace(click=lambda: None)
        return None


class _Page:
    def __init__(self, cards):
        self.cards = list(cards)

    def eles(self, sel):
        if sel == lad.CSS_RESUME_CARD_CONTAINER:
            return list(self.cards)
        return []

    def refresh(self):
        pass

    def remove(self, card):
        self.cards = [c for c in self.cards if c is not card]


def test_ensure_resume_slots_raises_when_delete_fails(monkeypatch):
    monkeypatch.setattr(lad.time, "sleep", lambda s: None)
    cards = [_Card("A_定制.pdf"), _Card("B_定制.pdf"), _Card("曾 纳-通用版.pdf")]
    monkeypatch.setattr(liepin_resume_manager, "page", _Page(cards))
    monkeypatch.setattr(lad, "page", _Page(cards))
    with pytest.raises(RuntimeError, match="槽位清理失败"):
        lad._ensure_resume_slots()


def test_ensure_resume_slots_noop_below_limit(monkeypatch):
    monkeypatch.setattr(lad.time, "sleep", lambda s: None)
    touched = []

    class _SpyCard(_Card):
        def ele(self, sel, timeout=1):
            touched.append(sel)
            return super().ele(sel, timeout)

    monkeypatch.setattr(liepin_resume_manager, "page", _Page([_SpyCard("A_定制.pdf"), _SpyCard("曾 纳-通用版.pdf")]))
    monkeypatch.setattr(lad, "page", _Page([_SpyCard("A_定制.pdf"), _SpyCard("曾 纳-通用版.pdf")]))
    lad._ensure_resume_slots()
    assert touched == [], "2 份附件尚有空槽位，不应触碰任何卡片的删除入口"


# ---------------- 3. import 无副作用 ----------------

def test_import_is_side_effect_free():
    code = textwrap.dedent(f"""
        import sys
        sys.path.insert(0, {str(BACKEND_DIR)!r})
        sys.path.insert(0, {str(ENGINE_DIR)!r})
        import liepin_auto_delivery as lad
        import liepin_session
        assert lad.page is None and liepin_session.page is None, (lad.page, liepin_session.page)
        print("LAZY_OK")
    """)
    res = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=90)
    assert res.returncode == 0, res.stderr
    assert "LAZY_OK" in res.stdout


# ---------------- 4. get_browser_page 探活自愈 ----------------

def test_get_browser_page_rebuilds_dead_handle(monkeypatch):
    class _Dead:
        quit_called = False

        @property
        def url(self):
            raise ConnectionError("browser gone")

        def quit(self):
            self.quit_called = True

    dead = _Dead()
    fresh = types.SimpleNamespace(url="https://c.liepin.com/")
    ctor_calls = []
    monkeypatch.setattr(liepin_session, "ChromiumPage", lambda opts: ctor_calls.append(opts) or fresh)
    monkeypatch.setattr(liepin_session, "page", dead)
    monkeypatch.setattr(lad, "ChromiumPage", lambda opts: ctor_calls.append(opts) or fresh)
    monkeypatch.setattr(lad, "page", dead)

    got = lad.get_browser_page()

    assert got is fresh and (lad.page is fresh or liepin_session.page is fresh)
    assert dead.quit_called
    assert ctor_calls == [lad._co]


def test_get_browser_page_reuses_live_handle(monkeypatch):
    live = types.SimpleNamespace(url="https://c.liepin.com/")
    monkeypatch.setattr(liepin_session, "page", live)
    monkeypatch.setattr(lad, "page", live)
    monkeypatch.setattr(liepin_session, "ChromiumPage", lambda opts: pytest.fail("句柄存活时不得重建浏览器"))
    monkeypatch.setattr(lad, "ChromiumPage", lambda opts: pytest.fail("句柄存活时不得重建浏览器"))
    assert lad.get_browser_page() is live


# ---------------- 5. 附件名消毒同源 ----------------

@pytest.mark.parametrize("raw", [
    "ABC Capital 软件工程师",
    "字节跳动/抖音 产品经理",
    '腾讯"云"架构师: 高级',
])
def test_sanitize_title_consistency_between_upload_and_modal(raw):
    clean = lad._sanitize_resume_title(raw)
    assert " " not in clean and "/" not in clean and '"' not in clean and ":" not in clean
    assert len(clean) <= 20
    # 上传校验用 clean[:8]，浮层匹配也必须用同一消毒结果的前缀；原始名前缀含空格/斜杠时必然错配
    assert lad._sanitize_resume_title(raw)[:8] == clean[:8]
    assert raw[:8] != clean[:8]


def test_sanitize_title_fallback_when_empty():
    assert lad._sanitize_resume_title("   ") == "专属定制简历"


# ---------------- 6. mass_apply 补传不重复打招呼 ----------------

def test_mass_apply_retry_only_resends_resume(monkeypatch, tmp_path):
    pdf_name = "补传测试"
    (tmp_path / f"{pdf_name}.pdf").write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr(lad, "TEMP_DIR", str(tmp_path))
    monkeypatch.setattr(lad, "ensure_login", lambda wait_s=0: True)
    monkeypatch.setattr(lad, "update_feishu_record", lambda *a, **k: None)

    calls = []
    monkeypatch.setattr(lad, "_manage_and_upload_resume", lambda p, n, *a, **kw: calls.append(("upload", n)))

    def _first_attempt(_job_url, _greeting, name, **_kwargs):
        calls.append(("chat_and_send", name))
        raise RuntimeError(f"发送浮层中未出现目标简历「{name}」，中止发送以防发错简历")

    monkeypatch.setattr(lad, "_chat_and_send_resume", _first_attempt)
    monkeypatch.setattr(lad, "_open_chat_box", lambda url: calls.append(("open_chat", url)) or "box")
    monkeypatch.setattr(lad, "_send_chat_message", lambda box, g: calls.append(("greeting", g)))
    monkeypatch.setattr(lad, "_send_resume_in_chat", lambda name, mass_apply=False: calls.append(("send_resume", name)))

    job_url = "https://www.liepin.com/job/1.shtml"
    ok = lad.deliver_job({
        "job_url": job_url, "pdf_name": pdf_name, "greeting": "您好", "record_id": "", "mass_apply": True,
    })

    assert ok is True
    assert calls == [
        ("upload", pdf_name),
        ("chat_and_send", pdf_name),
        ("upload", pdf_name),
        ("open_chat", job_url),
        ("send_resume", pdf_name),
    ]
    assert not any(c[0] == "greeting" for c in calls), "补传重试不得重复发送打招呼语"


# ---------------- 7. 通用简历汰旧换新闭环 ----------------

def test_generic_resume_retires_all_old_generics_when_uploading_new(monkeypatch):
    monkeypatch.setattr(lad.time, "sleep", lambda s: None)
    fake = _Page([_Card("曾 纳-通用版.pdf"), _Card("我的简历.pdf"), _Card("某某科技_产品经理.pdf")])
    deleted = []

    def _fake_delete(item):
        deleted.append(item.name)
        fake.remove(item)
        return True

    monkeypatch.setattr(liepin_resume_manager, "_delete_resume_card", _fake_delete)
    monkeypatch.setattr(liepin_resume_manager, "page", fake)

    lad._ensure_resume_slots(upload_name="通用简历-最新", mass_apply=True)

    assert sorted(deleted) == ["我的简历.pdf", "曾 纳-通用版.pdf"], "上传新通用简历前必须清空全部历史通用简历"
    assert [c.name for c in fake.cards] == ["某某科技_产品经理.pdf"], "不得误删定制简历"


def test_generic_retire_raises_when_old_generic_survives(monkeypatch):
    monkeypatch.setattr(lad.time, "sleep", lambda s: None)
    fake = _Page([_Card("曾 纳-通用版.pdf")])
    # 删除动作"谎报成功"但卡片仍在——失效句柄点击空转的真实场景，绝不能静默放行去上传
    monkeypatch.setattr(liepin_resume_manager, "_delete_resume_card", lambda item: True)
    monkeypatch.setattr(liepin_resume_manager, "page", fake)
    with pytest.raises(RuntimeError, match="汰旧换新失败"):
        lad._ensure_resume_slots(upload_name="通用简历-最新", mass_apply=True)


def test_custom_resume_keeps_generic_and_deletes_oldest_custom():
    cards = [
        _Card("华勤技术_产品经理.pdf"),
        _Card("九四智能_产品经理.pdf"),
        _Card("通用简历-最新.pdf"),
    ]
    target = lad._find_target_resume_to_delete(cards, is_uploading_generic=False, upload_name="新公司_新岗位")
    assert target.name == "九四智能_产品经理.pdf", "上传定制简历时满槽位应优先淘汰最早的定制简历，保护通用简历"


@pytest.mark.parametrize("name,expected", [
    ("通用简历-最新.pdf", True),
    ("曾 纳-通用版.pdf", True),
    ("我的简历.pdf", True),
    ("通用技术集团_机械工程师.pdf", False),
    ("通用汽车_软件工程师.pdf", False),
    ("九四智能_产品经理.pdf", False),
    ("", False),
])
def test_generic_title_heuristic_rejects_company_names(name, expected):
    assert lad._is_generic_resume_title(name) is expected


# ---------------- 8. 浮层选简历：今日日期断言优先于 DOM 排序 ----------------

def _modal_item(label, date, tag, clicked):
    return types.SimpleNamespace(text=f"{label}\n{date}上传", click=lambda **kw: clicked.append(tag))


def _modal_page(expected_items, generic_items=()):
    def _eles(sel):
        if "ancestor::label" not in sel:
            return []
        if "'通用简历'" in sel or "'我的简历'" in sel:
            return list(generic_items)
        return list(expected_items)

    return types.SimpleNamespace(
        wait=types.SimpleNamespace(ele_displayed=lambda *a, **k: True),
        eles=_eles,
        ele=lambda sel, timeout=1: None,
    )


def test_modal_locks_today_dated_candidate_regardless_of_order(monkeypatch):
    clicked = []
    today = time.strftime("%Y.%m.%d")
    old = _modal_item("通用简历-最新", "2020.01.01", "OLD", clicked)
    new = _modal_item("通用简历-最新", today, "NEW", clicked)
    # 故意把旧卡放在首位：选择必须由日期决定，而不是"浮层第一位"
    monkeypatch.setattr(liepin_im_sender, "page", _modal_page([old, new]))
    monkeypatch.setattr(lad.time, "sleep", lambda s: None)

    lad._select_resume_in_modal("通用简历-最新", mass_apply=True)
    assert clicked == ["NEW"]


def test_modal_locks_today_dated_candidate_with_online_hyphen_format(monkeypatch):
    """验证线上真实 DOM 文本格式（如「2026-09-15 23:12上传」）能被准确识别并锁定"""
    clicked = []
    today_hyphen = time.strftime("%Y-%m-%d")
    old = _modal_item("我的简历", "2026-08-24 00:04", "OLD", clicked)
    new = _modal_item("我的简历", f"{today_hyphen} 23:12", "NEW", clicked)
    # 旧卡放在首位，确保是通过识别今日连字符日期命中最新条目
    monkeypatch.setattr(liepin_im_sender, "page", _modal_page([old, new], generic_items=[old, new]))
    monkeypatch.setattr(lad.time, "sleep", lambda s: None)

    lad._select_resume_in_modal("我的简历", mass_apply=True)
    assert clicked == ["NEW"]


def test_modal_refuses_generic_without_today_date(monkeypatch):
    clicked = []
    old = _modal_item("通用简历-最新", "2020.01.01", "OLD", clicked)
    monkeypatch.setattr(liepin_im_sender, "page", _modal_page([old], generic_items=[old]))
    monkeypatch.setattr(lad.time, "sleep", lambda s: None)

    with pytest.raises(RuntimeError, match="中止发送"):
        lad._select_resume_in_modal("通用简历-最新", mass_apply=True)
    assert clicked == [], "通用简历只有历史日期条目时必须中止，绝不发旧版"


def test_modal_generic_fallback_requires_today_date(monkeypatch):
    clicked = []
    today = time.strftime("%Y.%m.%d")
    stale = _modal_item("我的简历", "2020.01.01", "STALE", clicked)
    fresh = _modal_item("我的简历", today, "FRESH", clicked)
    # expected 前缀四轮都匹配不到 → 兜底只允许今日上传的通用条目，旧卡即使排在首位也不得选中
    monkeypatch.setattr(liepin_im_sender, "page", _modal_page([], generic_items=[stale, fresh]))
    monkeypatch.setattr(lad.time, "sleep", lambda s: None)

    lad._select_resume_in_modal("通用简历-最新", mass_apply=True)
    assert clicked == ["FRESH"]


def test_modal_custom_degrades_to_first_when_no_date_mark(monkeypatch):
    clicked = []
    only = types.SimpleNamespace(text="九四智能_产品经理", click=lambda **kw: clicked.append("ONLY"))
    monkeypatch.setattr(liepin_im_sender, "page", _modal_page([only]))
    monkeypatch.setattr(lad.time, "sleep", lambda s: None)

    lad._select_resume_in_modal("九四智能_产品经理", mass_apply=False)
    assert clicked == ["ONLY"], "定制简历前缀唯一，无日期标记时允许降级选取，不得因日期缺失误伤精投"


# ---------------- 8. 懒加载句柄禁止 from-import（liepin_editor 回归） ----------------

_SKIP_DIRS = {".venv", "__pycache__", "node_modules"}
_FROM_IMPORT_RE = re.compile(r"^\s*from\s+\S*liepin_\w+\s+import\s*\(?([^)\n]*)", re.M)


def test_no_module_from_imports_page_handle():
    offenders = []
    for path in BACKEND_DIR.rglob("*.py"):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        for m in _FROM_IMPORT_RE.finditer(path.read_text(encoding="utf-8", errors="ignore")):
            names = {n.strip().split(" as ")[0] for n in m.group(1).split(",")}
            if "page" in names:
                offenders.append(str(path.relative_to(BACKEND_DIR)))
    assert offenders == [], f"这些模块 from-import 了懒加载句柄 page，会永久绑定 None：{offenders}"


def test_liepin_editor_uses_dynamic_page_handle(monkeypatch):
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))
    editor = importlib.import_module("resume_editor.platforms.liepin_editor")
    assert not hasattr(editor, "page"), "editor 不得在模块级持有 page 句柄"

    visited = []
    fake_page = types.SimpleNamespace(get=lambda url: visited.append(url), html="<html></html>")
    monkeypatch.setattr(editor, "_inject_cookies_if_needed", lambda: None)
    monkeypatch.setattr(editor, "get_browser_page", lambda: fake_page)
    monkeypatch.setattr(editor.time, "sleep", lambda s: None)

    data = editor.scrape_liepin_resume_fields()

    assert visited == [editor.LIEPIN_RESUME_URL]
    assert isinstance(data, dict) and data


# ---------------- 9. 成功路径清空失败日志 & 微聊补发模式（2026-09-15） ----------------

def _stub_full_success_flow(monkeypatch, tmp_path, pdf_name):
    """构造「本地 PDF 就绪 + 上传/沟通全部成功」的无浏览器投递环境"""
    (tmp_path / f"{pdf_name}.pdf").write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr(lad, "TEMP_DIR", str(tmp_path))
    monkeypatch.setattr(lad, "ensure_login", lambda wait_s=0: True)
    monkeypatch.setattr(lad, "_manage_and_upload_resume", lambda *a, **kw: None)
    monkeypatch.setattr(lad, "_chat_and_send_resume", lambda *a, **kw: None)


def test_delivered_success_clears_failure_log(monkeypatch, tmp_path):
    """投递成功必须同步清空「自动投递失败日志」，拔除登录态残留等历史旧账（对齐 BOSS/智联/51job 口径）"""
    _stub_full_success_flow(monkeypatch, tmp_path, "清日志测试")
    writes = []
    monkeypatch.setattr(lad, "update_feishu_record", lambda rid, fields: writes.append((rid, dict(fields))))

    ok = lad.deliver_job({
        "job_url": "https://www.liepin.com/job/1.shtml",
        "pdf_name": "清日志测试", "greeting": "您好", "record_id": "recX",
    })

    assert ok is True
    rid, fields = writes[-1]
    assert rid == "recX"
    assert fields["跟进状态"] == "已投递"
    assert fields["自动投递失败日志"] == "", "成功路径必须清空历史失败日志，否则已送达打招呼语会被误判为未送达"
    assert "投递日期" in fields


def test_retry_greeting_only_resends_greeting_without_upload(monkeypatch):
    """微聊补发模式：只唤起聊天窗口重发打招呼语，跳过 PDF 下载与槽位上传，且不得覆盖原投递日期"""
    calls = []
    writes = []
    monkeypatch.setattr(lad, "ensure_login", lambda wait_s=0: True)
    monkeypatch.setattr(lad, "update_feishu_record", lambda rid, fields: writes.append((rid, dict(fields))))
    monkeypatch.setattr(
        lad, "get_job_record_from_feishu",
        lambda rid, tid: {"record_id": rid, "fields": {"跟进状态": "已投递"}},
    )

    def _forbid(*_a, **_kw):
        raise AssertionError("补发打招呼模式不得触发简历上传/投递闭环")

    monkeypatch.setattr(lad, "_manage_and_upload_resume", _forbid)
    monkeypatch.setattr(lad, "_chat_and_send_resume", _forbid)
    monkeypatch.setattr(lad, "_open_chat_box", lambda url: calls.append(("open_chat", url)) or "box")
    monkeypatch.setattr(lad, "_send_chat_message", lambda box, g: calls.append(("greeting", g)))

    job_url = "https://www.liepin.com/job/2.shtml"
    ok = lad.deliver_job({
        "job_url": job_url, "pdf_name": "补发测试", "greeting": "您好，再次沟通",
        "record_id": "recY", "retry_greeting_only": True,
    })

    assert ok is True
    assert calls == [("open_chat", job_url), ("greeting", "您好，再次沟通")]
    rid, fields = writes[-1]
    assert rid == "recY"
    assert fields["自动投递失败日志"] == "", "补发成功必须清空受阻/残留日志"
    assert "投递日期" not in fields, "补发打招呼不得覆盖原投递日期"


def test_retry_greeting_only_degrades_to_full_delivery_when_not_delivered(monkeypatch, tmp_path):
    """补发防呆：跟进状态并非「已投递」时必须降级为完整投递，绝不空补打招呼"""
    calls = []
    monkeypatch.setattr(lad, "TEMP_DIR", str(tmp_path))
    monkeypatch.setattr(lad, "ensure_login", lambda wait_s=0: True)
    monkeypatch.setattr(
        lad, "get_job_record_from_feishu",
        lambda rid, tid: {"record_id": rid, "fields": {"跟进状态": "待投递"}},
    )
    monkeypatch.setattr(lad, "_manage_and_upload_resume", lambda p, n, *a, **kw: calls.append(("upload", n)))
    monkeypatch.setattr(lad, "_chat_and_send_resume", lambda *a, **kw: calls.append(("chat_and_send",)))
    monkeypatch.setattr(lad, "update_feishu_record", lambda *a, **kw: None)

    pdf_name = "降级测试"
    (tmp_path / f"{pdf_name}.pdf").write_bytes(b"%PDF-1.4 fake")
    ok = lad.deliver_job({
        "job_url": "https://www.liepin.com/job/3.shtml", "pdf_name": pdf_name,
        "greeting": "您好", "record_id": "", "retry_greeting_only": True,
    })

    assert ok is True
    assert ("upload", pdf_name) in calls and ("chat_and_send",) in calls, "非已投递记录必须走完整投递链路"


def test_retry_greeting_only_fails_fast_on_empty_greeting(monkeypatch):
    """补发模式下打招呼语为空：快速失败并带 [微聊受阻] 标记落库，保留台账补发入口"""
    writes = []
    monkeypatch.setattr(lad, "ensure_login", lambda wait_s=0: True)
    monkeypatch.setattr(lad, "update_feishu_record", lambda rid, fields: writes.append((rid, dict(fields))))
    monkeypatch.setattr(
        lad, "get_job_record_from_feishu",
        lambda rid, tid: {"record_id": rid, "fields": {"跟进状态": "已投递"}},
    )

    ok = lad.deliver_job({
        "job_url": "https://www.liepin.com/job/4.shtml", "pdf_name": "空语测试",
        "greeting": "   ", "record_id": "recZ", "retry_greeting_only": True,
    })

    assert ok is False
    rid, fields = writes[-1]
    assert rid == "recZ"
    assert "[微聊受阻]" in fields["自动投递失败日志"], "补发失败必须带受阻标记，供已投递台账判定未送达"
