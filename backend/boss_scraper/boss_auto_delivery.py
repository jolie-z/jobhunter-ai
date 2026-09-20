"""
BOSS直聘全自动投递引擎 (物理隔离与鲁棒状态机版)
核心能力：物理隔离免Cookie指纹异常；自适应多版本进入聊天室；长图自动压缩与防抖上传；已下线岗位智能识别与自愈。
"""

import os
import sys
import time
import random
import subprocess
from datetime import datetime

# ==========================================
# 路径配置
# ==========================================
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# 🌟 干净利落引入新的服务层
from app.services.feishu_service import update_feishu_record
# 🌟 我们需要补充一个新的下载功能
from app.core.feishu_utils import download_feishu_file

from DrissionPage import ChromiumPage, ChromiumOptions

from engine_guard import EngineGuardError, verify_browser_identity

BOSS_HOME_URL = "https://www.zhipin.com/"
TEMP_DIR = os.path.join(_PROJECT_ROOT, "temp_resumes")
# 🌟 核心突破：创建一个专门存储 BOSS 浏览器状态的物理隔离文件夹
PROFILE_DIR = os.path.join(_PROJECT_ROOT, "data", "profiles", "boss")
os.makedirs(PROFILE_DIR, exist_ok=True)

# ==========================================
# 浏览器初始化（配置本地持久化环境）
# ==========================================
_co = ChromiumOptions()
# 🌟 统一端口：19222 (对齐 registry.py)
BOSS_DEBUG_PORT = 19222
_co.set_local_port(BOSS_DEBUG_PORT)

# 指定 Edge 浏览器
edge_path = "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"
if os.path.exists(edge_path):
    _co.set_browser_path(edge_path)

_co.set_user_data_path(PROFILE_DIR)
# 抹除自动化特征
_co.set_argument('--disable-blink-features=AutomationControlled')
_co.set_argument('--disable-dev-shm-usage')
_co.set_argument('--disable-gpu')
_co.set_pref('credentials_enable_service', False)

_page = None

def get_browser_page():
    """安全地获取或重启 BOSS 专属 Edge 浏览器实例，严禁全局误杀其他平台 Edge"""
    global _page
    if _page is not None:
        try:
            if not _page.is_stopped:
                return _page
        except Exception:
            pass

    # 🛡️ 环境守卫（Q24）：端口占用者身份校验——非本引擎 profile 拉起的浏览器绝不附着
    ok, guard_reason = verify_browser_identity(BOSS_DEBUG_PORT, PROFILE_DIR, platform="boss")
    if not ok:
        raise EngineGuardError(f"BOSS 引擎环境守卫拒绝连接浏览器：{guard_reason}")

    # 清理当前 Profile 下的 SingletonLock 锁文件
    lock_file = os.path.join(PROFILE_DIR, 'SingletonLock')
    if os.path.exists(lock_file):
        try:
            os.remove(lock_file)
            print("   🧹 已清理 BOSS 残留的浏览器锁定文件...")
        except Exception:
            pass

    try:
        _page = ChromiumPage(_co)
        return _page
    except Exception as e:
        print(f"   ⚠️ BOSS 浏览器连接重试（{e}）...")
        time.sleep(1)
        if os.path.exists(lock_file):
            try:
                os.remove(lock_file)
            except Exception:
                pass
        _page = ChromiumPage(_co)
        return _page

# 未登录等待窗口（秒）：超时后按失败处理，不再无限挂起（无人值守安全阀）
_LOGIN_WAIT_S = int(os.environ.get("BOSS_LOGIN_WAIT_S", "300"))

