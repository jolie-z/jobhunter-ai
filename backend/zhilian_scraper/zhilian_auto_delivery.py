#!/usr/bin/env python3
"""
智联招聘 (Zhaopin) 全自动投递引擎

核心能力：
  1. 浏览器环境：使用 DrissionPage 接管 Edge，并固定 Profile 保持登录态。
  2. 飞书对接：拉取待投递岗位，下载专属 PDF 简历。
  3. 附件管理：
     - 进入简历页自动关闭干扰弹窗。
     - 检查满3份时自动 Hover 并在弹出的删除图标上点击删除旧简历。
     - 自动上传新附件，无需等待审核。
  4. 岗位投递：新标签页打开目标岗位，点击投递并精准匹配对应简历（弹窗内失配即中止，绝不兜底投错简历），检测投递成功。
  5. 状态回传：将投递结果写回飞书。
"""

import os
import re
import sys
import time
import random
import platform
from datetime import datetime
from DrissionPage import ChromiumPage, ChromiumOptions

# -------------------------------------------------------------
# 🛡️ DrissionPage 底层 CDP 查询防御补丁：
# DrissionPage 的 ChromiumBase._find_elements 在遇到页面异步渲染或 DOM 变动时，
# DOM.performSearch 返回异常可能导致内部未重置 num 计数，进而在后续循环读取
# result['searchId'] 时抛出未捕获的 KeyError('searchId')。
# 此处猴子补丁自动拦截 searchId 异常，执行小重试后回落为安全空元素，彻底避免崩溃击穿主业务。
# -------------------------------------------------------------
try:
    from DrissionPage._pages.chromium_base import ChromiumBase
    from DrissionPage._elements.none_element import NoneElement
    from DrissionPage._elements.chromium_element import ChromiumElementsList

    _orig_find_elements = ChromiumBase._find_elements

    def _safe_find_elements(self, locator, timeout, index=1, relative=False, raise_err=None):
        for attempt in range(4):
            try:
                return _orig_find_elements(self, locator, timeout, index=index, relative=relative, raise_err=raise_err)
            except KeyError as e:
                if "searchId" in str(e):
                    if attempt < 3:
                        time.sleep(0.25 * (attempt + 1))
                        continue
                    try:
                        return NoneElement(self) if index is not None else ChromiumElementsList(owner=self)
                    except Exception:
                        return NoneElement() if index is not None else ChromiumElementsList()
                raise

    ChromiumBase._find_elements = _safe_find_elements
except Exception as _patch_err:
    print(f"⚠️ DrissionPage 补丁注入警告: {_patch_err}")


# ==========================================
# 路径配置
# ==========================================
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_SCRIPT_DIR)
_PROJECT_ROOT = os.path.dirname(_BACKEND_DIR)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from app.services.feishu_service import update_feishu_record, get_jobs_to_deliver
from app.core.feishu_utils import download_feishu_file
from app.core.utils import is_valid_greeting

# ==========================================
# 全局常量
# ==========================================
TEMP_DIR = os.path.join(_PROJECT_ROOT, "temp_resumes")
ZHILIAN_HOME_URL = "https://www.zhaopin.com/"

# ==========================================
# 浏览器初始化
# ==========================================
def _get_edge_path():
    """跨平台获取 Edge 浏览器路径"""
    if platform.system() == "Darwin":
        mac_path = '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge'
        if os.path.exists(mac_path):
            return mac_path
    elif platform.system() == "Windows":
        for base in [os.environ.get("PROGRAMFILES", ""), os.environ.get("PROGRAMFILES(X86)", ""), os.environ.get("LOCALAPPDATA", "")]:
            candidate = os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe")
            if os.path.exists(candidate):
                return candidate
    return None


def _create_browser():
    """启动/连接带固定 Profile 的 Edge 浏览器，保持登录态"""
    print("🚀 连接 DrissionPage (Edge)...")
    from app.session.registry import get_profile_path, get_platform_port
    co = ChromiumOptions()
    port = get_platform_port("zhilian")
    co.set_address(f"127.0.0.1:{port}")

    # 🌟 使用全系统唯一统一 Profile（与简历回写、会话大盘、爬虫 100% 共享）
    profile_dir = get_profile_path("zhilian")
    os.makedirs(profile_dir, exist_ok=True)
    co.set_user_data_path(profile_dir)

    edge_path = _get_edge_path()
    if edge_path:
        co.set_browser_path(edge_path)

    page = ChromiumPage(addr_or_opts=co)
    return page


# 🌟 批次内常驻浏览器缓存：真人也不会每投一份简历就重启浏览器，
# 每岗冷启动 Edge 白烧 ~25-30 秒，批次内复用是纯收益且行为更接近人类
_shared_page = None


def _get_shared_browser():
    """获取批次内共享的常驻浏览器：进程内缓存 ChromiumPage，浏览器被外力杀掉/失联时自动重拉。"""
    global _shared_page
    if _shared_page is not None:
        try:
            _ = _shared_page.url  # 探活：浏览器进程已被杀/端口失联时会抛异常
            return _shared_page
        except Exception:
            print("   ⚠️ 常驻浏览器已失联，重新拉起...")
            try:
                _shared_page.quit()
            except Exception:
                pass
            _shared_page = None
    _shared_page = _create_browser()
    return _shared_page


def shutdown_shared_browser():
    """批次投递结束后由编排层统一关闭常驻浏览器（单岗位投递严禁调用）。"""
    global _shared_page
    if _shared_page is not None:
        try:
            _shared_page.quit()
            print("🧹 智联常驻浏览器已关闭")
        except Exception:
            pass
        _shared_page = None


def _safe_eles(tab, selector, timeout=3, retries=3):
    """元素列表安全查询：SPA 进页后异步重绘附件列表兜底，重试耗尽返回空列表而非抛异常崩溃"""
    for i in range(retries):
        try:
            return tab.eles(selector, timeout=timeout)
        except KeyError as e:
            if "searchId" not in str(e):
                raise
            time.sleep(0.3 + 0.2 * i)
        except Exception:
            return []
    return []


def _safe_ele(tab, selector, timeout=3, retries=3):
    """单元素安全查询：支持 searchId 抖动重试，重试耗尽返回 None 而非抛异常崩溃"""
    for i in range(retries):
        try:
            return tab.ele(selector, timeout=timeout)
        except KeyError as e:
            if "searchId" not in str(e):
                raise
            time.sleep(0.3 + 0.2 * i)
        except Exception:
            return None
    return None


