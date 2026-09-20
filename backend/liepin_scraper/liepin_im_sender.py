#!/usr/bin/env python3
"""猎聘 IM 沟通与微聊投递模块。

核心职责：
- 直达岗位详情页唤起微聊会话窗口；
- 模拟用户真实输入发送个性化打招呼语；
- 简历浮层按时间倒序优先选择最新上传的有效简历附件；
- 触发立即投递并正向断言履约成功。
"""

import os
import sys
import time

# 双身份导入引导
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)
for _p in (_SCRIPT_DIR, _PROJECT_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import liepin_session
from liepin_resume_manager import _sanitize_resume_title, _is_generic_resume_title

# 模块级句柄，支持单测 monkeypatch 与运行时动态获取
page = None

# 猎聘浮层条目的上传日期展示格式（首选线上事实 YYYY-MM-DD，兼容历史 YYYY.MM.DD）
_UPLOAD_DATE_FMTS = ("%Y-%m-%d", "%Y.%m.%d")
_UPLOAD_DATE_FMT = _UPLOAD_DATE_FMTS[0]


def _is_uploaded_today(text: str) -> bool:
    """断言文本中是否包含今日上传日期（基于 _UPLOAD_DATE_FMTS 单一真理源比对）。"""
    if not text:
        return False
    return any(time.strftime(fmt) in text for fmt in _UPLOAD_DATE_FMTS)


def _get_page():
    if page is not None:
        return page
    return liepin_session.get_browser_page()


def _open_chat_box(job_url: str):
    # 强制将 http:// 升级为 https://，防止浏览器剥离 Secure Cookie
    if job_url.startswith("http://"):
        job_url = "https://" + job_url[7:]

    p = _get_page()
    p.get(job_url)
    time.sleep(3)

    chat_btn = (
        p.ele('css:a[data-selector="chat-chat"]', timeout=5)
        or p.ele("css:.btn-chat", timeout=2)
        or p.ele("text:聊一聊", timeout=2)
        or p.ele("text:继续聊", timeout=2)
        or p.ele("text:立即沟通", timeout=2)
    )
    if not chat_btn:
        raise RuntimeError(f"未找到「聊一聊/继续聊」按钮，可能岗位已下架，链接：{job_url}")

    chat_btn.click(by_js=True)
    print("   点击沟通按钮，等待聊天框浮出...")

    is_chat_box_visible = p.wait.ele_displayed("css:.im-ui-chat-container", timeout=6)
    if not is_chat_box_visible:
        chat_btn.click(by_js=True)
        p.wait.ele_displayed("css:.im-ui-chat-container", timeout=4)

    input_box = p.ele("css:.im-ui-textarea", timeout=5)
    if not input_box:
        raise RuntimeError("未找到聊天输入框，聊天面板未能成功弹出")
    return input_box


def _send_chat_message(input_box, greeting: str):
    input_box.click(by_js=True)
    input_box.input(greeting)
    time.sleep(1)

    p = _get_page()
    send_btn = p.ele("xpath://button/span[normalize-space()='发送']", timeout=5) or p.ele("css:.im-ui-basic-send-btn", timeout=2)
    if not send_btn:
        raise RuntimeError("未找到聊天发送按钮")

    send_btn.click(by_js=True)
    time.sleep(2)
    print("   ✅ 定制打招呼语已发送")


def _select_resume_in_modal(pdf_name: str, mass_apply: bool = False):
    """在简历发送浮层中精确选中目标简历。

    - 附件列表刷新慢：轮询等待目标名称出现（最多 4 次 × 3 秒）
    - 宁可中止也不发错：找不到目标名称直接抛错，绝不"默认发第一位"
    - 无论海投还是定制，均优先匹配实际传入的动态文件名（公司_岗位）
    - 日期断言优先于排序：浮层条目文本自带上传日期（如「2026-09-15 23:12上传」），
      多候选时只锁定今日上传条目；通用简历找不到今日条目宁可中止，绝不发历史旧版。
      猎聘浮层的排序方式无契约保证，"取第一位"只能作为定制简历无日期标记时的最后降级，
      不得作为"哪份最新"的判断依据。
    """
    clean_title = _sanitize_resume_title(pdf_name) if pdf_name else ""
    expected = clean_title[:8] if clean_title else "专属简历"
    is_generic = mass_apply or _is_generic_resume_title(pdf_name)
    today = time.strftime(_UPLOAD_DATE_FMT)

    def _item_text(item) -> str:
        try:
            return item.text or ""
        except Exception:
            return ""

    p = _get_page()
    p.wait.ele_displayed("css:.ant-im-modal-body", timeout=5)

    target = None
    for _try in range(4):
        candidates = p.eles(f"xpath://p[contains(text(), '{expected}')]/ancestor::label")
        if candidates:
            dated = [c for c in candidates if _is_uploaded_today(_item_text(c))]
            if dated:
                if len(candidates) > 1:
                    print(f"   ℹ️ 浮层中「{expected}」命中 {len(candidates)} 项，锁定今日({today})上传条目")
                target = dated[0]
                break
            if is_generic:
                print(f"   ⏳ 浮层中「{expected}」均非今日({today})上传，拒绝误发历史版本，等待刷新 ({_try + 1}/4)...")
                time.sleep(3)
                continue
            else:
                print(f"   ⚠️ 「{expected}」条目未见今日日期标记，定制简历按浮层首位降级选取")
                target = candidates[0]
                break
        if not is_generic:
            fallback = p.ele(f"text:{expected}", timeout=1)
            if fallback:
                target = fallback
                break

        print(f"   ⏳ 浮层未显示「{expected}」，等待列表刷新 ({_try + 1}/4)...")
        time.sleep(3)

    # 通用模糊兜底必须移出轮询：expected 四轮全失败才启用，且同样只认今日上传条目，
    # 防止目标卡片渲染慢时抢先选中账号内残留的旧版通用简历
    if target is None and is_generic:
        generic_candidates = (
            p.eles("xpath://p[contains(text(), '通用简历')]/ancestor::label")
            or p.eles("xpath://p[contains(text(), '我的简历')]/ancestor::label")
        )
        dated_generic = [c for c in generic_candidates if _is_uploaded_today(_item_text(c))]
        if dated_generic:
            print(f"   ℹ️ 通用模式兜底：未匹配到「{expected}」，锁定今日({today})上传的通用简历条目")
            target = dated_generic[0]

    if not target:
        # 白盒诊断：打印当前浮层所有可见条目的原始文本，供精准排查
        try:
            all_labels = p.eles("xpath://div[contains(@class, 'ant-im-modal-body')]//label") or p.eles("css:.ant-im-modal-body label")
            raw_texts = [_item_text(x).replace("\n", " ").strip() for x in all_labels if _item_text(x).strip()]
            print(f"   🔍 [浮层白盒诊断] 当前浮层条目文本({len(raw_texts)}项): {raw_texts}")
        except Exception as e:
            print(f"   ⚠️ [浮层白盒诊断] 提取条目文本异常: {e}")

        raise RuntimeError(
            f"[附件未送达] 发送浮层中未出现目标简历「{expected}」"
            + (f"（通用模式仅接受 {today} 上传的条目）" if is_generic else "")
            + "，中止发送以防发错简历"
        )

    target_desc = target.text.replace("\n", " | ").strip() if (hasattr(target, "text") and target.text) else expected
    target.click(by_js=True)
    time.sleep(1)
    print(f"   ✅ 已精确选中目标简历卡片: [{target_desc}]")


def _send_resume_in_chat(pdf_name: str, mass_apply: bool = False):
    p = _get_page()
    send_resume_btn = p.ele("css:.action-resume", timeout=5)
    if not send_resume_btn:
        raise RuntimeError("未找到聊天框顶部的「发简历」图标")

    send_resume_btn.click(by_js=True)
    time.sleep(2)

    _select_resume_in_modal(pdf_name, mass_apply=mass_apply)

    confirm_btn = p.ele("text:立即投递", timeout=5) or p.ele("xpath://button[contains(., '立即投递')]", timeout=3)
    if not confirm_btn:
        print("   ⚠️ 警告：未找到「立即投递」确认按钮")
    else:
        confirm_btn.click(by_js=True)
        time.sleep(2)
        print("   ✅ 专属简历附件已成功投递！")


def _chat_and_send_resume(
    job_url: str,
    greeting: str,
    pdf_name: str,
    mass_apply: bool = False,
    on_greeting_sent=None,
):
    """直达岗位页 -> 打招呼 -> 发简历闭环"""
    input_box = _open_chat_box(job_url)
    _send_chat_message(input_box, greeting)
    if callable(on_greeting_sent):
        on_greeting_sent()
    _send_resume_in_chat(pdf_name, mass_apply=mass_apply)