def _ensure_login() -> bool:
    """检查登录状态；未登录则等待用户扫码，超时返回 False（不再无限挂起）"""
    global page
    print("   🔄 正在检查 BOSS 直聘登录状态...")
    time.sleep(2)  # 给浏览器留出初始化时间，防止 Disconnected
    time.sleep(1)
    try:
        page.get(BOSS_HOME_URL)
    except Exception as e:
        print(f"   ⚠️ 浏览器连接异常（{e}），正在重建连接...")
        page = get_browser_page()
        page.get(BOSS_HOME_URL)
    time.sleep(3)

    # 检查页面上是否存在用户头像或退出按钮，判断是否登录
    is_logged_in = page.ele('css:.user-nav', timeout=2) or page.ele('text:退出登录', timeout=2)

    if is_logged_in:
        print("   ✅ 已检测到有效的登录态，可以开始投递！")
        return True

    print("\n⚠️ 未检测到登录状态！")
    print("👉 请在弹出的浏览器窗口中，使用 BOSS 直聘 APP 扫描二维码登录。")
    print(f"⏳ 最多等待 {_LOGIN_WAIT_S} 秒，超时后本次操作按失败处理…")

    deadline = time.monotonic() + _LOGIN_WAIT_S
    while time.monotonic() < deadline:
        time.sleep(3)
        if page.ele('css:.user-nav', timeout=1) or page.ele('text:退出登录', timeout=1):
            print("\n🎉 检测到扫码成功！登录凭证已永久保存在本地物理目录。")
            print("🚀 继续执行自动化投递...\n")
            time.sleep(2)
            return True

    print(f"❌ 等待登录超时（{_LOGIN_WAIT_S} 秒），放弃本次 BOSS 操作")
    return False

def _handle_security_captcha():
    """处理 BOSS 安全滑块"""
    captcha_ele = page.ele('css:#nc_1_n1z', timeout=2)
    if not captcha_ele:
        captcha_ele = page.ele('text:安全验证', timeout=1)

    if captcha_ele:
        print("\n⚠️ 触发了 BOSS 安全验证！")
        print("⏳ 脚本已暂停，请在浏览器中【手动拖动滑块】...")
        page.wait.ele_deleted('css:#nc_1_n1z', timeout=60)
        print("✅ 验证通过，继续执行！\n")
        time.sleep(2)

def _enter_chat_room(immediate_btn, continue_btn):
    """处理进入聊天室的各种分支（立即沟通/继续沟通）与弹窗，自适应支持新旧版本 BOSS 直聘"""
    global page, _page
    # ── 2A. 分支 A：发现「立即沟通」→ 点击激活 ──
    if immediate_btn:
        print("   🟢 检测到新岗位（立即沟通），执行激活流程...")
        immediate_btn.click(by_js=True)
        time.sleep(2)
        _handle_security_captcha()

        # 🌟 路径 1：现代 BOSS 直聘点击立即沟通后，直接新开了聊天标签页
        if len(_page.tab_ids) > 1:
            page = _page.get_tab(_page.latest_tab)
            if "chat" in page.url or page.ele('css:#chat-input', timeout=2):
                print(f"   💬 已直接通过新标签页进入聊天室: {page.url}")
                page.wait.load_start()
                return

        # 🌟 路径 2：当前页面直接跳转到了聊天室
        if "chat" in page.url or page.ele('css:#chat-input', timeout=2):
            print(f"   💬 当前页面已直接跳转至聊天室: {page.url}")
            return

        # 🌟 路径 3：老版 BOSS，留在详情页弹窗打招呼，需要关闭弹窗再点「继续沟通」
        modal_close = page.ele('css:.ant-modal-close', timeout=2) or page.ele('css:.close-container', timeout=1)
        if modal_close:
            modal_close.click(by_js=True)
            print("   🔕 已关闭干扰弹窗")
            time.sleep(1.5)

        continue_btn = page.ele('text:继续沟通', timeout=5)
        if not continue_btn:
            # 兜底：再次探测是否已打开聊天 Tab
            if len(_page.tab_ids) > 1:
                page = _page.get_tab(_page.latest_tab)
                return
            raise RuntimeError(
                f"点击「立即沟通」后未进入聊天室且未出现「继续沟通」按钮，"
                f"当前 URL：{page.url}，请检查是否触发了风控。"
            )

    # ── 2B. 分支 B：点击「继续沟通」，进入正式聊天室 ─────────
    if continue_btn:
        print("   🔵 点击「继续沟通」，等待聊天标签页...")
        continue_btn.click(by_js=True)
        time.sleep(random.uniform(2, 3))
        _handle_security_captcha()

    # 切换到新打开的聊天标签页
    if len(_page.tab_ids) > 1:
        page = _page.get_tab(_page.latest_tab)
        page.wait.load_start()
        time.sleep(2)

