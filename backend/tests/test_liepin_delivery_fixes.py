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
    import liepin_attachment_uploader
    import liepin_im_sender
    import liepin_resume_manager
    import liepin_session
    HAS_ENGINE = True
except Exception:
    HAS_ENGINE = False

pytestmark = pytest.mark.skipif(not HAS_ENGINE, reason="DrissionPage 不可用")


# ---------------- 1. 选择器收敛 ----------------

def test_resume_card_selector_scoped_to_main_box():
    """卡片选择器的每个备选都必须约束在附件主展示区内（旧版 .attachment-view-box /
    2026-10 改版 attachmentView--*），侧边栏 resume-analysis-card 不得被计入槽位。"""
    sel = lad.CSS_RESUME_CARD_CONTAINER
    assert sel.startswith("css:")
    alternatives = [s.strip() for s in sel[len("css:"):].split(",")]
    assert len(alternatives) >= 2, "需同时覆盖改版前后的 DOM"
    for alt in alternatives:
        assert alt.startswith(".attachment-view-box ") or alt.startswith('[class*="attachmentView--"] '), alt
    assert ".attachment-view-box .resume-card-container" in alternatives
    assert '[class*="attachmentView--"] [class*="attachmentCard--"]' in alternatives


@pytest.mark.parametrize("const_name,legacy,current", [
    ("CSS_ANT_MODAL_CLOSE", ".ant-modal-close", ".ant-c-modal-close"),
    ("CSS_MODAL_CONTENT", ".ant-modal-content", ".ant-c-modal-content"),
    ("CSS_DROPDOWN_MENU", ".ant-dropdown-menu", ".ant-c-dropdown-menu"),
    ("CSS_CARD_FILE_NAME", ".file-name", '[class*="fileName--"]'),
    ("CSS_CARD_MORE_ICON", ".more-icon", '[class*="moreIcon--"]'),
    ("CSS_UPLOAD_FILE_INPUT", '.ant-upload input[type="file"]', '.ant-c-upload input[type="file"]'),
])
def test_selectors_cover_both_legacy_and_ant_c_prefix(const_name, legacy, current):
    """2026-10 猎聘换肤：Ant Design 前缀 ant- → ant-c-，业务 class → CSS Modules 哈希。
    每个选择器都必须新旧并列，旧页面灰度/回滚时不再失明。"""
    sel = getattr(liepin_resume_manager, const_name)
    assert legacy in sel and current in sel, sel


def test_popups_modal_selectors_cover_ant_c_prefix():
    import liepin_popups
    assert ".ant-c-modal-close" in liepin_popups.CSS_ANT_MODAL_CLOSE
    assert ".ant-c-modal-content" in liepin_popups.CSS_ANT_MODAL_CONTENT


def test_new_dom_selectors_use_hash_immune_substring_match():
    """CSS Modules 哈希后缀（attachmentCard--XzM2N）随站点构建漂移：
    改版选择器必须写成 [class*="name--"] 前缀子串匹配，且不得把任何具体哈希写死进选择器，
    否则猎聘下次前端发版会再次全灭。"""
    import re
    for const in ("CSS_RESUME_CARD_CONTAINER", "CSS_CARD_FILE_NAME", "CSS_CARD_MORE_ICON"):
        sel = getattr(liepin_resume_manager, const)
        if "[class*=" in sel:
            for frag in re.findall(r'\[class\*="([^"]+)"\]', sel):
                assert frag.endswith("--"), f"{const}: 片段 {frag!r} 未按 name-- 前缀子串匹配"
        assert not re.search(r"--[A-Za-z0-9]{4,}", sel), f"{const}: 写死了 CSS Modules 哈希: {sel}"


