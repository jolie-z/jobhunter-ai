#!/usr/bin/env python3
"""猎聘附件简历槽位与物料上传模块。

核心职责：
- 简历标题净化与通用简历标识判定；
- 3份上限槽位管控，旧定制简历安全淘汰；
- 通用简历【汰旧换新】机制：上传前先行清理历史版本，确保全账号唯一最新；
- 上传弹窗内 input[type=file] 原生注入（CDP setFileInputFiles，走猎聘自身
  beforeUpload → customRequest → onChange 全链路）；
- TDOSS 内存分块 Base64 + React Fiber 直调 customRequest/onChange 作降级兜底；
- 失败现场截图落盘 liepin_failure_shots/。
"""

import os
import sys
import time
import re
import base64
import shutil
from datetime import datetime

# 双身份导入引导
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)
for _p in (_SCRIPT_DIR, _PROJECT_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import liepin_session
import liepin_popups

# db_paths 阀门：dev 态逐字保持 backend/data 锚点，打包态落 JOBHUNTER_DATA_DIR
from app.core.db_paths import writable_path  # noqa: E402

TEMP_DIR = writable_path(os.path.join(_PROJECT_ROOT, "temp_resumes"), "temp_resumes")
LIEPIN_MAX_RESUMES = 3
LIEPIN_ATTACHMENT_EDIT_URL = "https://c.liepin.com/resume/edit?editType=attachment"

# 猎聘附件简历页 2026-10 改版：业务 class 全部变为 CSS Modules 哈希风格
# （attachmentCard--XzM2N / fileName--XzM2N / moreIcon--XzBkN，哈希随构建漂移，
# 只能按 `name--` 前缀匹配），Ant Design 组件前缀由 ant- 换成 ant-c-。
# 每个选择器都把改版前后的写法并列成一组，旧页面灰度/回滚时不至于再次失明。
# 卡片仍限定在附件主展示区（attachment-view-box / attachmentView--*）之内，
# 侧边栏的简历分析卡片不得被计入槽位。
CSS_ANT_MODAL_CLOSE = 'css:.ant-modal-close, .ant-c-modal-close'
CSS_MODAL_CONTENT = 'css:.ant-modal-content, .ant-c-modal-content'
CSS_RESUME_CARD_CONTAINER = (
    'css:.attachment-view-box .resume-card-container, '
    '[class*="attachmentView--"] [class*="attachmentCard--"]'
)
CSS_CARD_FILE_NAME = 'css:.file-name, [class*="fileName--"]'
CSS_CARD_MORE_ICON = 'css:.more-icon, [class*="moreIcon--"], .ant-c-dropdown-trigger'
CSS_DROPDOWN_MENU = 'css:.ant-dropdown-menu, .ant-c-dropdown-menu'
CSS_ANT_UPLOAD_DRAG = 'css:.ant-upload-drag, .ant-c-upload-drag'
CSS_UPLOAD_FILE_INPUT = 'css:.ant-upload input[type="file"], .ant-c-upload input[type="file"]'
UPLOAD_MODAL_TITLE = "上传附件简历"

# 模块级句柄，支持单测 monkeypatch 与运行时动态获取
page = None


def _get_page():
    if page is not None:
        return page
    return liepin_session.get_browser_page()


def _sanitize_resume_title(pdf_name: str) -> str:
    """猎聘附件名消毒：非法字符与空白转下划线并截断 20 字符"""
    return re.sub(r'[\/\\:\*\?"<>\|\s]+', '_', pdf_name).strip('_')[:20] or "专属定制简历"


def _is_generic_resume_title(file_name: str) -> bool:
    """判断简历文件名是否属于通用简历。

    只认规范标记（「通用简历」前缀 / 「通用版」 / 「我的简历」），不得用裸「通用」子串：
    「通用技术集团 / 通用汽车 / 通用电气」等真实雇主的定制简历会被误判成通用简历，
    导致汰旧换新误删账号内真正的通用简历，且该定制简历会被当成通用简历永久免于淘汰。
    """
    if not file_name:
        return False
    clean = file_name.strip()
    return clean.startswith("通用简历") or "通用版" in clean or "我的简历" in clean


def _get_card_file_name(item) -> str:
    """从卡片元素提取文件名文本"""
    if not item:
        return ""
    try:
        fn_ele = item.ele(CSS_CARD_FILE_NAME, timeout=1)
        return fn_ele.text.strip() if (fn_ele and fn_ele.text) else ""
    except Exception:
        return ""


def _close_upload_modal_if_open(p) -> bool:
    """关掉「上传附件简历」弹窗：editType=attachment 会在进页时自动弹出，
    遮罩挡住卡片「⋯」入口，槽位管理前必须关掉；上传时再按需重开。"""
    for modal in p.eles(CSS_MODAL_CONTENT):
        try:
            if not modal.states.is_displayed or UPLOAD_MODAL_TITLE not in (modal.text or ""):
                continue
            close_btn = modal.ele(CSS_ANT_MODAL_CLOSE, timeout=1)
            if not close_btn:
                continue
            close_btn.click(by_js=True)
            time.sleep(1)
            return True
        except Exception:
            continue
    return False


def _click_delete_in_dropdown_menu() -> bool:
    """在下拉菜单中点击删除"""
    p = _get_page()
    for menu in p.eles(CSS_DROPDOWN_MENU):
        if menu.states.is_displayed:
            del_btn = menu.ele("xpath:.//*[contains(text(), '删除')]", timeout=2)
            if del_btn:
                del_btn.click()
                return True
    return False


def _confirm_delete_in_modal() -> bool:
    """确认删除弹窗"""
    p = _get_page()
    for modal in p.eles(CSS_MODAL_CONTENT):
        if not modal.states.is_displayed:
            continue
        content_text = modal.text or ""
        # 改版后确认弹窗文案无契约保证，只要是带「删除」语义的可见弹窗即视为删除确认；
        # 「上传附件简历」弹窗同为 modal-content，必须排除，否则会误点它的关闭/其他按钮
        if UPLOAD_MODAL_TITLE in content_text:
            continue
        if not ("不可恢复" in content_text or "确定要删除" in content_text or "删除" in content_text):
            continue
        confirm = (
            modal.ele("text:确 定", timeout=2)
            or modal.ele("text:确定", timeout=1)
            or modal.ele("xpath:.//button[contains(., '删除')]", timeout=1)
            or modal.ele("css:.ant-btn-primary, .ant-c-btn-primary, .ant-c-btn-dangerous", timeout=1)
        )
        if confirm:
            confirm.click()
            print(f"   ✅ 已提交删除确认请求（弹窗文案: {content_text.strip()[:40]!r}）")
            time.sleep(2)
            return True
        print(f"   ⚠️ 删除确认弹窗已出现但未找到确认按钮（弹窗文案: {content_text.strip()[:60]!r}）")
    return False


def _delete_resume_card(target_item) -> bool:
    """安全删除单个简历卡片"""
    if not target_item:
        return False
    try:
        target_item.hover()
        time.sleep(0.5)
    except Exception:
        pass

    more_btn = target_item.ele(CSS_CARD_MORE_ICON, timeout=3)
    if not more_btn:
        print("   ⚠️ 目标卡片缺少「⋯」操作入口（.more-icon / moreIcon--*），无法删除")
        return False
    try:
        more_btn.click()
    except Exception:
        more_btn.click(by_js=True)
    time.sleep(1)

    if not _click_delete_in_dropdown_menu():
        print("   ⚠️ 未在可见菜单中找到“删除”选项")
        return False

    time.sleep(1.5)
    _confirm_delete_in_modal()
    return True


def _find_target_resume_to_delete(resume_items, is_uploading_generic: bool = False, upload_name: str = ""):
    """智能寻找最适宜删除的简历卡片。

    淘汰策略：
    1. 若指定 upload_name 且存在同名历史卡片：优先删除旧卡片执行覆盖更新。
    2. 若即将上传通用简历：优先清理历史旧版通用简历；无通用简历则淘汰最早上传的定制简历。
    3. 若上传定制简历：优先逆序淘汰最早上传的定制简历（非通用版），保护有效通用简历；
       若全部都是通用简历（历史脏数据）：安全降级删除列表最后一份（最旧简历）。
    """
    if not resume_items:
        return None

    if upload_name:
        clean_target = _sanitize_resume_title(upload_name)[:8]
        for item in reversed(resume_items):
            fn = _get_card_file_name(item)
            if clean_target in fn:
                print(f"   🎯 发现同名历史简历，锁定待清理目标: {fn}")
                return item

    if is_uploading_generic:
        for item in reversed(resume_items):
            fn = _get_card_file_name(item)
            if _is_generic_resume_title(fn):
                print(f"   🎯 通用简历汰旧换新，锁定待删除目标: {fn}")
                return item

    for item in reversed(resume_items):
        fn = _get_card_file_name(item)
        if not _is_generic_resume_title(fn):
            print(f"   🎯 锁定最旧定制简历待删除目标: {fn}")
            return item

    print("   ⚠️ 未找到非通用版简历，安全降级：删除列表最后一份（最旧简历）。")
    return resume_items[-1]


def _delete_oldest_resume(resume_items, is_uploading_generic: bool = False, upload_name: str = "") -> bool:
    """寻找合适目标卡片并执行删除清理；返回删除动作是否完整执行"""
    target_item = _find_target_resume_to_delete(resume_items, is_uploading_generic=is_uploading_generic, upload_name=upload_name)
    if not target_item:
        return False
    return _delete_resume_card(target_item)


def _ensure_resume_slots(upload_name: str = "", mass_apply: bool = False):
    """确保上传前有可用槽位，并执行通用简历汰旧换新"""
    p = _get_page()
    is_generic = mass_apply or _is_generic_resume_title(upload_name)
    resume_items = p.eles(CSS_RESUME_CARD_CONTAINER)
    count_before = len(resume_items)
    print(f"   当前附件简历数量：{count_before} (待上传: {upload_name or '默认'}, 通用模式: {is_generic})")

    # 1. 汰旧换新源头治理：上传通用简历前，逐一淘汰账号内所有历史通用简历。
    #    每轮重新查询卡片列表（删除会触发 Ant 列表重渲染，快照元素句柄会失效导致点击空转），
    #    并以重数复核删除结果——任何一张静默失败都会造成新旧通用并存误发，必须快速失败
    if is_generic and resume_items:
        for attempt in range(5):
            generic_cards = [
                item for item in p.eles(CSS_RESUME_CARD_CONTAINER)
                if _is_generic_resume_title(_get_card_file_name(item))
            ]
            if not generic_cards:
                break
            old_card = generic_cards[-1]  # 卡片按上传时间倒序，取末位（最旧）先汰换
            print(f"   🗑️ 正在汰换旧版通用简历({attempt + 1}/5): {_get_card_file_name(old_card) or '<未知名>'} ...")
            if not _delete_resume_card(old_card):
                print("   ⚠️ 本轮汰换未完成删除动作，清理干扰弹窗后重试...")
                liepin_popups._clear_interfering_modals(p)
            time.sleep(2)
            p.refresh()
            time.sleep(2.5)
            _close_upload_modal_if_open(p)

        leftover = [
            item for item in p.eles(CSS_RESUME_CARD_CONTAINER)
            if _is_generic_resume_title(_get_card_file_name(item))
        ]
        if leftover:
            names = [_get_card_file_name(item) or "<未知名>" for item in leftover]
            raise RuntimeError(
                f"通用简历汰旧换新失败：5 轮清理后仍残留 {len(leftover)} 份历史通用简历 {names}，"
                "中止本次投递以防新旧通用简历并存误发"
            )
        resume_items = p.eles(CSS_RESUME_CARD_CONTAINER)
        count_before = len(resume_items)
        print(f"   ✅ 汰旧换新完成，当前剩余附件数: {count_before}")

    # 2. 槽位上限管控：若已达上限 (3 份)，按淘汰策略删除 1 份腾出可用槽位
    if count_before < LIEPIN_MAX_RESUMES:
        return

    print(f"   ⚠️ 已达上限 ({LIEPIN_MAX_RESUMES} 份)，开始执行清理程序...")
    _delete_oldest_resume(resume_items, is_uploading_generic=is_generic, upload_name=upload_name)
    time.sleep(2)
    p.refresh()
    time.sleep(2.5)
    _close_upload_modal_if_open(p)

    if len(p.eles(CSS_RESUME_CARD_CONTAINER)) < count_before:
        return

    print("   ❌ 简历删除校验失败，尝试清理干扰弹窗后重试...")
    liepin_popups._clear_interfering_modals(p)
    current_items = p.eles(CSS_RESUME_CARD_CONTAINER)
    _delete_oldest_resume(current_items, is_uploading_generic=is_generic, upload_name=upload_name)
    time.sleep(2)
    p.refresh()
    time.sleep(2.5)
    _close_upload_modal_if_open(p)

    count_final = len(p.eles(CSS_RESUME_CARD_CONTAINER))
    if count_final >= count_before:
        raise RuntimeError(
            f"槽位清理失败：删除后仍有 {count_final} 份附件简历（删除前 {count_before} 份），中止本次投递"
        )