def _send_greeting_text(greeting: str):
    """发送打招呼语（空串跳过；补发场景传 "" 即可只发图片不重复打招呼）"""
    text = (greeting or "").strip()
    if not text:
        print("   ℹ️ 未提供打招呼语（补发模式），跳过打招呼")
        return
    input_box = page.ele('css:#chat-input', timeout=10)
    if not input_box:
        input_box = page.ele('css:.chat-input', timeout=5)

    if input_box:
        input_box.click(by_js=True)
        # 🌟 核心加固：整段文本完整注入输入框，优先点击发送按钮，杜绝多段话术被提前截断
        input_box.input(text)
        time.sleep(1)

        send_btn = (
            page.ele('css:.btn-send', timeout=2)
            or page.ele('text:发送', timeout=2)
            or page.ele('css:[class*="btn-send"]', timeout=1)
        )
        if send_btn and send_btn.states.is_enabled:
            send_btn.click(by_js=True)
            print("   ✅ 已点击发送按钮发送打招呼语")
        else:
            # 兜底回车触发
            input_box.input("\n")
            print("   ✅ 已通过回车键发送打招呼语")
        time.sleep(1.5)
    else:
        print("   ⚠️ 未找到聊天输入框，打招呼语未发送")

def _upload_resume_images(local_image_paths: list):
    """静默上传多张图片简历，返回 (送达张数, 总张数)。

    包含自动图片尺寸与体积压缩、多种 DOM 选择器兜底、弹窗确认支持与状态校验。
    """
    if not local_image_paths:
        return 0, 0
    print(f"   ⏳ 准备发送 {len(local_image_paths)} 张简历图片...")
    sent = 0

    # 多重选择器寻找图片上传 input
    img_input = (
        page.ele('css:.btn-sendimg input[type="file"]', timeout=3)
        or page.ele('css:.chat-toolbar input[type="file"]', timeout=2)
        or page.ele('css:input[type="file"][accept*="image"]', timeout=2)
        or page.ele('css:input[type="file"]', timeout=2)
        or page.ele('css:[title="图片"] input', timeout=2)
    )

    if not img_input:
        print("   ⚠️ 未能找到图片上传入口，请检查 BOSS 前端是否更新。")
        return 0, len(local_image_paths)

    for idx, img_path in enumerate(local_image_paths):
        abs_path = os.path.abspath(img_path)
        
        # 🌟 1. 自动预压缩：将体积压缩至 Web 友好大小 (<1MB, 宽度≤1000px)，杜绝 BOSS OSS 上传超时
        try:
            from PIL import Image
            with Image.open(abs_path) as im:
                if im.mode != "RGB":
                    im = im.convert("RGB")
                target_w = min(im.width, 1000)
                target_h = int(im.height * (target_w / im.width))
                im_resized = im.resize((target_w, target_h), Image.Resampling.LANCZOS)
                opt_path = f"/tmp/boss_opt_{idx}_{int(time.time())}.jpg"
                im_resized.save(opt_path, format="JPEG", quality=85, optimize=True)
                abs_path = opt_path
                print(f"   🗜️ 长图物料已轻量化压缩 ({os.path.getsize(opt_path)} bytes, {target_w}x{target_h})")
        except Exception as img_err:
            print(f"   ⚠️ 图片本地预压缩跳过: {img_err}")

        # 🌟 2. 注入图片并强校验送达状态
        def _count_sent_images():
            imgs = (
                page.eles('css:.im-list .item-myself .message-image')
                or page.eles('css:.item-myself .image-message')
                or page.eles('css:.item-myself img:not(.avatar):not([class*="avatar"]):not([class*="icon"])')
            )
            return len(imgs)

        base_n = _count_sent_images()
        ok = False
        for attempt in (1, 2):
            try:
                img_input.input(abs_path)
                print(f"   ⬆️ 正在静默上传第 {idx+1} 张图片（第 {attempt} 次尝试）...")
            except Exception as e:
                print(f"   ⚠️ 文件注入触发异常: {e}")
            
            # 检查是否有图片确认发送弹窗（部分版本 BOSS 会弹出确认预览框）
            time.sleep(1.5)
            confirm_btn = (
                page.ele('css:.btn-sure', timeout=1)
                or page.ele('css:.ant-btn-primary', timeout=1)
                or page.ele('css:[class*="confirm-btn"]', timeout=1)
                or page.ele('text:确认发送', timeout=1)
            )
            if confirm_btn and confirm_btn.states.is_displayed:
                confirm_btn.click(by_js=True)
                print("   🔘 已点击图片预览确认发送按钮")

            # 等待送达与状态校验
            for _ in range(12):
                time.sleep(1.5)
                cur_n = _count_sent_images()
                if cur_n > base_n:
                    # 检查最后一条消息是否带有失败红标
                    last_msgs = page.eles('css:.im-list .item-myself') or page.eles('css:.item-myself')
                    if last_msgs:
                        last_msg = last_msgs[-1]
                        fail_icon = (
                            last_msg.ele('css:[class*="fail"]', timeout=1)
                            or last_msg.ele('css:[class*="error"]', timeout=1)
                            or last_msg.ele('css:.icon-warning', timeout=1)
                        )
                        if fail_icon:
                            print("   ⚠️ 检测到图片发送失败红标，正在点击重发...")
                            fail_icon.click(by_js=True)
                            time.sleep(2)
                            continue
                    ok = True
                    break
            if ok:
                break
            # 未送达则重新寻找 input 重试一次
            img_input = (
                page.ele('css:.btn-sendimg input[type="file"]', timeout=2)
                or page.ele('css:.chat-toolbar input[type="file"]', timeout=2)
                or page.ele('css:input[type="file"][accept*="image"]', timeout=2)
                or img_input
            )
        
        if ok:
            sent += 1
            print(f"   ✅ 第 {idx+1} 张图片已送达（DOM 确认成功）")
        else:
            print(f"   ❌ 第 {idx+1} 张图片两次注入均未送达，可用 resend_resume_images 补发")
            
    print(f"   ✅ 简历图片投递完毕：{sent}/{len(local_image_paths)} 张送达")
    return sent, len(local_image_paths)