def _is_logged_in(page) -> bool:
    """简历中心无登录元素且 URL 仍在 i.zhaopin.com 视为已登录"""
    target_tab = page
    try:
        # 如果是 ChromiumPage，优先使用指向 i.zhaopin.com 的 tab，杜绝被其他后台标签页（如岗位详情页）误导
        if hasattr(page, "get_tab"):
            t = page.get_tab(url="i.zhaopin.com")
            if t:
                target_tab = t
    except Exception:
        pass

    url = getattr(target_tab, "url", "") or getattr(page, "url", "") or ""
    if "passport.zhaopin.com" in url:
        return False
    if "i.zhaopin.com" not in url:
        # 尝试遍历查找是否有 i.zhaopin.com 的 tab
        found = False
        try:
            if hasattr(page, "tab_ids"):
                for tid in page.tab_ids:
                    t = page.get_tab(tid)
                    if "i.zhaopin.com" in (t.url or ""):
                        target_tab = t
                        url = t.url or ""
                        found = True
                        break
        except Exception:
            pass
        if not found:
            return False

    login = target_tab.ele('text:扫码登录', timeout=1) or target_tab.ele('text:手机号登录', timeout=1)
    return not login



def ensure_login(wait_s: int = 0) -> bool:
    """登录守卫：访问简历中心校验登录态；可选阻塞等扫码（CLI/测试场景）。

    wait_s=0（服务场景）：只检测不等待；未登录返回 False 由调用方决定失败处理。
    智联登录态靠持久化 Profile 保持，扫码/短信登录成功后自动存入 Profile。
    """
    page = _create_browser()
    try:
        page.get("https://i.zhaopin.com/resume")
        time.sleep(5)
        if _is_logged_in(page):
            print("   ✅ 智联登录态有效")
            return True
        if wait_s <= 0:
            print("   ❌ 智联未登录（不等待扫码）")
            return False
        print("=" * 64)
        print("   ⚠️  智联未登录！请在 9250 Edge 浏览器中扫码/短信登录")
        print(f"   ⏳ 登录成功后脚本自动继续，最长等待 {wait_s // 60} 分钟")
        print("=" * 64)
        t0 = time.time()
        while time.time() - t0 < wait_s:
            time.sleep(5)
            if _is_logged_in(page):
                print("   ✅ 登录成功，登录态已恢复！")
                return True
        return False
    finally:
        try:
            page.quit()
        except Exception:
            pass


# ==========================================
# 弹窗拦截
# ==========================================
def _kill_popups(tab, max_rounds=5):
    """关闭所有干扰弹窗（纯 JS 方式点击可见关闭/取消按钮，零 CDP performSearch 依赖，杜绝 searchId 崩溃）"""
    for _ in range(max_rounds):
        closed = False
        try:
            closed = bool(tab.run_js('''
                var n = 0;
                // 1. 常见干扰弹窗的显式关闭按钮
                document.querySelectorAll('.upload-to-confirm__close, .ivu-modal-close, .el-dialog__headerbtn, [aria-label="Close"]').forEach(function(e){
                    if (e.getBoundingClientRect().width > 0) { e.click(); n++; }
                });
                // 2. 干扰弹窗/引导弹窗中的取消按钮（排除删除确认等核心业务弹窗）
                document.querySelectorAll('.ivu-modal-wrap, .el-dialog__wrapper, .ivu-modal').forEach(function(m){
                    var s = window.getComputedStyle(m);
                    if (s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0') {
                        var text = m.innerText || '';
                        // 包含同步/建议/完善/提示文案的非业务弹窗才执行取消
                        if (text.indexOf('同步') >= 0 || text.indexOf('建议') >= 0 || text.indexOf('完善') >= 0 || text.indexOf('提示') >= 0) {
                            m.querySelectorAll('button, span, a').forEach(function(b){
                                var bt = (b.innerText || '').trim();
                                if ((bt === '取消' || bt === '暂不' || bt === '知道了') && b.getBoundingClientRect().width > 0) {
                                    b.click();
                                    n++;
                                }
                            });
                        }
                    }
                });
                return n > 0;
            '''))
        except Exception:
            closed = False
        if closed:
            time.sleep(0.5)
        else:
            break


def _delete_resume_item(tab, item_ele):
    """删除指定的简历 item 元素"""
    try:
        item_ele.run_js("this.dispatchEvent(new MouseEvent('mouseenter', {bubbles: true}));")
        time.sleep(1.5)

        li_ele = item_ele.parent('tag:li')
        del_icon = li_ele.ele('css:.parse-action-area__right__delete-icon', timeout=3)
        if not del_icon:
            tab.run_js('document.querySelectorAll(".ivu-poptip-popper").forEach(e => e.style.display = "block");')
            time.sleep(1)
            del_icon = li_ele.ele('css:.parse-action-area__right__delete-icon', timeout=2)

        if not del_icon or not del_icon.states.is_displayed:
            print("   ❌ 未找到删除图标")
            return False

        del_icon.click(by_js=True)
        time.sleep(2)

        # 在 .ivu-modal-wrap 容器内查找确认按钮
        clicked = tab.run_js('''
            var modals = document.querySelectorAll('.ivu-modal-wrap');
            for (var m of modals) {
                var s = window.getComputedStyle(m);
                if (s.display !== 'none' && s.visibility !== 'hidden') {
                    var btns = m.querySelectorAll('.ivu-btn-primary');
                    for (var b of btns) {
                        var r = b.getBoundingClientRect();
                        if (r.width > 0) { b.click(); return true; }
                    }
                }
            }
            return false;
        ''')
        if clicked:
            print("   ✅ 已确认删除简历")
            time.sleep(2)
            return True
        else:
            print("   ❌ 未找到删除确认按钮")
            return False
    except Exception as e:
        print(f"   ⚠️ 删除简历元素异常: {e}")
        return False


def _delete_oldest_resume(tab):
    """删除最旧的附件简历（槽位满时调用）"""
    print("   ⚠️ 简历槽位已满，尝试删除最旧的一份...")
    _kill_popups(tab)

    items = _safe_eles(tab, 'css:.parse-item')
    if not items or len(items) < 3:
        return
    _delete_resume_item(tab, items[-1])


def _delete_resume_by_name(tab, name="我的简历"):
    """按名称查找并删除指定的附件简历（用于海投批次前置清理历史同名旧简历）"""
    _kill_popups(tab)
    items = _safe_eles(tab, 'css:.parse-item')
    deleted = False
    for it in (items or []):
        if name in (it.text or ""):
            print(f"   🗑️ 发现历史「{name}」，执行前置清理删除...")
            if _delete_resume_item(tab, it):
                deleted = True
            time.sleep(1)
    return deleted


# ==========================================
# 简历槽位与上传
# ==========================================
def _upload_resume(page, local_pdf_path, pdf_name="我的简历", is_mass=False, batch_mass_uploaded=False, navigate=True):
    """
    进入简历中心并上传简历（支持精投专属上传与海投单次删旧传新+批次复用）
    navigate=False 时跳过进入简历中心的导航（调用方已停在 i.zhaopin.com/resume，省一轮加载+4s 死等）
    返回: (ok: bool, next_batch_mass_uploaded: bool, backend_resume_count: int)
    """
    for attempt in (1, 2):
        try:
            return _upload_resume_once(page, local_pdf_path, pdf_name, is_mass, batch_mass_uploaded,
                                       navigate=(navigate or attempt > 1))
        except Exception as e:
            if attempt == 1:
                print(f"   ⚠️ 简历上传第一轮异常 ({e})，刷新页面重试一次...")
                try:
                    page.latest_tab.refresh()
                except Exception:
                    pass
                time.sleep(3)
                continue
            raise
    return False, batch_mass_uploaded, 0