def test_upload_entrypoint_is_the_only_production_path():
    """入口不变量（R4-P2）：_manage_and_upload_resume 内置「物料校验先于删除」防线，
    必须是猎聘生产代码中唯一的「上传+账号变更」路径——新增上传路径若绕过它，
    物料缺失事故（删了旧的、新的没传上）防线即被旁路。"""
    import re
    engine_dir = Path(__file__).resolve().parent.parent / "liepin_scraper"
    offenders = []
    for py in engine_dir.glob("*.py"):
        src = py.read_text(encoding="utf-8")
        for i, line in enumerate(src.split("\n"), 1):
            s = line.strip()
            if s.startswith("#") or s.startswith('"') or s.startswith("'"):
                continue
            if re.search(r"_upload_attachment_resume\s*\(|_ensure_resume_slots\s*\(|_delete_resume_card\s*\(", s):
                if py.name in ("liepin_attachment_uploader.py", "liepin_resume_manager.py"):
                    continue  # 入口/防线实现与模块内部调用所在文件
                offenders.append(f"{py.name}:{i}: {s}")
    assert not offenders, f"发现绕过上传入口的直调路径（物料防线会被旁路）: {offenders}"
    # 生产入口调用点收敛在 liepin_auto_delivery（deliver_job 主路径 + mass_apply 补传路径）
    lad_src = (engine_dir / "liepin_auto_delivery.py").read_text(encoding="utf-8")
    calls = re.findall(r"_manage_and_upload_resume\s*\(", lad_src)
    assert len(calls) == 2, f"生产入口调用点应为 2 处（主路径+补传路径），实际 {len(calls)}"


# ---------------- 1b. 2026-10 改版：弹窗驱动的上传流程 ----------------

class _FakeClock:
    """sleep 推进虚拟时钟，让 _wait_for_card 的 deadline 轮询在单测里零等待收敛"""

    def __init__(self):
        self.now = 0.0

    def time(self):
        return self.now

    def sleep(self, s):
        self.now += s


class _Modal:
    def __init__(self, page, text, close_sel=None, confirm_text=None):
        self._page = page
        self.text = text
        self._close_sel = close_sel
        self._confirm_text = confirm_text
        self.states = types.SimpleNamespace(is_displayed=True)
        self.confirmed = False

    def ele(self, sel, timeout=None):
        if self._close_sel and sel == self._close_sel:
            return types.SimpleNamespace(click=lambda by_js=False: self._page.close_modal(self))
        if self._confirm_text and sel == f"text:{self._confirm_text}":
            def _click():
                self.confirmed = True
            return types.SimpleNamespace(click=_click)
        return None


class _RevampedPage:
    """模拟改版后的附件页：导航到 editType=attachment 即弹出「上传附件简历」弹窗（含 file input），
    关闭弹窗销毁其 DOM；原生注入成功时卡片列表反应式追加。"""

    def __init__(self, cards, upload_succeeds=True):
        self.cards = list(cards)
        self.upload_succeeds = upload_succeeds
        self.modals = []
        self.urls = []
        self.refreshed = 0
        self.injected = []
        self.js_calls = []
        self.shots = []

    def open_upload_modal(self):
        if not any(getattr(m, "is_upload", False) for m in self.modals):
            m = _Modal(self, "上传附件简历 点击上传或将文件拖拽至此处", close_sel=liepin_resume_manager.CSS_ANT_MODAL_CLOSE)
            m.is_upload = True
            self.modals.append(m)

    def close_modal(self, modal):
        self.modals = [m for m in self.modals if m is not modal]

    @property
    def upload_modal_open(self):
        return any(getattr(m, "is_upload", False) for m in self.modals)

    def get(self, url):
        self.urls.append(url)
        if "editType=attachment" in url:
            self.open_upload_modal()

    def refresh(self):
        self.refreshed += 1

    def eles(self, sel, timeout=None):
        if sel == liepin_resume_manager.CSS_RESUME_CARD_CONTAINER:
            return list(self.cards)
        if sel == liepin_resume_manager.CSS_MODAL_CONTENT:
            return list(self.modals)
        return []

    def ele(self, sel, timeout=None):
        if sel == liepin_resume_manager.CSS_UPLOAD_FILE_INPUT and self.upload_modal_open:
            page = self

            class _Input:
                def input(self, path):
                    page.injected.append(path)
                    if page.upload_succeeds:
                        page.cards.append(_Card(Path(path).name))
            return _Input()
        return None

    def run_js(self, js):
        self.js_calls.append(js)
        return "no_input" if "customRequest" in js else None

    def get_screenshot(self, path):
        self.shots.append(path)