def check_job_link_alive(job_url: str):
    """链接预检：与投递同一判定标准（页面存在「立即沟通」或「继续沟通」按钮）。

    供全链路在评估前剔除已下架/过期的 BOSS 岗位链接，避免浪费评估与投递。
    返回 True=活链 / False=确定死链 / None=无法判定（异常时保留岗位，不误杀）。
    """
    global page
    page = get_browser_page()
    if not _ensure_login():
        print("   ⚠️ 登录态不可用，预检无法判定（保留岗位，不误杀）")
        return None
    try:
        page.get(job_url)
        time.sleep(random.uniform(2, 3))
        _handle_security_captcha()
        if page.ele('text:立即沟通', timeout=3) or page.ele('text:继续沟通', timeout=2):
            return True
        print(f"   💀 预检判定死链（无沟通入口）: {job_url}")
        return False
    except Exception as exc:
        print(f"   ⚠️ 链接预检异常（无法判定，保留岗位）: {str(exc)[:80]}")
        return None

class JobClosedError(RuntimeError):
    """职位已关闭或已下线异常"""
    pass

def _chat_and_send_resume(job_url: str, greeting: str, local_image_paths: list):
    """激活-关闭-重进 三段式投递 -> 打招呼 -> 发长图。返回 (sent, total) 图片送达数"""
    time.sleep(1)
    page.get(job_url)
    time.sleep(random.uniform(2, 4))
    _handle_security_captcha()

    # ── 1. 入口状态判定 ──────────────────────────────────────
    immediate_btn = page.ele('text:立即沟通', timeout=3)
    continue_btn  = page.ele('text:继续沟通', timeout=2)

    if not immediate_btn and not continue_btn:
        # 🌟 智能研判岗位是否已在 BOSS 平台上关闭/下架
        closed_hint = (
            page.ele('text:职位已关闭', timeout=1)
            or page.ele('text:停止招聘', timeout=1)
            or page.ele('text:该职位已下线', timeout=1)
            or page.ele('text:查看更多优选职位', timeout=1)
        )
        if closed_hint:
            raise JobClosedError(f"该职位在 BOSS 直聘上已关闭或停止招聘 ({closed_hint.text})")
        raise RuntimeError(
            f"页面上既未找到「立即沟通」也未找到「继续沟通」，"
            f"当前 URL：{page.url}，岗位可能已下线或需要手动刷新。"
        )

    # ── 2. 激活并进入聊天室 ──────────────────────────────────────
    _enter_chat_room(immediate_btn, continue_btn)

    # ── 3. 聊天室内动作 ──────────────────────────────────────
    _send_greeting_text(greeting)

    sent, total = 0, 0
    if local_image_paths:
        sent, total = _upload_resume_images(local_image_paths)

    # 收尾：尝试关闭聊天标签页（4.x 的 tab 对象无 tab_ids，清理失败不影响投递结果）
    try:
        if len(page.tab_ids) > 1:
            page.close()
    except Exception:
        pass
    return sent, total

