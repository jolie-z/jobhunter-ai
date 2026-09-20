#!/usr/bin/env python3
"""猎聘附件简历槽位与物料上传模块。

核心职责：
- 简历标题净化与通用简历标识判定；
- 3份上限槽位管控，旧定制简历安全淘汰；
- 通用简历【汰旧换新】机制：上传前先行清理历史版本，确保全账号唯一最新；
- TDOSS 内存分块 Base64 上传与 React Fiber onChange 状态响应式同步；
- 幽灵 DOM 隐藏 input 注入降级兜底。
"""

import os
import sys
import time
import re
import base64

# 双身份导入引导
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)
for _p in (_SCRIPT_DIR, _PROJECT_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import liepin_session
import liepin_popups

TEMP_DIR = os.path.join(_PROJECT_ROOT, "temp_resumes")
LIEPIN_MAX_RESUMES = 3

CSS_ANT_MODAL_CLOSE = 'css:.ant-modal-close'
CSS_RESUME_CARD_CONTAINER = 'css:.attachment-view-box .resume-card-container'
CSS_ANT_UPLOAD_DRAG = 'css:.ant-upload-drag'

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
        fn_ele = item.ele("css:.file-name", timeout=1)
        return fn_ele.text.strip() if (fn_ele and fn_ele.text) else ""
    except Exception:
        return ""


def _click_delete_in_dropdown_menu() -> bool:
    """在下拉菜单中点击删除"""
    p = _get_page()
    for menu in p.eles("css:.ant-dropdown-menu"):
        if menu.states.is_displayed:
            del_btn = menu.ele("xpath:.//*[contains(text(), '删除')]", timeout=2)
            if del_btn:
                del_btn.click()
                return True
    return False


def _confirm_delete_in_modal() -> bool:
    """确认删除弹窗"""
    p = _get_page()
    for modal in p.eles("css:.ant-modal-content"):
        if modal.states.is_displayed:
            content_text = modal.text
            if "不可恢复" in content_text or "确定要删除" in content_text:
                confirm = modal.ele("text:确 定", timeout=2) or modal.ele("text:确定", timeout=2)
                if confirm:
                    confirm.click()
                    print("   ✅ 已提交删除确认请求")
                    time.sleep(2)
                    return True
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

    more_btn = target_item.ele("css:.more-icon", timeout=3)
    if not more_btn:
        print("   ⚠️ 目标卡片缺少 .more-icon 操作入口，无法删除")
        return False
    more_btn.click()
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

    if len(p.eles(CSS_RESUME_CARD_CONTAINER)) < count_before:
        return

    print("   ❌ 简历删除校验失败，尝试清理干扰弹窗后重试...")
    liepin_popups._clear_interfering_modals(p)
    current_items = p.eles(CSS_RESUME_CARD_CONTAINER)
    _delete_oldest_resume(current_items, is_uploading_generic=is_generic, upload_name=upload_name)
    time.sleep(2)
    p.refresh()
    time.sleep(2.5)

    count_final = len(p.eles(CSS_RESUME_CARD_CONTAINER))
    if count_final >= count_before:
        raise RuntimeError(
            f"槽位清理失败：删除后仍有 {count_final} 份附件简历（删除前 {count_before} 份），中止本次投递"
        )


def _get_upload_btn():
    p = _get_page()
    return (
        p.ele('css:div[data-testid="attachment-resume-add-btn"]', timeout=3)
        or p.ele('css:[data-testid="attachment-resume-add-btn"]', timeout=3)
        or p.ele('text:上传附件简历', timeout=2)
        or p.ele('css:.resume-add-icon', timeout=2)
        or p.ele('css:span.ant-upload-btn', timeout=2)
        or p.ele('css:.attachment-add-btn', timeout=1)
        or p.ele('css:.add-resume-btn', timeout=1)
    )


def _execute_hidden_input_injection(abs_path):
    p = _get_page()
    print("   ⚠️ 未找到「上传」按钮，尝试直接定位隐藏的 file input ...")
    hidden_input = p.ele('css:input[type="file"]', timeout=3)
    if hidden_input:
        try:
            hidden_input.input(abs_path)
            print("   ⏳ 已通过隐藏控件静默注入文件，等待页面响应...")
            time.sleep(5)
            liepin_popups._clear_liepin_annoying_popups(p)
            return
        except Exception as e:
            raise RuntimeError(f"隐藏 input 注入失败: {e}")
    raise RuntimeError("无法定位「+」号或「上传附件简历」按钮，请核实页面是否处于附件简历区域")


def _upload_attachment_resume(local_pdf_path: str, pdf_name: str):
    """穿透 UI 弹窗静默上传核心逻辑并严格验证入库 (支持 TDOSS 内存分块上传与 React 响应式同步)"""
    p = _get_page()
    abs_path = os.path.abspath(local_pdf_path)

    clean_title = _sanitize_resume_title(pdf_name)
    upload_filename = f"{clean_title}.pdf"

    upload_btn = _get_upload_btn()
    if not upload_btn:
        _execute_hidden_input_injection(abs_path)
        return

    try:
        upload_btn.scroll.to_see()
    except Exception:
        pass

    try:
        upload_btn.click(timeout=3)
    except Exception:
        upload_btn.click(by_js=True)

    time.sleep(2)
    liepin_popups._clear_liepin_annoying_popups(p)

    with open(abs_path, "rb") as f:
        b64_data = base64.b64encode(f.read()).decode("utf-8")

    # 分块注入 Base64 到浏览器
    p.run_js("window.__b64_chunks = [];")
    chunk_size = 100000
    for i in range(0, len(b64_data), chunk_size):
        chunk = b64_data[i:i+chunk_size]
        p.run_js(f"window.__b64_chunks.push(\"{chunk}\");")

    print(f"   ⏳ 正在通过 TDOSS 分块上传并触发 React 状态绑定: {upload_filename} ...")

    js_upload = f"""
    return (function() {{
        const fullB64 = window.__b64_chunks.join("");
        const binaryStr = atob(fullB64);
        const len = binaryStr.length;
        const bytes = new Uint8Array(len);
        for (let i = 0; i < len; i++) {{
            bytes[i] = binaryStr.charCodeAt(i);
        }}
        const blob = new Blob([bytes], {{ type: "application/pdf" }});
        const file = new File([blob], "{upload_filename}", {{ type: "application/pdf" }});

        const input = document.querySelector(".ant-upload input[type=file]") || document.querySelector("input[type=file]");
        if (!input) return "no_input";

        let curr = null;
        for (let k in input) {{
            if (k.startsWith("__reactInternalInstance") || k.startsWith("__reactFiber")) {{
                curr = input[k];
                break;
            }}
        }}

        let uploaderNode = null;
        let targetOnChange = null;
        while (curr) {{
            if (curr.stateNode && curr.stateNode.props && curr.stateNode.props.customRequest) {{
                uploaderNode = curr.stateNode;
            }}
            if (curr.memoizedProps && typeof curr.memoizedProps.onChange === "function" && curr.memoizedProps.customRequest) {{
                targetOnChange = curr.memoizedProps.onChange;
            }}
            curr = curr.return;
        }}

        if (!uploaderNode || !targetOnChange) return "uploader_comp_not_found";

        window.__save_status = "uploading";
        uploaderNode.props.customRequest({{
            file: file,
            onSuccess: function(response) {{
                window.__save_status = "TDOSS_DONE";
                try {{
                    targetOnChange({{
                        file: {{
                            uid: "rc-upload-" + Date.now(),
                            name: "{upload_filename}",
                            status: "done",
                            response: response,
                            percent: 100
                        }}
                    }});
                    window.__save_status = "ONCHANGE_TRIGGERED";
                }} catch(e) {{
                    window.__save_status = "ONCHANGE_ERROR: " + e.toString();
                }}
            }},
            onError: function(err) {{
                window.__save_status = "TDOSS_ERROR: " + err;
            }}
        }});
        return "started";
    }})();
    """

    res = p.run_js(js_upload)
    if res == "no_input" or res == "uploader_comp_not_found":
        # 降级尝试原生 input 注入
        fi = p.ele('css:input[type="file"]', timeout=3)
        if fi:
            fi.input(abs_path)
            time.sleep(6)
    else:
        # 等待上传完成与 React 响应式更新
        for _ in range(35):
            time.sleep(1)
            status = p.run_js("return window.__save_status;")
            if status == "ONCHANGE_TRIGGERED":
                time.sleep(6)
                break
            if status and "ERROR" in status:
                print(f"   ⚠️ TDOSS 上传报错: {status}")
                break

    liepin_popups._clear_liepin_annoying_popups(p)

    # 刷新并强校验卡片列表中是否真正出现了新上传的简历
    p.refresh()
    time.sleep(3)
    cards = p.eles(CSS_RESUME_CARD_CONTAINER)
    card_names = [_get_card_file_name(c) for c in cards if _get_card_file_name(c)]
    print(f"   📋 当前账号内生效的附件列表: {card_names}")

    short_name = clean_title[:8]
    matched = any(short_name in name for name in card_names)
    if not matched:
        raise RuntimeError(f"猎聘附件上传后卡片列表中未找到「{clean_title}」，生效列表为: {card_names}")

    print(f"   ✅ 简历「{upload_filename}」上传验证通过！")


def _manage_and_upload_resume(local_pdf_path: str, pdf_name: str, mass_apply: bool = False):
    """访问在线简历管理页 -> 清理旧简历 -> 上传新简历并强校验"""
    p = _get_page()
    print("   1. 正在访问猎聘在线简历管理页...")
    p.get("https://c.liepin.com/resume/edit?editType=attachment")
    time.sleep(3)

    # 1. 关掉可能出现的引导弹窗
    for _ in range(3):
        guide = p.ele('text:我知道了', timeout=1) or p.ele('css:.ant-modal-close', timeout=1)
        if guide:
            try:
                guide.click(by_js=True)
            except Exception:
                pass
            time.sleep(1)
        else:
            break

    liepin_popups._handle_resume_sync_modals(p)
    liepin_popups._clear_interfering_modals(p)

    # 2. 检查槽位并执行汰旧换新
    _ensure_resume_slots(upload_name=pdf_name, mass_apply=mass_apply)

    # 3. 执行上传
    _upload_attachment_resume(local_pdf_path, pdf_name)