def _patch_upload_env(monkeypatch, tmp_path, page):
    # 上传执行链路在 liepin_attachment_uploader（2026-10-29 拆分）；卡片/槽位工具仍在 resume_manager
    monkeypatch.setattr(liepin_attachment_uploader, "time", _FakeClock())
    monkeypatch.setattr(liepin_resume_manager, "time", _FakeClock())
    monkeypatch.setattr(liepin_resume_manager, "page", page)
    monkeypatch.setattr(liepin_attachment_uploader, "TEMP_DIR", str(tmp_path / "temp_resumes"))
    monkeypatch.setattr(liepin_attachment_uploader, "writable_path", lambda default, sub: str(tmp_path / sub))
    import liepin_popups
    monkeypatch.setattr(liepin_popups, "page", page, raising=False)
    monkeypatch.setattr(liepin_popups, "_clear_liepin_annoying_popups", lambda p=None: None)
    src = tmp_path / "raw.pdf"
    src.write_bytes(b"%PDF-1.4 fake")
    return src


def test_upload_refuses_when_local_material_missing(monkeypatch, tmp_path):
    """本地物料缺失时必须在触碰账号前显式失败（真实事故防线）：
    绝不允许「删了旧附件、新的没传上」，也不用 assert（python -O 下会被移除）。"""
    page = _RevampedPage(cards=[_Card("我的简历.pdf")])
    _patch_upload_env(monkeypatch, tmp_path, page)  # 页面与账号状态就绪
    missing = tmp_path / "not_exist.pdf"

    with pytest.raises(RuntimeError, match="本地物料缺失"):
        liepin_attachment_uploader._upload_attachment_resume(str(missing), "某公司_某岗位")
    assert len(page.cards) == 1, "账号不得发生任何删除/变更"
    assert page.injected == [], "物料缺失时不得触发任何注入"


def test_material_guard_rejects_empty_file(monkeypatch, tmp_path):
    """空文件物料：三条防线分支之二，显式 raise。"""
    empty = tmp_path / "empty.pdf"
    empty.write_bytes(b"")
    with pytest.raises(RuntimeError, match="空文件"):
        liepin_attachment_uploader._assert_local_material_ready(str(empty))


def test_stage_copy_rejects_size_mismatch(monkeypatch, tmp_path):
    """副本大小不一致：三条防线分支之三。"""
    good = tmp_path / "good.pdf"
    good.write_bytes(b"%PDF-1.4 real-content")
    stage_dir = tmp_path / "temp_resumes" / "_liepin_upload_stage"
    stage_dir.mkdir(parents=True)
    staged = stage_dir / "X.pdf"
    staged.write_bytes(b"%PDF-1.4 truncated")  # 模拟复制不完整

    real_copy = liepin_attachment_uploader.shutil.copy2
    monkeypatch.setattr(liepin_attachment_uploader.shutil, "copy2",
                        lambda *a, **k: real_copy(*a, **k))
    # 让 copy2 产出大小不符的副本
    def _bad_copy(src, dst, *a, **k):
        Path(dst).write_bytes(b"%PDF-1.4 truncated")
    monkeypatch.setattr(liepin_attachment_uploader.shutil, "copy2", _bad_copy)
    monkeypatch.setattr(liepin_attachment_uploader, "TEMP_DIR", str(tmp_path / "temp_resumes"))

    with pytest.raises(RuntimeError, match="大小不一致"):
        liepin_attachment_uploader._stage_upload_copy(str(good), "X")


def test_manage_upload_checks_material_before_any_account_change(monkeypatch, tmp_path):
    """调用顺序契约（R3-P1-7）：_manage_and_upload_resume 必须在访问页面/删除槽位之前
    完成物料校验——物料缺失时 get/refresh/删除入口一律零调用。"""
    page = _RevampedPage(cards=[_Card("我的简历.pdf"), _Card("旧定制.pdf")])
    _patch_upload_env(monkeypatch, tmp_path, page)
    # 即使账号满槽（删除条件成立），物料缺失也必须先失败且零导航零删除
    page.cards.append(_Card("第三份.pdf"))
    missing = tmp_path / "not_exist.pdf"

    with pytest.raises(RuntimeError, match="本地物料缺失"):
        liepin_attachment_uploader._manage_and_upload_resume(str(missing), "某公司_某岗位")
    assert page.urls == [], "物料校验必须先于任何页面导航"
    assert page.refreshed == 0, "物料校验必须先于任何页面刷新"
    assert len(page.cards) == 3, "物料缺失时账号不得发生任何删除/变更"