def _log_failure(record_id: str, error_msg: str, job_data: dict | None = None):
    if job_data is not None:
        job_data["delivery_error"] = str(error_msg)
    if record_id:
        update_feishu_record(record_id, {"自动投递失败日志": str(error_msg)[:120]})

def _download_resume_images(image_items: list) -> list:
    """下载图片并返回本地路径列表"""
    local_image_paths = []
    print(f"\n▶ A. 飞书数据联动 | 下载 {len(image_items)} 张图片 ...")
    for item in image_items:
        token = item.get("token") or item.get("file_token")
        if not token:
            continue
        name = item.get("name", "resume_img")
        short_token = str(token)[:6]
        local_path = os.path.join(TEMP_DIR, f"{name}_{short_token}.png")
        # 🌟 去掉 feishu_api. 前缀，直接调用
        ok = download_feishu_file(token, local_path)
        if ok and os.path.exists(local_path):
            local_image_paths.append(local_path)
    return local_image_paths

def _update_success_record(record_id: str):
    """更新飞书投递成功状态"""
    if record_id:
        # 🌟 修复：飞书 API 要求日期字段必须是毫秒级时间戳，不能是字符串
        import time
        current_ts = int(time.time() * 1000)
        update_feishu_record(record_id, {
            "跟进状态": "已投递",
            "自动投递失败日志": "",
            "投递日期": current_ts
        })

def _cleanup_after_delivery(local_image_paths: list, disconnect_error: bool):
    """投递后的清理工作：删除本地图片、关闭多余聊天标签页并安全复位"""
    global page, _page
    for img_path in local_image_paths:
        if os.path.exists(img_path):
            try:
                os.remove(img_path)
            except OSError:
                pass
    if not disconnect_error and _page is not None:
        try:
            # 优雅收敛所有新开子标签页，仅保留主标签页
            while len(_page.tab_ids) > 1:
                _page.get_tab(_page.latest_tab).close()
            page = _page
        except Exception:
            pass