def _upload_resume_once(page, local_pdf_path, pdf_name="我的简历", is_mass=False, batch_mass_uploaded=False, navigate=True):
    # 🌟 核心优化：海投岗位在当次批次若已上传过「我的简历.pdf」，后续岗位100%直接复用，杜绝重复删传耗时
    if is_mass and batch_mass_uploaded:
        print(f"   ✅ [海投批次极速复用] 当次任务已上传最新海投简历「{pdf_name}」，直接复用无需访问后台删传！")
        return True, True, 0

    print(f"\n📤 准备检查/上传简历: {pdf_name} (模式: {'通用海投' if is_mass else '定制精投'})")

    if navigate:
        page.get("https://i.zhaopin.com/resume")
        time.sleep(4)

    tab = page.latest_tab
    _kill_popups(tab)

    if is_mass:
        # 海投首次进入：先清理历史同名的「我的简历.pdf」，避免残留上个任务或多天前的旧文件
        _delete_resume_by_name(tab, "我的简历")
        time.sleep(1)
    else:
        # 🌟 精投模式：同名专属简历一律删旧传新 —— 后台同名≠同内容（重新生成的定制稿、
        # 同公司同名不同岗位都会撞名），复用旧附件会让最新定制简历永远发不出去
        _delete_resume_by_name(tab, pdf_name)
        time.sleep(1)

    # 检查槽位数 (智联最多 3 份)
    resume_items = _safe_eles(tab, 'css:.parse-item')
    slot_count = len(resume_items) if resume_items else 0
    print(f"   📊 当前附件简历: {slot_count} / 3 份")

    if slot_count >= 3:
        _delete_oldest_resume(tab)
        time.sleep(1)

    # 上传新附件
    upload_btn = (
        tab.ele('text:上传新附件', timeout=3)
        or tab.ele('text:添加附件', timeout=2)
        or tab.ele('css:button.upload__button', timeout=2)
    )
    if not upload_btn:
        print("   ❌ 未找到【上传新附件】按钮")
        return False, batch_mass_uploaded, 0

    upload_btn.click()
    time.sleep(2)

    # 直接向 modal 中的 input[type=file] 注入本地文件路径
    file_input = tab.ele('css:input[type="file"]', timeout=3)
    if not file_input:
        print("   ❌ 未找到文件上传控件 (input[type=file])")
        return False, batch_mass_uploaded, 0

    file_input.input(local_pdf_path)
    time.sleep(3)

    # 点击"确定上传" → 完成上传
    confirm_btn = tab.ele('text:确定上传', timeout=5) or tab.ele('css:.ivu-btn-primary', timeout=3)
    if confirm_btn and confirm_btn.states.is_displayed:
        print(f"   ✅ 点击【确定上传】...")
        confirm_btn.click()
        time.sleep(4)

    # 🌟 上传解析等待：轮询确认新附件已出现在后台列表（最多 30 秒），规避「附件审核中不可选」竞态
    t0 = time.time()
    while True:
        _kill_popups(tab)
        items_now = _safe_eles(tab, 'css:.parse-item') or []
        if any(pdf_name in (it.text or "") for it in items_now):
            break
        if time.time() - t0 > 30:
            print(f"   ❌ [物料] 上传后 30 秒内未在简历后台看到「{pdf_name}」，附件可能解析失败")
            return False, (True if is_mass else batch_mass_uploaded), 0
        time.sleep(2)
    time.sleep(3)  # 解析宽限：附件出现 ≠ 解析渲染完成，留出缓冲

    slot_count = len(_safe_eles(tab, 'css:.parse-item') or [])
    _kill_popups(tab)
    print(f"   🎉 简历「{pdf_name}」上传流程完成！（后台附件 {slot_count} 份）")
    return True, (True if is_mass else batch_mass_uploaded), slot_count


# ==========================================
# 岗位投递
# ==========================================
def _classify_main_buttons(button_texts) -> str:
    """主操作区按钮状态分类（纯函数，便于单测）：
    - deliverable: 存在「立即投递/申请职位」，说明尚未完成投递，可执行附件投递
    - delivered:   明确的已投递态（已投递/继续申请/继续沟通/聊一聊/先聊聊等），说明附件已投过，可跳过投递直接进入微聊打招呼
    - unknown:     无法识别
    """
    texts = [(t or "").strip() for t in (button_texts or []) if (t or "").strip()]
    if any(t in ("立即投递", "申请职位") for t in texts):
        return "deliverable"
    if any(t in ("已投递", "继续申请", "继续沟通", "聊一聊", "与TA沟通", "先聊聊") for t in texts):
        return "delivered"
    return "unknown"


def _is_delivered_button_state(button_texts) -> bool:
    """投递后的正向断言：主操作区必须出现明确的已投递态按钮才算送达（空值/无法识别一律判失败）。"""
    return _classify_main_buttons(button_texts) == "delivered"


