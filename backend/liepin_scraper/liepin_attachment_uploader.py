#!/usr/bin/env python3
"""猎聘附件简历上传执行模块（2026-10-29 自 liepin_resume_manager 拆分，控制单文件行数）。

核心职责：
- 打开「上传附件简历」弹窗（改版后满槽时 URL 参数 editType=attachment 是唯一入口）；
- input[type=file] 原生注入（CDP setFileInputFiles，走猎聘自身 beforeUpload → customRequest → onChange）；
- TDOSS 内存分块 Base64 + React Fiber 直调 customRequest/onChange 作降级兜底；
- 失败现场截图落盘 liepin_failure_shots/。

依赖方向：本模块 → liepin_resume_manager（命名/卡片/槽位/弹窗工具）→ liepin_session；严禁反向。
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

import liepin_popups
import liepin_resume_manager as _rm
from liepin_resume_manager import (
    TEMP_DIR,
    LIEPIN_ATTACHMENT_EDIT_URL,
    CSS_ANT_MODAL_CLOSE,
    CSS_RESUME_CARD_CONTAINER,
    CSS_UPLOAD_FILE_INPUT,
    _get_page,
    _sanitize_resume_title,
    _get_card_file_name,
    _close_upload_modal_if_open,
    _ensure_resume_slots,
)

# db_paths 阀门：dev 态逐字保持 backend/data 锚点，打包态落 JOBHUNTER_DATA_DIR
from app.core.db_paths import writable_path  # noqa: E402


def _save_failure_shot(p, tag: str):
    """失败现场截图留痕（DOM 改版/弹窗拦截时肉眼可回溯），落盘 liepin_failure_shots/。"""
    try:
        shot_dir = str(writable_path(
            os.path.join(_PROJECT_ROOT, "liepin_failure_shots"), "liepin_failure_shots"
        ))
        os.makedirs(shot_dir, exist_ok=True)
        safe_tag = re.sub(r'[\/\\:\*\?"<>\|\s]+', "_", (tag or "shot").strip())[:60] or "shot"
        path = os.path.join(shot_dir, f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{safe_tag}.png")
        p.get_screenshot(path=path)
        print(f"   📸 失败现场截图已保存: {path}")
    except Exception as e:
        print(f"   ⚠️ 失败截图保存异常（不影响流程）: {e}")


def _get_upload_btn():
    """旧版页面的「上传附件简历」入口按钮（改版后满槽时页面不再渲染任何上传按钮，仅作兜底）。"""
    p = _get_page()
    return (
        p.ele('css:div[data-testid="attachment-resume-add-btn"]', timeout=2)
        or p.ele('css:[data-testid="attachment-resume-add-btn"]', timeout=1)
        or p.ele('css:.resume-add-icon', timeout=1)
        or p.ele('css:span.ant-upload-btn, span.ant-c-upload-btn', timeout=1)
        or p.ele('css:.attachment-add-btn', timeout=1)
        or p.ele('css:.add-resume-btn', timeout=1)
        or p.ele('text:上传附件简历', timeout=2)
    )


def _upload_modal_file_input(p, timeout: float = 5):
    """上传弹窗内的 input[type=file]；弹窗关闭时 Ant Modal 会销毁其 DOM，找不到即弹窗未开。"""
    return p.ele(CSS_UPLOAD_FILE_INPUT, timeout=timeout)


def _open_upload_modal(p):
    """打开「上传附件简历」弹窗并返回其文件控件。

    改版后满槽时页面不渲染任何上传按钮，URL 参数 editType=attachment 是唯一稳定入口；
    关闭弹窗后猎聘会把 URL 改写成 editType=&editId=，因此必须重新导航而不是 refresh。
    页面若仍按旧版渲染了按钮，则点按钮兜底。
    """
    file_input = _upload_modal_file_input(p, timeout=1)
    if file_input:
        return file_input

    p.get(LIEPIN_ATTACHMENT_EDIT_URL)
    time.sleep(3)
    file_input = _upload_modal_file_input(p, timeout=5)
    if file_input:
        return file_input

    upload_btn = _get_upload_btn()
    if not upload_btn:
        return None
    try:
        upload_btn.scroll.to_see()
    except Exception:
        pass
    try:
        upload_btn.click(timeout=3)
    except Exception:
        upload_btn.click(by_js=True)
    time.sleep(2)
    return _upload_modal_file_input(p, timeout=5)


def _assert_local_material_ready(local_pdf_path: str) -> None:
    """不可逆删除动作（_ensure_resume_slots 可能删除账号内同名/最旧附件）执行前的物料守卫：
    物料缺失/空文件时宁可整单失败，绝不允许「删了旧的、新的没传上」。显式 raise，
    不用 assert（python -O 下会被移除）。在 _manage_and_upload_resume 入口调用，
    即任何账号变更发生之前。"""
    if not os.path.exists(local_pdf_path):
        raise RuntimeError(f"本地物料缺失，已中止上传（未对账号做任何变更）: {local_pdf_path}")
    if os.path.getsize(local_pdf_path) <= 0:
        raise RuntimeError(f"本地物料为空文件，已中止上传（未对账号做任何变更）: {local_pdf_path}")


def _stage_upload_copy(abs_path: str, upload_filename: str) -> str:
    """以消毒后的附件名复制临时副本：原生 input 注入时猎聘记录的附件名就是本地文件名。"""
    staged = os.path.join(str(TEMP_DIR), "_liepin_upload_stage", upload_filename)
    os.makedirs(os.path.dirname(staged), exist_ok=True)
    if os.path.abspath(staged) != abs_path:
        # 第二道防线：距入口校验已过若干秒，仍不信任文件系统状态
        _assert_local_material_ready(abs_path)
        shutil.copy2(abs_path, staged)
        if os.path.getsize(staged) != os.path.getsize(abs_path):
            raise RuntimeError(f"物料副本大小不一致，已中止上传: {staged}")
    return staged


def _card_names(p) -> list:
    return [name for name in (_get_card_file_name(c) for c in p.eles(CSS_RESUME_CARD_CONTAINER)) if name]


def _wait_for_card(p, short_name: str, timeout: float) -> list:
    """轮询等待新附件卡片出现（上传成功后列表由 React 状态直接刷新，无需整页 reload）。"""
    deadline = time.time() + timeout
    names = []
    while time.time() < deadline:
        names = _card_names(p)
        if any(short_name in n for n in names):
            return names
        time.sleep(1.5)
    return names


def _upload_via_react_fiber(p, abs_path: str, upload_filename: str) -> str:
    """降级路径：TDOSS 分块 Base64 注入 + 沿 React Fiber 直调 Ant Upload 的 customRequest/onChange。

    绕过了猎聘自身的 beforeUpload 校验，仅在原生 input 注入未产生卡片时使用。返回最终状态串。
    """
    with open(abs_path, "rb") as f:
        b64_data = base64.b64encode(f.read()).decode("utf-8")

    p.run_js("window.__b64_chunks = []; window.__save_status = '';")
    chunk_size = 100000
    for i in range(0, len(b64_data), chunk_size):
        chunk = b64_data[i:i + chunk_size]
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

        const input = document.querySelector(".ant-upload input[type=file]")
            || document.querySelector(".ant-c-upload input[type=file]")
            || document.querySelector("input[type=file]");
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
    print(f"   ℹ️ Fiber 直调启动结果: {res}")
    if res != "started":
        return str(res)

    status = ""
    for _ in range(35):
        time.sleep(1)
        status = p.run_js("return window.__save_status;") or ""
        if status == "ONCHANGE_TRIGGERED":
            time.sleep(6)
            break
        if "ERROR" in status:
            print(f"   ⚠️ TDOSS 上传报错: {status}")
            break
    return status or "timeout_without_status"


def _upload_attachment_resume(local_pdf_path: str, pdf_name: str):
    """打开上传弹窗 → 原生 input 注入 → 等卡片出现；未出现则 Fiber 直调兜底；最后整页刷新强校验。"""
    p = _get_page()
    abs_path = os.path.abspath(local_pdf_path)

    clean_title = _sanitize_resume_title(pdf_name)
    upload_filename = f"{clean_title}.pdf"
    short_name = clean_title[:8]

    file_input = _open_upload_modal(p)
    if not file_input:
        _save_failure_shot(p, f"no_upload_input_{clean_title}")
        raise RuntimeError("无法打开猎聘「上传附件简历」弹窗或弹窗内缺少文件控件，请核实页面是否再次改版")

    staged_path = _stage_upload_copy(abs_path, upload_filename)
    try:
        print(f"   ⏳ 正在通过上传弹窗文件控件原生注入: {upload_filename} ...")
        file_input.input(staged_path)

        # 三段式等待：反应式列表 → 关弹窗再看 → 整页刷新看服务端真值。
        # 只有刷新后仍不见卡片才切到 Fiber 兜底，避免首路已成功时重复上传撑爆槽位。
        names = _wait_for_card(p, short_name, timeout=20)
        matched = any(short_name in n for n in names)
        if not matched:
            _close_upload_modal_if_open(p)
            names = _wait_for_card(p, short_name, timeout=5)
            matched = any(short_name in n for n in names)
        if not matched:
            p.refresh()
            time.sleep(4)
            _close_upload_modal_if_open(p)
            names = _card_names(p)
            matched = any(short_name in n for n in names)
        print(f"   {'✅' if matched else '⚠️'} 原生注入后卡片列表: {names}")

        if not matched:
            print("   ⚠️ 原生注入后未见新卡片，切换 TDOSS/Fiber 直调兜底...")
            liepin_popups._clear_liepin_annoying_popups(p)
            file_input = _open_upload_modal(p)
            if file_input:
                status = _upload_via_react_fiber(p, abs_path, upload_filename)
                print(f"   ℹ️ Fiber 直调最终状态: {status}")
                names = _wait_for_card(p, short_name, timeout=20)
            else:
                print("   ⚠️ 兜底阶段仍无法打开上传弹窗")
    finally:
        try:
            os.remove(staged_path)
        except OSError:
            pass

    liepin_popups._clear_liepin_annoying_popups(p)

    # 整页刷新后以服务端渲染结果为准做最终强校验
    p.refresh()
    time.sleep(3)
    _close_upload_modal_if_open(p)
    card_names = _card_names(p)
    print(f"   📋 当前账号内生效的附件列表: {card_names}")

    if not any(short_name in name for name in card_names):
        _save_failure_shot(p, f"upload_missing_{clean_title}")
        raise RuntimeError(f"猎聘附件上传后卡片列表中未找到「{clean_title}」，生效列表为: {card_names}")

    print(f"   ✅ 简历「{upload_filename}」上传验证通过！")


def _manage_and_upload_resume(local_pdf_path: str, pdf_name: str, mass_apply: bool = False):
    """访问在线简历管理页 -> 清理旧简历 -> 上传新简历并强校验

    物料守卫置于本函数最前：后续 _ensure_resume_slots 会执行不可逆的账号附件删除，
    物料不就绪必须在任何账号变更发生之前失败。
    """
    _assert_local_material_ready(local_pdf_path)

    p = _get_page()
    print("   1. 正在访问猎聘在线简历管理页...")
    p.get(LIEPIN_ATTACHMENT_EDIT_URL)
    time.sleep(3)

    # 1. 关掉引导弹窗与进页即弹的「上传附件简历」弹窗——后者的遮罩会挡住卡片「⋯」入口，
    #    槽位管理必须在无遮罩状态下进行，上传阶段再由 _open_upload_modal 按需重开
    for _ in range(3):
        guide = p.ele('text:我知道了', timeout=1) or p.ele(CSS_ANT_MODAL_CLOSE, timeout=1)
        if guide:
            try:
                guide.click(by_js=True)
            except Exception:
                pass
            time.sleep(1)
        else:
            break
    _close_upload_modal_if_open(p)

    liepin_popups._handle_resume_sync_modals(p)
    liepin_popups._clear_interfering_modals(p)

    # 2. 检查槽位并执行汰旧换新
    _ensure_resume_slots(upload_name=pdf_name, mass_apply=mass_apply)

    # 3. 执行上传
    _upload_attachment_resume(local_pdf_path, pdf_name)
