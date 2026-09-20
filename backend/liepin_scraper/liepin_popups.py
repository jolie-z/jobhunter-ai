#!/usr/bin/env python3
"""猎聘弹窗与引导层拦截器模块。

核心职责：
- 经历同步、是否更新在线简历、问卷调研、退出二次确认等全流程弹窗拦截清理；
- 页面干扰层检测与关闭（如“内容未保存”提示）；
- 首页广告/稍后更新引导弹窗安全清理。
"""

import os
import sys
import time
import random

# 双身份导入引导
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)
for _p in (_SCRIPT_DIR, _PROJECT_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import liepin_session

CSS_ANT_MODAL_CLOSE = 'css:.ant-modal-close'


def _resolve_page(page=None):
    if page is not None:
        return page
    return liepin_session.get_browser_page()


def _clear_interfering_modals(page=None):
    """检测并关闭干扰弹窗（如“内容未保存”提示）"""
    p = _resolve_page(page)
    for modal in p.eles("css:.ant-modal-content"):
        if modal.states.is_displayed:
            text = modal.text
            if "内容未保存" in text or "确定退出编辑" in text:
                print("   🧹 清理干扰弹窗：内容未保存提示")
                confirm_btn = modal.ele("text:确 定", timeout=2)
                if confirm_btn:
                    confirm_btn.click()
                    time.sleep(1)


def _handle_experience_sync_modal(page=None):
    """拦截进入在线简历时的【经历同步】弹窗"""
    p = _resolve_page(page)
    sync_title = p.ele('text:经历可同步至在线简历中', timeout=2)
    if sync_title:
        print("   🧹 拦截到【经历同步】弹窗，正在点击右上角「X」关闭...")
        close_btn = p.ele(CSS_ANT_MODAL_CLOSE, timeout=2)
        if close_btn:
            close_btn.click(by_js=True)
            time.sleep(1.5)


def _handle_online_resume_sync_modal(page=None):
    """拦截进入在线简历时的【是否更新在线简历】追问弹窗"""
    p = _resolve_page(page)
    exit_btn = p.ele('text:退出', timeout=2)
    if exit_btn and exit_btn.states.is_displayed:
        print("   🧹 拦截到【是否更新在线简历】弹窗，正在点击「退出同步」...")
        exit_btn.click(by_js=True)
        time.sleep(2)

        reason_label = p.ele('tag:label', timeout=3)
        if not reason_label:
            reason_label = p.ele('css:[type="radio"]', timeout=1)

        if reason_label:
            print("   🧹 拦截到【为何不更新】追问弹窗，正在自动勾选原因...")
            reason_label.click(by_js=True)
            time.sleep(1)

            confirm_btn = p.ele('text:确 定', timeout=2) or p.ele('text:确定', timeout=1) or p.ele('text:提交', timeout=1)
            if confirm_btn:
                confirm_btn.click(by_js=True)
                print("   ✅ 成功击破简历同步二连环弹窗！")
                time.sleep(2)


def _handle_resume_sync_modals(page=None):
    """专门处理进入简历页时，猎聘询问是否【更新/同步在线简历】的各类干扰弹窗"""
    p = _resolve_page(page)
    _handle_experience_sync_modal(p)
    _handle_online_resume_sync_modal(p)


def _clear_home_page_modals(page=None):
    """检测并清理首页拦截弹窗（只点击明确文案的安全按钮，绝不盲点通用关闭）"""
    p = _resolve_page(page)
    print("   🛡️ 正在检测并清理首页拦截弹窗...")
    try:
        update_later_btn = p.ele('text:稍后更新', timeout=2) or p.ele('text:暂不', timeout=1)
        if update_later_btn and update_later_btn.states.is_displayed:
            print("   🧹 发现【更新简历/广告】弹窗，正在点击「稍后更新」...")
            update_later_btn.click(by_js=True)
            time.sleep(1.5)
    except Exception as e:
        print(f"   ⚠️ 清理首页弹窗时发生小意外，忽略并继续前进: {e}")


def _handle_new_sync_modal(page=None):
    """处理新版【经历解析同步】弹窗"""
    p = _resolve_page(page)
    new_sync_modal = p.ele('text:经历可同步至在线简历中', timeout=2)
    if not new_sync_modal:
        return
    print("   🔕 检测到新版【经历解析同步】弹窗，直接点击右上角「X」关闭...")
    close_btn = p.ele(CSS_ANT_MODAL_CLOSE, timeout=2)
    if close_btn:
        close_btn.click(by_js=True)
    else:
        fallback_close = p.ele('css:[class*="close"]', timeout=1)
        if fallback_close:
            fallback_close.click(by_js=True)
    time.sleep(1.5)


def _handle_legacy_sync_modal(page=None):
    """处理旧版的“是否同步到在线简历”弹窗"""
    p = _resolve_page(page)
    cancel_sync = p.ele('text:暂不同步', timeout=2) or p.ele('text:取消同步', timeout=1) or p.ele('text:不需要', timeout=1)
    if not cancel_sync:
        return
    print("   🔕 检测到【同步在线简历】弹窗，点击拒绝...")
    cancel_sync.click(by_js=True)
    time.sleep(1.5)


def _handle_exit_reason_modal(page=None):
    """处理“请问你退出的原因是”问卷弹窗"""
    p = _resolve_page(page)
    reason_title = p.ele('text:请问你退出的原因是', timeout=2)
    if not reason_title:
        return
    print("   🔕 检测到【简历同步退出问卷】弹窗，正在随机选择原因...")
    try:
        options = ["解析效果不好", "在线简历中不想写太详细", "现在没时间确认，稍后同步"]
        choice = random.choice(options)
        option_ele = p.ele(f'text:{choice}', timeout=2)
        if option_ele:
            option_ele.click(by_js=True)
            time.sleep(0.5)

        submit_btn = p.ele('text:提交并退出', timeout=2)
        if submit_btn:
            submit_btn.click(by_js=True)
            print("   ✅ 已点击【提交并退出】")
        else:
            close_btn = p.ele(CSS_ANT_MODAL_CLOSE, timeout=1)
            if close_btn:
                close_btn.click(by_js=True)
    except Exception as e:
        print(f"   ⚠️ 处理问卷弹窗失败: {e}")
    time.sleep(1.5)


def _handle_exit_sync_confirmation(page=None):
    """处理“退出同步”二次确认弹窗"""
    p = _resolve_page(page)
    exit_sync_btn = p.ele('text:退出同步', timeout=2)
    if not exit_sync_btn:
        return
    print("   🔕 检测到【二次确认退出同步】弹窗，正在点击退出...")
    try:
        exit_sync_btn.click(by_js=True)
        print("   ✅ 已成功彻底退出同步流程")
    except Exception as e:
        print(f"   ⚠️ 点击退出同步失败: {e}")
    time.sleep(1.5)


def _clear_liepin_annoying_popups(page=None):
    """处理猎聘上传附件简历时的一连串恶心弹窗"""
    p = _resolve_page(page)
    print("   🛡️ 启动防干扰弹窗清理机制...")
    _handle_new_sync_modal(p)
    _handle_legacy_sync_modal(p)
    _handle_exit_reason_modal(p)
    _handle_exit_sync_confirmation(p)