def _save_failure_shot(tab, tag: str):
    """失败现场截图留痕（DOM 改版/弹窗拦截时肉眼可回溯），落盘 zhilian_failure_shots/。"""
    try:
        shot_dir = os.path.join(_BACKEND_DIR, "zhilian_failure_shots")
        os.makedirs(shot_dir, exist_ok=True)
        safe_tag = re.sub(r'[\/\\:\*\?"<>\|\s]+', "_", (tag or "shot").strip())[:60] or "shot"
        path = os.path.join(shot_dir, f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{safe_tag}.png")
        tab.get_screenshot(path=path)
        print(f"   📸 失败现场截图已保存: {path}")
    except Exception as e:
        print(f"   ⚠️ 失败截图保存异常（不影响流程）: {e}")


def _deliver_to_job(
    page,
    job_url,
    pdf_name="我的简历",
    job_title="",
    company="",
    mass_apply=False,
    greeting="",
    backend_resume_count=0,
    retry_greeting_only=False,
    file_token="",
    local_pdf_path="",
):
    """
    在新标签打开岗位详情页并进行投递
    双动作闭环流程：
      动作一（附件投递）：主操作区定位「立即投递」→ 精准匹配附件简历 → 投递 → 正向断言送达；
      动作二（即时微聊）：点击「继续沟通/先聊聊」→ 捕获本次新开的微聊窗口 → 校验会话归属 → 发送打招呼语。
    返回: (deliver_ok: bool, greeting_sent: bool, error_msg: str)
    """
    if not local_pdf_path:
        local_pdf_path = os.path.join(TEMP_DIR, f"{pdf_name}.pdf")

    if job_url.startswith("http://"):
        job_url = "https://" + job_url[7:]

    tab = page.new_tab(job_url)
    time.sleep(4)

    # 检查登录状态
    login = tab.ele('text:扫码登录', timeout=2) or tab.ele('text:手机号登录', timeout=2)
    if login:
        err = "[登录] 主域未登录，需在 9250 端口浏览器中登录智联招聘"
        print(f"   ❌ {err}")
        _save_failure_shot(tab, f"login_{company}_{job_title}")
        tab.close()
        return False, False, err
    try:
        if tab.ele('css:.registers-guide__button', timeout=1):
            err = "[登录] 主域登录态失效：页面只渲染登录引导"
            print(f"   ❌ {err}")
            _save_failure_shot(tab, f"guide_{company}_{job_title}")
            tab.close()
            return False, False, err
    except Exception:
        pass

    # -------------------------------------------------------------
    # 动作一：立即投递 (附件简历)
    # -------------------------------------------------------------
    # 🌟 只读主操作区按钮，杜绝侧栏「相似职位」卡片同名文案干扰（修复：全页文本搜索曾把「已投递」误判跳过投递）
    def _read_main_buttons(timeout_s=1.0):
        texts = []
        try:
            for btn in tab.eles('css:.summary-planes__action button', timeout=timeout_s):
                t = (btn.text or "").strip()
                if t:
                    texts.append(t)
        except Exception:
            pass
        return texts

    main_texts = _read_main_buttons(3)
    if not main_texts:
        time.sleep(3)
        main_texts = _read_main_buttons(2)
    btn_state = _classify_main_buttons(main_texts)

    if btn_state == "unknown":
        # 仅当主操作区无按钮时才做全页失效关键词判定（岗位失效页没有操作区），
        # 避免侧栏卡片上的失效文案把当前岗位误判为已下架
        for dead_kw in ['职位已失效', '职位已下架', '已停止招聘', '该职位已关闭']:
            try:
                if tab.ele(f'text:{dead_kw}', timeout=1):
                    err = f"[下架] 岗位已失效（页面提示：{dead_kw}）"
                    print(f"   ❌ {err}")
                    tab.close()
                    return False, False, err
            except Exception:
                pass
        err = f"[状态] 主操作区未定位到投递按钮（现有按钮: {main_texts or '无'}），可能页面改版或渲染异常"
        print(f"   ❌ {err}")
        _save_failure_shot(tab, f"nobutton_{company}_{job_title}")
        tab.close()
        return False, False, err

    # 🌟 核心分流机制（完全契合智联业务现实）：
    # 1. 只有当主操作区确实无【立即投递/申请职位】，仅剩【继续沟通/已投递】等沟通类按钮 (btn_state == 'delivered')：
    # 说明该岗位此前已成功投递过附件简历！直接跳过动作一，直奔动作二点击【继续沟通】发送打招呼语！
    # 2. 如果外部指定微聊补发模式 (retry_greeting_only=True) 但主操作区状态并非 delivered（例如 deliverable 甚至是 unknown）：
    # 强制校正为执行附件投递！若此前因 retry_greeting_only 跳过下载导致本地 PDF 缺失，现场触发补下载，失败则响亮报错。
    if btn_state == "delivered":
        is_already_delivered = True
    elif retry_greeting_only:
        print(f"   ⚠️ [模式校正] 外部指定微聊补发模式，但主操作区状态为【{btn_state}】（{main_texts}）（非已投递），强制校正执行附件投递！")
        is_already_delivered = False
        if not os.path.exists(local_pdf_path):
            if file_token:
                print(f"   📥 [模式校正补料] 现场补下载简历物料: {local_pdf_path}")
                os.makedirs(TEMP_DIR, exist_ok=True)
                if not download_feishu_file(file_token, local_pdf_path):
                    err = "[物料] 模式校正后补下载简历附件失败，无法执行投递"
                    print(f"   ❌ {err}")
                    tab.close()
                    return False, False, err
            else:
                err = "[物料] 模式校正需重新投递附件，但缺少 PDF file_token 物料"
                print(f"   ❌ {err}")
                tab.close()
                return False, False, err
    else:
        is_already_delivered = False
    if is_already_delivered:
        print(f"   ℹ️ [附件已确认] 主操作区按钮为 {main_texts}（无【立即投递】，仅剩【继续沟通】等沟通按钮），判定附件简历此前已成功送达，跳过重复投递直奔微聊打招呼！")
    else:
        print("\n   [动作 1/2] 开始投递附件简历...")
        apply_btn = None
        for btn in tab.eles('css:.summary-planes__action button', timeout=2):
            if (btn.text or "").strip() in ("立即投递", "申请职位"):
                apply_btn = btn
                break
        if not apply_btn or not apply_btn.states.is_displayed:
            err = f"[状态] 主操作区按钮 {main_texts} 中未找到可点击的【立即投递】"
            print(f"   ❌ {err}")
            _save_failure_shot(tab, f"btnhidden_{company}_{job_title}")
            tab.close()
            return False, False, err

        print(f"   🖱️ 点击 [立即投递]...")
        apply_btn.click()
        time.sleep(2)

        # 轮询等待简历选择弹窗渲染（慢页面下弹窗可能延迟出现）；等待期间主按钮若变迁为已投递态，
        # 说明智联对单附件岗位做了静默直投
        resume_items = []
        t0 = time.time()
        while time.time() - t0 < 8:
            try:
                resume_items = tab.eles('css:.a-attachment-select__item', timeout=1) or []
            except Exception:
                resume_items = []
            if resume_items or _is_delivered_button_state(_read_main_buttons()):
                break
            time.sleep(0.5)

        if resume_items:
            target_kw = "我的简历" if mass_apply else pdf_name
            print(f"   🔍 发现简历选择弹窗（共 {len(resume_items)} 份），正在匹配「{target_kw}」...")
            selected = False
            for item in resume_items:
                item_text = item.text or ""
                if target_kw in item_text or (mass_apply and "我的简历" in item_text):
                    item.click()
                    selected = True
                    print(f"   ✅ 已精准选中目标简历: [{item_text[:35]}]")
                    break
            if not selected:
                # 🚫 失配即中止：投错简历无法撤回，绝不兜底选第一份
                listed = " | ".join([(it.text or "").strip()[:40] for it in resume_items[:5]])
                err_msg = f"[简历] 简历选择弹窗中未找到目标简历「{target_kw}」（弹窗附件: {listed}），为防投错简历已中止本次投递"
                print(f"   ❌ {err_msg}")
                _save_failure_shot(tab, f"mismatch_{company}_{job_title}")
                tab.close()
                return False, False, err_msg
            time.sleep(1)
        else:
            # 🚫 弹窗始终未渲染：单附件静默直投可接受（简历去向唯一）；
            # 多附件时默认选中无法验证，必须中止，杜绝把默认旧简历投出去
            if _is_delivered_button_state(_read_main_buttons()):
                if backend_resume_count >= 2:
                    print("   ⚠️ 弹窗未渲染但已发生静默直投，且后台存在多份附件，简历去向存疑，请人工核实！")
                else:
                    print("   ℹ️ 弹窗未渲染但主按钮已变为已投递态，判定为单附件静默直投成功")
            else:
                err_msg = f"[简历] 投递弹窗未渲染且无投递状态变迁（后台附件 {backend_resume_count} 份），无法确认简历去向，中止本次投递"
                print(f"   ❌ {err_msg}")
                _save_failure_shot(tab, f"nopopup_{company}_{job_title}")
                tab.close()
                return False, False, err_msg

        # 未发生静默直投时，点击"投递简历"确认按钮
        if not _is_delivered_button_state(_read_main_buttons()):
            confirm_btn = (
                tab.ele('css:.a-attachment-select__action-btn__delivery', timeout=2)
                or tab.ele('text:投递简历', timeout=2)
                or tab.ele('text:确认投递', timeout=2)
            )
            if confirm_btn and confirm_btn.states.is_displayed:
                print(f"   🖱️ 点击 [{confirm_btn.text}] 确认投递...")
                try:
                    confirm_btn.click()
                except Exception as e:
                    print(f"   ⚠️ 确认按钮点击异常: {str(e)[:60]}")
                time.sleep(3)
            else:
                err_msg = "[简历] 未能定位【投递简历】确认按钮，投递未执行，中止本次投递"
                print(f"   ❌ {err_msg}")
                _save_failure_shot(tab, f"noconfirm_{company}_{job_title}")
                tab.close()
                return False, False, err_msg

        # 🛡️ 投递结果断言 1：监听是否有风控/验证码/报错弹窗阻断
        # 1) 全局级严重风控关键词
        for err_kw in ["安全验证", "拖动滑块", "点击倒立文字", "滑动验证"]:
            try:
                err_ele = tab.ele(f"text:{err_kw}", timeout=0.5)
            except Exception:
                err_ele = None
            if err_ele and err_ele.states.is_displayed:
                err_msg = f"[风控] 智联投递被阻断: 页面检测到「{err_kw}」"
                print(f"   ❌ {err_msg}")
                _save_failure_shot(tab, f"blocked_{company}_{job_title}")
                tab.close()
                return False, False, err_msg

        # 2) 模态/弹窗级拦截关键词（如「不符合」、「申请次数已达上限」等）：
        # 必须限定在弹窗、对话框等浮层内，严禁在页面全域检索，防止把 JD 正文中的「不符合上述条件者请勿投递」误判为风控阻断！
        modal_kws = ["不符合", "申请次数已达上限", "该职位已关闭", "请完善简历", "验证码"]
        modal_selectors = '[class*="modal"], [class*="dialog"], [class*="popup"], [class*="message-box"], [class*="layer"], .a-modal, .el-message-box'
        try:
            modals = tab.eles(f'css:{modal_selectors}', timeout=1) or []
            for m in modals:
                if m.states.is_displayed:
                    m_txt = (m.text or "").strip()
                    # 避免匹配到超长外层容器（如页面级 layer 容器）
                    if not m_txt or len(m_txt) > 500:
                        continue
                    if "验证码登录" in m_txt:
                        continue
                    for kw in modal_kws:
                        if kw in m_txt:
                            err_msg = f"[风控] 智联投递被弹窗阻断: 检测到「{kw}」（弹窗内容: {m_txt[:40]}）"
                            print(f"   ❌ {err_msg}")
                            _save_failure_shot(tab, f"blocked_{company}_{job_title}")
                            tab.close()
                            return False, False, err_msg
        except Exception:
            pass

        # 关闭"知道了"等提示弹窗
        try:
            got_it = tab.ele('text:知道了', timeout=2)
            if got_it and got_it.states.is_displayed:
                got_it.click()
                time.sleep(1)
        except Exception:
            pass

        # 🛡️ 投递结果断言 2：正向断言——主按钮必须明确变迁为已投递态才算送达（严禁假阳性）
        time.sleep(2)
        final_texts = _read_main_buttons(2)
        if not _is_delivered_button_state(final_texts):
            err_msg = f"[状态] 投递后主操作区按钮为 [{final_texts or '未定位到按钮'}]，未出现已投递态变迁，判定为投递失败"
            print(f"   ❌ {err_msg}")
            _save_failure_shot(tab, f"notdelivered_{company}_{job_title}")
            tab.close()
            return False, False, err_msg

        print("   🎉 附件简历确认成功送达！")

    # -------------------------------------------------------------
    # 动作二：微聊即时打招呼
    # -------------------------------------------------------------
    greeting_sent = False
    print(f"\n   [动作 2/2] 开始发起微聊并发送专属打招呼语...")

    if greeting:
        # 🌟 投递完成后的稳态重入机制：
        # 投递完成时出现的成功浮层弹窗是瞬态组件，生命周期极短且易被 Vue 销毁（易抛 The element object is invalid）。
        # 若刚刚执行过动作一，确认送达后重新加载岗位详情页，浮层彻底消失，主操作区呈现常驻大按钮；
        # 若原本就已送达（is_already_delivered），当前页面已是稳态详情页，直接点击常驻按钮即可！
        if not is_already_delivered:
            print("   🔄 重新加载当前岗位详情页，获取稳态常驻微聊按钮...")
            try:
                tab.get(job_url)
                time.sleep(2)
                _kill_popups(tab)
            except Exception as e:
                print(f"   ⚠️ 页面重载轻微异常 (继续尝试定位按钮): {e}")

        # 在稳态页面主操作区定位【继续沟通 / 先聊聊】大按钮
        chat_btn = None
        for _round in range(3):
            try:
                for btn in tab.eles('css:.summary-planes__action button', timeout=1.5):
                    txt = (btn.text or "").strip()
                    if txt in ("继续沟通", "先聊聊", "聊一聊", "与TA沟通"):
                        chat_btn = btn
                        break
            except Exception:
                pass
            if not chat_btn:
                try:
                    chat_btn = tab.ele('css:.summary-planes__prechat', timeout=1)
                except Exception:
                    pass
            if not chat_btn:
                try:
                    chat_btn = tab.ele('text:继续沟通', timeout=1) or tab.ele('text:先聊聊', timeout=1)
                except Exception:
                    pass

            if chat_btn and chat_btn.states.is_displayed:
                break
            time.sleep(1)

        if not chat_btn:
            print("   ⚠️ 主操作区未捕获到【继续沟通 / 先聊聊】按钮，可能职位限制沟通或页面加载延迟")
        else:
            btn_txt = "继续沟通"
            try:
                btn_txt = (chat_btn.text or "").strip() or "继续沟通"
            except Exception:
                pass
            print(f"   💬 点击主操作区常驻微聊按钮 [{btn_txt}]，等待新微聊窗口响应...")
            try:
                # 🌟 先快照已有标签页（DrissionPage 4.x：ChromiumPage 无 .tabs，用 tab_ids/get_tab），
                # 只认「本次新开」的微聊窗口，杜绝把打招呼语打进历史会话
                before_ids = set(page.tab_ids)
                try:
                    chat_btn.click()
                except Exception:
                    chat_btn.click(by_js=True)  # 弹窗遮罩拦截原生点击时，用 JS 直点兜底

                # 轮询捕获本次新开的微聊 Tab (最多等待 8 秒)；若当前岗位标签页自身跳转为微聊页也接受
                chat_tab = None
                t0 = time.time()
                while time.time() - t0 < 8:
                    if "i.zhaopin.com/im" in (tab.url or ""):
                        chat_tab = tab
                        break
                    try:
                        for tid in page.tab_ids:
                            if tid in before_ids:
                                continue
                            t = page.get_tab(tid)
                            if "i.zhaopin.com/im" in (t.url or ""):
                                chat_tab = t
                                break
                    except Exception:
                        pass
                    if chat_tab:
                        break
                    time.sleep(0.5)

                if not chat_tab:
                    # 🚫 不再兜底抓取任意 zhaopin.com 标签页（历史微聊页/简历中心页都会中招）：
                    # 无法确认会话归属时宁可不发打招呼语，也不冒发错人的风险
                    print("   ⚠️ 未捕获到本次新开的微聊窗口 (i.zhaopin.com/im)，跳过打招呼（不影响附件投递结果）")
                elif company or job_title:
                    # 🌟 会话归属校验（三选一宽松匹配）：公司去后缀核心字号 / 公司全称 / 岗位名，
                    # 任一在微聊窗口命中即可发；三者都找不到仍坚决跳过，不拆防发错人的安全阀
                    probes = []
                    if company:
                        core = re.sub(r'股份有限公司|有限公司|有限责任公司|分公司|集团', '', company).strip()
                        if core and core != company:
                            probes.append(core)
                        probes.append(company)
                        # 🌟 进一步提纯核心品牌/字号（如 "中望软件" 提纯出 "中望"，防止 IM 窗口营业执照全称如 "广州中望龙腾..." 导致失配）
                        short_brand = re.sub(r'软件|技术|网络|科技|信息|咨询|电子|工业|国际|服务|实业', '', core).strip()
                        if len(short_brand) >= 2 and short_brand not in probes:
                            probes.append(short_brand)
                    if job_title:
                        probes.append(job_title)
                        # 🌟 岗位名去修饰括号提纯（如 "产品经理（CRM方向）" -> "产品经理"，防全半角及卡片修饰词失配）
                        pure_title = re.sub(r'[\(（].*?[\)）]', '', job_title).strip()
                        if len(pure_title) >= 2 and pure_title not in probes:
                            probes.append(pure_title)
                    owner_ok = False
                    for probe in probes:
                        try:
                            if chat_tab.ele(f'text:{probe}', timeout=2):
                                owner_ok = True
                                break
                        except Exception:
                            continue
                    if not owner_ok:
                        print(f"   ⚠️ 微聊窗口内未找到「{' / '.join(probes)[:60]}」，无法确认会话归属，跳过打招呼防发错人")
                        try:
                            chat_tab.close()
                        except Exception:
                            pass
                        chat_tab = None

                if chat_tab:
                    print(f"   💬 成功捕获微聊界面: {chat_tab.title} ({chat_tab.url})")
                    time.sleep(2)
                    # 结合真实智联 IM DOM: textarea.im-sender__input，Vue 响应式绑定
                    chat_input = (
                        chat_tab.ele('css:textarea.im-sender__input', timeout=3)
                        or chat_tab.ele('css:[placeholder*="开启对话"]', timeout=2)
                        or chat_tab.ele('css:textarea', timeout=2)
                    )
                    if chat_input:
                        print(f"   ✍️ 正在输入专属打招呼语 ({len(greeting)}字):\n「{greeting[:60]}...」")
                        # 🌟 关键：智联微聊采用 Vue 数据绑定，必须触发 input 与 change 事件以解除发送按钮的 disabled 状态
                        js_inject = """
                        const ta = document.querySelector("textarea.im-sender__input") || document.querySelector("textarea");
                        if (ta) {
                            ta.focus();
                            const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value")?.set;
                            if (setter) {
                                setter.call(ta, arguments[0]);
                            } else {
                                ta.value = arguments[0];
                            }
                            ta.dispatchEvent(new Event("input", { bubbles: true }));
                            ta.dispatchEvent(new Event("change", { bubbles: true }));
                            return true;
                        }
                        return false;
                        """
                        try:
                            chat_tab.run_js(js_inject, greeting)
                        except Exception as js_err:
                            print(f"   ⚠️ JS 注入异常，回退原生输入: {js_err}")
                            chat_input.input(greeting, clear=True)
                        time.sleep(1)

                        # 发送前记录输入框实际文本，作为后续清空校验的基准（严防初始为空时的假阳性）
                        pre_input_val = ""
                        try:
                            pre_input_val = (chat_tab.ele('css:textarea.im-sender__input', timeout=0.5).value or "").strip()
                        except Exception:
                            pass

                        # 发送按钮：定位 .im-sender__send-btn
                        send_btn = (
                            chat_tab.ele('css:button.im-sender__send-btn', timeout=2)
                            or chat_tab.ele('text:发送', timeout=1)
                        )
                        # 校验是否解锁 disabled，若未解锁则微调一次唤醒 Vue 响应式
                        if send_btn and send_btn.attr('disabled'):
                            try:
                                chat_tab.run_js("""
                                const ta = document.querySelector("textarea.im-sender__input") || document.querySelector("textarea");
                                if (ta) {
                                    ta.dispatchEvent(new Event("input", { bubbles: true }));
                                    ta.dispatchEvent(new Event("change", { bubbles: true }));
                                }
                                """)
                                time.sleep(0.5)
                            except Exception:
                                pass

                        # 执行发送点击
                        sent_clicked = False
                        if send_btn and send_btn.states.is_displayed:
                            try:
                                send_btn.click()
                                sent_clicked = True
                            except Exception:
                                try:
                                    send_btn.click(by_js=True)
                                    sent_clicked = True
                                except Exception:
                                    pass

                        if not sent_clicked:
                            # 键盘回车发送兜底
                            chat_tab.run_js("""
                            const ta = document.querySelector("textarea.im-sender__input") || document.querySelector("textarea");
                            if (ta) {
                                ta.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', keyCode: 13, code: 'Enter', which: 13, bubbles: true }));
                                ta.dispatchEvent(new KeyboardEvent('keypress', { key: 'Enter', keyCode: 13, code: 'Enter', which: 13, bubbles: true }));
                                ta.dispatchEvent(new KeyboardEvent('keyup', { key: 'Enter', keyCode: 13, code: 'Enter', which: 13, bubbles: true }));
                            }
                            """)

                        # 🌟 正向校验断言：杜绝假阳性虚报已送达！
                        # 成功特征：聊天流中出现招呼语关键词，或前置成功录入的文本在发送后被清空
                        verify_ok = False
                        probe_kw = greeting[:8].strip()
                        for _v in range(8):
                            time.sleep(0.5)
                            try:
                                has_msg = bool(chat_tab.ele(f'text:{probe_kw}', timeout=0.5)) if probe_kw else False
                                val = (chat_tab.ele('css:textarea.im-sender__input', timeout=0.5).value or "").strip()
                                # 杜绝假阳性：只有确认填入过内容且发送后被清空，或者消息上屏，才判为完全成功
                                if has_msg or (sent_clicked and pre_input_val and val == ""):
                                    verify_ok = True
                                    break
                            except Exception:
                                pass

                        if verify_ok:
                            greeting_sent = True
                            print("   🎉 智联在线微聊专属打招呼语发送成功，已通过正向送达断言！")
                            # 留足 3 秒缓冲给网络发包与 WebSocket 确认
                            time.sleep(3)
                        else:
                            print("   ⚠️ 打招呼语已输入并尝试发送，但未能确认内容上屏/输入框清空，标记为未送达")
                            greeting_sent = False
                    else:
                        print("   ⚠️ 微聊界面已打开，但未找到输入框")
                        greeting_sent = False
                    try:
                        chat_tab.close()
                    except Exception:
                        pass
            except Exception as e:
                print(f"   ⚠️ 微聊打招呼交互异常: {e}")

    try:
        tab.close()
    except Exception:
        pass
    return True, greeting_sent, ""


# ==========================================
# 完整工作流
# ==========================================
def deliver_job(job_data) -> bool:
    """
    投递单个岗位（全自动化无缝支持海投与精投分流）
    """
    import re
    record_id = job_data.get("record_id", "")
    job_url = job_data.get("job_url", "")
    file_token = job_data.get("file_token", "")
    job_title = (job_data.get("job_title") or "").strip()
    company = (job_data.get("company") or "").strip()
    mass_apply = bool(job_data.get("mass_apply", False))
    batch_mass_uploaded = bool(job_data.get("batch_mass_uploaded", False))
    greeting = (job_data.get("greeting") or "").strip()

    # 🌟 命名规范化：
    # 海投固定为「我的简历」；精投强制命名为「公司名_岗位名」（如 广州翰特_数字化产品经理）
    if mass_apply:
        target_resume_name = "我的简历"
    else:
        raw_name = (job_data.get("pdf_name") or f"{company}_{job_title}").replace('.pdf', '')
        target_resume_name = re.sub(r'[\/\\:\*\?"<>\|\s]+', '_', raw_name).strip('_') or "专属定制简历"

    # 打招呼语获取多重安全优先级
    if not greeting and mass_apply:
        try:
            from app.automation.db import get_autopilot_config
            cfg = get_autopilot_config()
            greeting = (cfg.get("mass_apply_greeting") or "").strip()
        except Exception:
            pass

    # 🚫 禁止 LLM 现场编造打招呼语：缺失时在下方主流程直接失败并标注原因。
    # 打招呼语只允许来自飞书「打招呼语」字段或人工配置的「海投通用打招呼语」。

    print(f"\n{'='*60}")
    print(f"📋 开始处理智联投递: {company} - {job_title}")
    print(f"   岗位链接: {job_url}")
    print(f"   投递物料名称: {target_resume_name}.pdf")
    print(f"   打招呼语模式: {'通用海投' if mass_apply else '定制精投'}")
    print(f"   打招呼语内容预览:\n「{greeting[:80]}...」")
    print(f"{'='*60}")

    local_pdf_path = os.path.join(TEMP_DIR, f"{target_resume_name}.pdf")
    page = None

    def _update_status(status, extra_fields=None) -> bool:
        if not record_id:
            print("   ⚠️ 无 record_id，跳过飞书状态更新")
            return False
        fields = {"跟进状态": status}
        if status == "已投递":
            now = datetime.now()
            fields["投递日期"] = int(now.timestamp() * 1000)
            fields["自动投递失败日志"] = ""
            print(f"   📝 更新飞书: 跟进状态 → {status}, 投递日期 → {now.strftime('%Y-%m-%d %H:%M')}")
        else:
            print(f"   📝 更新飞书: 跟进状态 → {status}")
        # 🌟 extra 最后合并：成功路径先把失败日志清空，再追加「已投递但打招呼语未送达」等真实回执，
        # 分两次写会被清空逻辑抹掉，必须随同一次更新落库
        if extra_fields:
            fields.update(extra_fields)
        ok = update_feishu_record(record_id, fields)
        if ok:
            print(f"   ✅ 飞书状态更新成功")
        else:
            print(f"   ❌ 飞书状态更新失败")
        return bool(ok)

    def _log_failure(error_msg):
        # 同步把结构化失败原因挂回 job_data，供 Tool 层透传给状态机写进「执行失败」台账
        job_data["delivery_error"] = str(error_msg)
        if record_id:
            update_feishu_record(record_id, {"自动投递失败日志": str(error_msg)[:120]})

    retry_greeting_only = bool(job_data.get("retry_greeting_only"))

    try:
        # 0. 打招呼语门禁：智联投递后需随微聊发送打招呼语，缺失/非法直接失败（不现场编造）
        if not greeting:
            hint = (
                "请前往「全链路中心-打招呼语模块」配置「海投通用打招呼语」后重试"
                if mass_apply
                else "该精投岗位缺少定制打招呼语，请在飞书「打招呼语」字段补填后重试"
            )
            err = f"[物料] 缺少打招呼语：智联投递需随微聊发送打招呼语，{hint}"
            print(f"   ❌ {err}")
            _log_failure(err)
            return False
        if not is_valid_greeting(greeting):
            err = f"[物料] 打招呼语为非法内容（疑似生成失败的错误文本），已拦截: {str(greeting)[:60]}，请人工修正飞书「打招呼语」后重试"
            print(f"   ❌ {err}")
            _log_failure(err)
            return False

        # 1. 下载 PDF 简历物料（若仅单独重试补发打招呼语，无需下载简历）
        from app.automation.abort import is_job_delivery_cancelled
        if is_job_delivery_cancelled(record_id):
            print(f"🛑 [智联] 物料准备前检测到岗位 {record_id} 已被用户终止，立即退出")
            _log_failure("[用户主动终止] 在指挥中心手动终止投递流程")
            return False

        if not retry_greeting_only:
            os.makedirs(TEMP_DIR, exist_ok=True)
            # 如果是海投且批次已上传过，无需再次下载物料
            if not (mass_apply and batch_mass_uploaded):
                print(f"\n📥 正在下载简历附件物料: {target_resume_name}.pdf")
                if not download_feishu_file(file_token, local_pdf_path):
                    _log_failure("[物料] 简历附件下载失败")
                    return False
                print(f"   ✅ 物料已就绪: {local_pdf_path}")
        else:
            print("\n🔄 [微聊补发模式] 该岗位附件简历此前已成功送达，跳过物料下载，直奔微聊打招呼...")

        if is_job_delivery_cancelled(record_id):
            print(f"🛑 [智联] 浏览器连接前检测到岗位 {record_id} 已被用户终止，立即退出")
            _log_failure("[用户主动终止] 在指挥中心手动终止投递流程")
            return False

        # 2. 连接/复用批次内常驻浏览器
        page = _get_shared_browser()

        try:
            from app.automation.delivery_interrupter import register_delivery_target, make_page_interrupt_fn
            register_delivery_target(record_id, make_page_interrupt_fn(lambda: page))
        except Exception:
            pass

        # 2.5 登录守卫：未登录直接失败
        page.get("https://i.zhaopin.com/resume")
        time.sleep(4)
        if not _is_logged_in(page):
            _log_failure("[登录] 智联登录态失效，请先在 9250 端口浏览器登录后重试")
            return False

        if is_job_delivery_cancelled(record_id):
            print(f"🛑 [智联] 简历上传前检测到岗位 {record_id} 已被用户终止，立即退出")
            _log_failure("[用户主动终止] 在指挥中心手动终止投递流程")
            return False

        # 3. 检查/上传附件简历至后台（若仅重试补发打招呼，跳过后台上传）
        backend_resume_count = 0

        if not retry_greeting_only:
            upload_ok, next_mass_uploaded, backend_resume_count = _upload_resume(
                page,
                local_pdf_path,
                pdf_name=target_resume_name,
                is_mass=mass_apply,
                batch_mass_uploaded=batch_mass_uploaded,
                navigate=False
            )
            job_data["batch_mass_uploaded"] = next_mass_uploaded
            if not upload_ok:
                _log_failure("[物料] 简历上传/检查失败")
                return False
        else:
            next_mass_uploaded = batch_mass_uploaded

        # 4. 投递岗位 + 微聊打招呼
        deliver_ok, greeting_sent, err_reason = _deliver_to_job(
            page,
            job_url,
            pdf_name=target_resume_name,
            job_title=job_title,
            company=company,
            mass_apply=mass_apply,
            greeting=greeting,
            backend_resume_count=backend_resume_count,
            retry_greeting_only=retry_greeting_only,
            file_token=file_token,
            local_pdf_path=local_pdf_path,
        )
        if not deliver_ok:
            _log_failure(err_reason or "[状态] 岗位投递/微聊发送失败")
            return False

        # 5. 二段式状态交付：
        # 只要 deliver_ok is True，表明附件简历已在招聘平台确认送达！
        # 必须无条件将飞书多维表格「跟进状态」变更为「已投递」（并写入投递时间），
        # 绝对杜绝状态停留在「待投递」导致定时波次重复发射！
        if not greeting_sent:
            fail_msg = "[微聊受阻] 附件简历已成功送达，打招呼语未成功发送"
            extra_fields = {"自动投递失败日志": f"{fail_msg}，请点击重试补发"}
            feishu_synced = _update_status("已投递", extra_fields)
            _log_failure(fail_msg)
            job_data["delivery_result"] = {
                "success": True,
                "greeting_sent": False,
                "partial": True,
                "batch_mass_uploaded": next_mass_uploaded,
                "feishu_synced": feishu_synced,
            }
            print(f"   ⚠️ {fail_msg}（飞书跟进状态已标记为「已投递」，异常已登记入台账供重试）")
            return False
        else:
            extra_fields = {"自动投递失败日志": ""}
            feishu_synced = _update_status("已投递", extra_fields)
            if not feishu_synced:
                print("   ⚠️ 投递已成功但飞书「跟进状态」同步失败：该岗位可能被波次重复发射（重复打招呼风险），请人工核对")
            job_data["delivery_result"] = {
                "success": True,
                "greeting_sent": True,
                "partial": False,
                "batch_mass_uploaded": next_mass_uploaded,
                "feishu_synced": feishu_synced,
            }
            print(f"\n🎉 智联投递与打招呼全链路圆满完成: {company} - {job_title}")
            return True
        
    except Exception as e:
        import traceback
        error_msg = f"[环境] 投递异常: {str(e)[:80]}"
        print(f"\n❌ {error_msg}")
        traceback.print_exc()
        _log_failure(error_msg)
        return False
        
    finally:
        try:
            from app.automation.delivery_interrupter import unregister_delivery_target
            unregister_delivery_target(record_id)
        except Exception:
            pass

        # 清理本地缓存
        if os.path.exists(local_pdf_path):
            try:
                os.remove(local_pdf_path)
            except OSError:
                pass

        # 🌟 浏览器不在此处退出：批次内常驻复用（每岗 quit 会白烧 ~25-30 秒冷启动），
        # 由编排层在整批结束后调用 shutdown_shared_browser() 统一收尾



def deliver_all_pending():
    print("🚀 智联招聘 (Zhaopin) 自动投递引擎启动\n")
    
    jobs = get_jobs_to_deliver(target_platform="智联招聘", target_status="待投递")
    if not jobs:
        print("📭 没有待投递的智联岗位")
        return
        
    print(f"📋 共 {len(jobs)} 个待投递岗位\n")
    
    success_count = 0
    fail_count = 0
    
    for i, job in enumerate(jobs):
        print(f"\n{'='*60}")
        print(f"📌 进度: [{i + 1}/{len(jobs)}]")
        print(f"{'='*60}")
        
        result = deliver_job(job)
        if result:
            success_count += 1
        else:
            fail_count += 1
            
        if i < len(jobs) - 1:
            wait = random.randint(30, 90)
            print(f"\n💤 等待 {wait} 秒后投递下一个岗位...")
            time.sleep(wait)
            
    print(f"\n{'='*60}")
    print(f"🏁 投递完成！成功: {success_count}, 失败: {fail_count}")
    print(f"{'='*60}")
    shutdown_shared_browser()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="智联招聘自动投递引擎")
    parser.add_argument('--all', action='store_true', help='投递所有待投递岗位')
    parser.add_argument('--url', type=str, help='指定单个岗位 URL')
    parser.add_argument('--pdf', type=str, help='指定本地 PDF 路径')
    args = parser.parse_args()
    
    if args.all:
        deliver_all_pending()
    elif args.url and args.pdf:
        job_data = {
            "record_id": "",
            "job_url": args.url,
            "file_token": "",
            "pdf_name": os.path.basename(args.pdf).replace('.pdf', ''),
        }
        deliver_job(job_data)
    else:
        print("用法:")
        print("  python zhilian_auto_delivery.py --all          # 投递所有待投递岗位")
        print("  python zhilian_auto_delivery.py --url URL --pdf PATH  # 投递单个岗位")