def deliver_job(job_data: dict) -> bool:
    """投递入口。

    返回 True 表示打招呼已成立；若图片未全部送达，会在飞书
    「自动投递失败日志」写入【待补发图片】标记（仍返回 True，避免上层
    整单重投导致重复打招呼），后续用 resend_resume_images 补发即可。
    """
    global page
    page = get_browser_page()

    job_url     = job_data.get("job_url", "")
    image_items = job_data.get("image_items", [])
    greeting    = job_data.get("greeting", "")
    record_id   = job_data.get("record_id", "")

    # 确保登录态安全：失效且等待超时 → 按失败返回，不再无限挂起
    if not _ensure_login():
        _log_failure(record_id, "[登录] BOSS登录态失效，等待扫码超时", job_data)
        return False

    local_image_paths = []
    disconnect_error = False
    os.makedirs(TEMP_DIR, exist_ok=True)

    try:
        from app.automation.delivery_interrupter import register_delivery_target, make_page_interrupt_fn
        register_delivery_target(record_id, make_page_interrupt_fn(lambda: page))
    except Exception:
        pass

    try:
        from app.automation.abort import is_job_delivery_cancelled
        if is_job_delivery_cancelled(record_id):
            print(f"🛑 [BOSS] 物料准备前检测到岗位 {record_id} 已被用户终止，立即退出")
            _log_failure(record_id, "[用户主动终止] 在指挥中心手动终止投递流程", job_data)
            return False

        if image_items:
            local_image_paths = _download_resume_images(image_items)
            if not local_image_paths:
                _log_failure(record_id, "[物料] 所有图片下载失败", job_data)
                return False

            if is_job_delivery_cancelled(record_id):
                print(f"🛑 [BOSS] 图片物料下载后检测到岗位 {record_id} 已被用户终止，立即退出")
                _log_failure(record_id, "[用户主动终止] 在指挥中心手动终止投递流程", job_data)
                return False

        print("\n▶ B. 主动出击 | 发起沟通并发送简历 ...")
        page.wait.load_start()
        sent, total = _chat_and_send_resume(job_url, greeting, local_image_paths)

        _update_success_record(record_id)

        # 部分送达：打招呼已成立但图片未全部送达，标记待补发（见模块头经验 5）
        if total and sent < total:
            _log_failure(record_id, f"【待补发图片】打招呼成功但图片仅送达 {sent}/{total} 张，请调用 resend_resume_images 补发", job_data)
            print(f"⚠️ 图片部分送达（{sent}/{total}），已在飞书标记待补发")

        print("🎉 本次 BOSS 投递任务圆满结束！")
        return True

    except JobClosedError as jce:
        err_msg = str(jce)[:100]
        print(f"⚠️ 岗位已关闭/已下线：{err_msg}")
        job_data["delivery_error"] = f"[下架] BOSS岗位已关闭或已下线: {err_msg}"
        try:
            update_feishu_record(record_id, {
                "跟进状态": "已下架",
                "自动投递失败日志": f"[下架] BOSS平台已下线: {err_msg}"
            })
            from app.core.cache import JobCache
            JobCache.patch_record_fields(record_id, {"follow_status": "已下架"})
            print(f"   ℹ️ 岗位 {record_id} 已在飞书与本地缓存中自动标记为「已下架」")
        except Exception as e:
            print(f"⚠️ 标记已下架异常: {e}")
        return False

    except Exception as exc:
        err_msg = str(exc)[:100]
        disconnect_error = any(k in str(exc).lower() for k in ('disconnect', 'connection refused', 'closed'))
        print(f"❌ 投递异常中断：{err_msg}")
        _log_failure(record_id, f"投递异常: {err_msg}", job_data)
        return False
    finally:
        try:
            from app.automation.delivery_interrupter import unregister_delivery_target
            unregister_delivery_target(record_id)
        except Exception:
            pass
        _cleanup_after_delivery(local_image_paths, disconnect_error)


def resend_resume_images(job_data: dict) -> bool:
    """补发入口：对已打过招呼但缺图的岗位补发图片简历（见模块头经验 5）。

    job_data 需含 job_url、image_items（[{'token','name'}]）与 record_id；
    无需 greeting——内部强制置空，只走「继续沟通」发图，不重发打招呼语。
    补发成功后清空「自动投递失败日志」中的待补发标记。
    """
    job_data = dict(job_data)
    job_data["greeting"] = ""
    ok = deliver_job(job_data)
    if ok:
        print("✅ 补发流程完成（若仍有未送达图片，失败日志会保留【待补发图片】标记）")
    return ok