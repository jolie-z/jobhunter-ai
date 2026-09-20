#!/usr/bin/env python3
"""猎聘网全自动投递引擎 (门面与主编排器)。

架构设计：
- 本模块作为猎聘自动化链路的统一入口与门面 (Facade)；
- 全量 re-export 子模块符号，保持对外部调用方 (workflow / tools / editor) 100% 零破坏兼容；
- 核心逻辑已拆分至：
    - liepin_session: 浏览器常驻管理、探活自愈、Cookie 与登录态检测
    - liepin_popups: 弹窗与引导层拦截清理
    - liepin_resume_manager: 简历标题消毒、槽位控制、通用简历汰旧换新与 TDOSS 分块上传
    - liepin_im_sender: IM 沟通打招呼、时间倒序选简历与投递确认
"""

import os
import sys
import time
import shutil

# 双身份导入引导
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)
for _p in (_SCRIPT_DIR, _PROJECT_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from app.core.config import settings
from app.services.feishu_service import get_job_record_from_feishu, update_feishu_record
from app.core.feishu_utils import download_feishu_file, extract_feishu_text

# 1. 会话与基础层导出
from liepin_session import (
    COOKIE_FILE,
    LIEPIN_HOME_URL,
    _port,
    _LIEPIN_PROFILE,
    _co,
    ChromiumPage,
    ChromiumOptions,
    get_browser_page,
    check_login_status,
    _inject_cookies_if_needed,
    save_current_cookies,
    ensure_login,
)

# 懒加载句柄：模块级默认为 None
page = None

# 2. 弹窗清理层导出
from liepin_popups import (
    CSS_ANT_MODAL_CLOSE,
    _clear_interfering_modals,
    _handle_experience_sync_modal,
    _handle_online_resume_sync_modal,
    _handle_resume_sync_modals,
    _clear_home_page_modals,
    _handle_new_sync_modal,
    _handle_legacy_sync_modal,
    _handle_exit_reason_modal,
    _handle_exit_sync_confirmation,
    _clear_liepin_annoying_popups,
)

# 3. 简历管理层导出
from liepin_resume_manager import (
    TEMP_DIR,
    LIEPIN_MAX_RESUMES,
    CSS_RESUME_CARD_CONTAINER,
    CSS_ANT_UPLOAD_DRAG,
    _sanitize_resume_title,
    _is_generic_resume_title,
    _get_card_file_name,
    _click_delete_in_dropdown_menu,
    _confirm_delete_in_modal,
    _delete_resume_card,
    _find_target_resume_to_delete,
    _delete_oldest_resume,
    _ensure_resume_slots,
    _get_upload_btn,
    _execute_hidden_input_injection,
    _upload_attachment_resume,
    _manage_and_upload_resume,
)

# 4. IM 微聊层导出
from liepin_im_sender import (
    _open_chat_box,
    _send_chat_message,
    _send_resume_in_chat,
    _chat_and_send_resume,
    _select_resume_in_modal,
)

__all__ = [
    # 常量
    "COOKIE_FILE", "LIEPIN_HOME_URL", "_port", "_LIEPIN_PROFILE", "_co",
    "TEMP_DIR", "LIEPIN_MAX_RESUMES", "CSS_ANT_MODAL_CLOSE",
    "CSS_RESUME_CARD_CONTAINER", "CSS_ANT_UPLOAD_DRAG",
    # 类与句柄
    "ChromiumPage", "ChromiumOptions", "page",
    # 会话
    "get_browser_page", "check_login_status", "_inject_cookies_if_needed",
    "save_current_cookies", "ensure_login",
    # 弹窗
    "_clear_interfering_modals", "_handle_experience_sync_modal",
    "_handle_online_resume_sync_modal", "_handle_resume_sync_modals",
    "_clear_home_page_modals", "_handle_new_sync_modal",
    "_handle_legacy_sync_modal", "_handle_exit_reason_modal",
    "_handle_exit_sync_confirmation", "_clear_liepin_annoying_popups",
    # 简历
    "_sanitize_resume_title", "_is_generic_resume_title", "_get_card_file_name",
    "_click_delete_in_dropdown_menu", "_confirm_delete_in_modal",
    "_delete_resume_card", "_find_target_resume_to_delete",
    "_delete_oldest_resume", "_ensure_resume_slots", "_get_upload_btn",
    "_execute_hidden_input_injection", "_upload_attachment_resume",
    "_manage_and_upload_resume",
    # IM
    "_open_chat_box", "_send_chat_message", "_send_resume_in_chat",
    "_chat_and_send_resume", "_select_resume_in_modal",
    # 门面主入口
    "deliver_job",
]


def deliver_job(job_data: dict) -> bool:
    """全链路执行引擎入口。

    job_data 可选参数:
        - temp_pdf_name: "公司_岗位.pdf" (默认 None，使用原配置名)
        - retry_greeting_only: True 时为微聊补发模式，仅唤起聊天窗口重发打招呼语，
          跳过 PDF 下载与槽位上传（仅对「已投递」记录生效，否则降级为完整投递）
    """
    job_url = job_data.get("job_url", "")
    file_token = job_data.get("file_token", "")
    pdf_name = job_data.get("pdf_name", "resume")
    greeting = job_data.get("greeting", "")
    record_id = job_data.get("record_id", "")
    mass_apply = bool(job_data.get("mass_apply", False))
    temp_pdf_name = job_data.get("temp_pdf_name")
    retry_greeting_only = bool(job_data.get("retry_greeting_only", False))
    # 阶段标记：失败时据此判断"打招呼已送达但附件未送达"，统一补 [附件未送达] 标签供台账定向建议
    job_data["greeting_sent"] = False
    attachment_sent = False

    pdf_filename = f"{pdf_name}.pdf"
    local_pdf_path = os.path.join(TEMP_DIR, pdf_filename)
    renamed_pdf_path: str | None = None
    os.makedirs(TEMP_DIR, exist_ok=True)

    def _update_status(status: str, keep_deliver_date: bool = False):
        if record_id:
            update_fields = {"跟进状态": status}
            if status == "已投递":
                # 成功即清空历史失败日志（对齐 BOSS/智联/51job 口径），否则登录态失效等
                # 旧账会残留在已投递记录上，把真实送达的打招呼语误判成「未送达」
                update_fields["自动投递失败日志"] = ""
                if not keep_deliver_date:
                    update_fields["投递日期"] = int(time.time() * 1000)
            update_feishu_record(record_id, update_fields)

    def _log_failure(error_msg: str, full_error: str | None = None):
        err_str = full_error if full_error is not None else str(error_msg)
        job_data["delivery_error"] = err_str  # 保留未截断原文，供上游精确分诊与决策
        if record_id:
            update_feishu_record(record_id, {"自动投递失败日志": str(error_msg)[:120]})

    def _record_follow_status() -> str:
        if not record_id:
            return ""
        try:
            rec = get_job_record_from_feishu(record_id, settings.FEISHU_TABLE_ID_JOBS)
            return extract_feishu_text((rec or {}).get("fields", {}).get("跟进状态", "")) or ""
        except Exception as e:
            print(f"[{pdf_name}]   ⚠️ 读取飞书跟进状态异常：{e}")
            return ""

    try:
        from app.automation.delivery_interrupter import register_delivery_target, make_page_interrupt_fn
        register_delivery_target(record_id, make_page_interrupt_fn(get_browser_page))
    except Exception:
        pass

    # 登录守卫：未登录直接失败，避免硬闯登录页产生晦涩 DOM 错误
    if not ensure_login(wait_s=0):
        _log_failure("[登录] 猎聘登录态失效，请先在 9226 端口浏览器登录后重试")
        return False

    from app.automation.abort import is_job_delivery_cancelled
    if is_job_delivery_cancelled(record_id):
        print(f"[{pdf_name}] 🛑 投递前检测到岗位 {record_id} 已被用户终止，立即退出")
        _log_failure("[用户主动终止] 在指挥中心手动终止投递流程")
        return False

    # 补发防呆：只有已投递记录才允许「只补打招呼」，否则附件根本没投出去，必须走完整投递
    if retry_greeting_only:
        follow_status = _record_follow_status()
        if follow_status != "已投递":
            print(f"[{pdf_name}]   ⚠️ 跟进状态为「{follow_status or '未知'}」并非已投递，降级为完整投递")
            retry_greeting_only = False

    if retry_greeting_only:
        if not greeting or not greeting.strip():
            _log_failure("[微聊受阻] 补发打招呼失败：打招呼语为空")
            return False
        print(f"\n[{pdf_name}] ▶ 微聊补发 | 仅重发打招呼语，跳过 PDF 下载与槽位上传 ...")
        try:
            input_box = _open_chat_box(job_url)
            _send_chat_message(input_box, greeting)
        except Exception as exc:
            full_err = str(exc)
            err_msg = f"补发打招呼异常：{full_err}"
            print(f"[{pdf_name}] ❌ {err_msg}")
            # 带 [微聊受阻] 结构化标记落库：台账据此点亮「打招呼未送达」并保留一键补发入口
            _log_failure(f"[微聊受阻] {err_msg}", full_error=full_err)
            return False
        _update_status("已投递", keep_deliver_date=True)
        print(f"[{pdf_name}] 🎉 打招呼语补发完成！")
        return True

    try:
        print(f"\n[{pdf_name}] ▶ A. 飞书数据联动 | 下载专属 PDF ...")
        if not os.path.exists(local_pdf_path) and file_token:
            ok = download_feishu_file(file_token, local_pdf_path)
            if not ok or not os.path.exists(local_pdf_path):
                _log_failure("[物料] 简历下载失败")
                return False
        elif not os.path.exists(local_pdf_path) and not file_token:
            _log_failure("[物料] 缺少简历附件 token 且本地无缓存")
            return False
        print(f"[{pdf_name}] ✅ PDF 准备就绪：{local_pdf_path}")

        if is_job_delivery_cancelled(record_id):
            print(f"[{pdf_name}] 🛑 物料就绪后检测到岗位 {record_id} 已被用户终止，立即退出")
            _log_failure("[用户主动终止] 在指挥中心手动终止投递流程")
            return False

        # 动态命名模式：重命名 PDF，投递时使用新文件名
        final_pdf_name = temp_pdf_name or pdf_name
        renamed_pdf_path = os.path.join(TEMP_DIR, f"{final_pdf_name}.pdf")
        if temp_pdf_name and os.path.exists(local_pdf_path) and renamed_pdf_path != local_pdf_path:
            shutil.copy2(local_pdf_path, renamed_pdf_path)
            print(f"[{pdf_name}] 📝 动态重命名为：{final_pdf_name}")

        upload_pdf_path = renamed_pdf_path if (temp_pdf_name and os.path.exists(renamed_pdf_path)) else local_pdf_path
        upload_name = final_pdf_name

        print(f"[{pdf_name}] ▶ B. 突破限制 | 清理槽位与简历上传 ...")
        _manage_and_upload_resume(upload_pdf_path, upload_name, mass_apply=mass_apply)

        if is_job_delivery_cancelled(record_id):
            print(f"[{pdf_name}] 🛑 简历上传后检测到岗位 {record_id} 已被用户终止，立即退出")
            _log_failure("[用户主动终止] 在指挥中心手动终止投递流程")
            return False

        print(f"[{pdf_name}] ▶ C. 主动出击 | 发起沟通并投递附件 ...")
        try:
            _chat_and_send_resume(
                job_url,
                greeting,
                final_pdf_name if temp_pdf_name else pdf_name,
                mass_apply=mass_apply,
                on_greeting_sent=lambda: job_data.update({"greeting_sent": True}),
            )
            attachment_sent = True
        except RuntimeError as e:
            if mass_apply and "中止发送" in str(e):
                print(f"[{pdf_name}]   ⚠️ 专属附件缺失，执行一次补传后仅补发简历...")
                _manage_and_upload_resume(upload_pdf_path, upload_name, mass_apply=mass_apply)
                _open_chat_box(job_url)
                _send_resume_in_chat(upload_name, mass_apply=mass_apply)
                attachment_sent = True
            else:
                raise

        _update_status("已投递")
        print(f"[{pdf_name}] 🎉 本次全自动投递任务圆满结束！")
        return True

    except Exception as exc:
        full_err = str(exc)
        if job_data.get("greeting_sent") and not attachment_sent and "[附件未送达]" not in full_err:
            # 浮层匹配失败之外的附件阶段异常（如未找到「发简历」图标）同样是"打招呼已送达、附件未送达"，
            # 补齐标签后台账才会给出"补发附件"建议而非整单重投
            full_err = f"[附件未送达] {full_err}"
        err_msg = f"投递异常中断：{full_err}"
        print(f"[{pdf_name}] ❌ {err_msg}")
        _log_failure(err_msg, full_error=full_err)
        return False

    finally:
        try:
            from app.automation.delivery_interrupter import unregister_delivery_target
            unregister_delivery_target(record_id)
        except Exception:
            pass

        # 清理本地缓存
        if temp_pdf_name and renamed_pdf_path and os.path.exists(renamed_pdf_path):
            try:
                os.remove(renamed_pdf_path)
                print(f"[{pdf_name}] 🗑 已删除临时重命名文件：{final_pdf_name}")
            except OSError as e:
                print(f"[{pdf_name}] ⚠️ 临时文件擦除失败：{e}")
        if not temp_pdf_name and os.path.exists(local_pdf_path):
            try:
                os.remove(local_pdf_path)
                print(f"[{pdf_name}] 🗑 本地缓存已安全擦除")
            except OSError as e:
                print(f"[{pdf_name}] ⚠️ 缓存擦除失败：{e}")