def test_upload_opens_modal_via_url_and_injects_sanitized_filename(monkeypatch, tmp_path):
    """满槽改版页面没有任何上传按钮：必须靠 editType=attachment 导航弹出弹窗；
    原生注入用消毒后的文件名；成功后不得再走 Fiber 兜底；临时副本必须清理。"""
    page = _RevampedPage(cards=[_Card("我的简历.pdf"), _Card("旧定制.pdf")])
    src = _patch_upload_env(monkeypatch, tmp_path, page)

    liepin_attachment_uploader._upload_attachment_resume(str(src), "新奥集团_AI Agent 全栈工程师（FDE 方向）")

    assert any("editType=attachment" in u for u in page.urls), "未通过 URL 参数打开上传弹窗"
    assert len(page.injected) == 1
    assert Path(page.injected[0]).name == "新奥集团_AI_Agent_全栈工程师（.pdf"
    assert not Path(page.injected[0]).exists(), "上传后的临时副本未清理"
    assert not any("customRequest" in js for js in page.js_calls), "原生注入已成功，不得再触发 Fiber 兜底重复上传"
    assert [c.name for c in page.cards][-1] == "新奥集团_AI_Agent_全栈工程师（.pdf"


def test_upload_falls_back_to_fiber_then_fails_loudly_with_screenshot(monkeypatch, tmp_path):
    """原生注入未产生卡片 → 刷新复核仍无 → 才切 Fiber 兜底；兜底也无果时抛错并留截图，
    不得像改版前那样只留一行 `[]`。"""
    page = _RevampedPage(cards=[_Card("我的简历.pdf")], upload_succeeds=False)
    src = _patch_upload_env(monkeypatch, tmp_path, page)

    with pytest.raises(RuntimeError, match="卡片列表中未找到"):
        liepin_attachment_uploader._upload_attachment_resume(str(src), "某公司_某岗位")

    assert len(page.injected) == 1
    assert sum("customRequest" in js for js in page.js_calls) == 1, "Fiber 兜底应恰好执行一次"
    assert page.refreshed >= 1, "切兜底前必须先刷新看服务端真值，防止首路已成功时重复上传"
    assert page.shots and "upload_missing" in page.shots[0]


def test_close_upload_modal_only_touches_upload_modal():
    page = _RevampedPage(cards=[])
    page.open_upload_modal()
    other = _Modal(page, "确定要删除该附件简历吗？删除后不可恢复", close_sel=liepin_resume_manager.CSS_ANT_MODAL_CLOSE)
    page.modals.append(other)

    assert liepin_resume_manager._close_upload_modal_if_open(page) is True
    assert not page.upload_modal_open
    assert other in page.modals, "非上传弹窗不得被误关"
    assert liepin_resume_manager._close_upload_modal_if_open(page) is False


def test_confirm_delete_skips_upload_modal_and_confirms_delete_modal(monkeypatch):
    monkeypatch.setattr(liepin_resume_manager, "time", _FakeClock())
    page = _RevampedPage(cards=[])
    page.open_upload_modal()
    delete_modal = _Modal(page, "确定要删除该附件简历吗？", confirm_text="确 定")
    page.modals.append(delete_modal)
    monkeypatch.setattr(liepin_resume_manager, "page", page)

    assert liepin_resume_manager._confirm_delete_in_modal() is True
    assert delete_modal.confirmed
    assert page.upload_modal_open, "上传弹窗不得被当作删除确认弹窗操作"


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
    # 本用例只验证句柄重建逻辑；环境守卫会去探真实 9226 端口，宿主若跑着别的数据目录的猎聘 Edge 会被拒
    monkeypatch.setattr(liepin_session, "verify_browser_identity", lambda *a, **k: (True, ""))
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
