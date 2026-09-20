"""
飞书 WebSocket 长连接客户端
替代 Cloudflare Tunnel + Webhook 方案，本地主动连接飞书服务器接收事件。

使用方式：
    在 FastAPI lifespan 中调用 start_feishu_ws() 启动后台线程。
"""

import asyncio
import json
import logging
import re
import threading
import time

import lark_oapi as lark
from lark_oapi.api.im.v1 import P2ImMessageReceiveV1
from lark_oapi.event.callback.model.p2_card_action_trigger import (
    CallBackToast,
    P2CardActionTrigger,
    P2CardActionTriggerResponse,
)

from app.core.config import settings
from app.services import resume_edit_chat
from app.services.job_entry_chat import (
    clear_pending_link,
    clear_pending_pipeline,
    extract_post_text,
    handle_card_action,
    handle_image_message,
    handle_link_reply,
    handle_pipeline_confirm,
    handle_unsupported_message,
    should_intercept_link_reply,
    should_intercept_pipeline_confirm,
)

# logger 用 __name__（app.core.feishu_ws）归入 "app" 层级，才能吃到 console_stream 的 setLevel(INFO)
# ——裸名 logger 的 INFO 被 root WARNING 拦截，守卫/时间守卫/幂等/重连等运行日志会全部静默丢弃（Q-M9-7）
logger = logging.getLogger(__name__)

# ==========================================
# 消息防重锁（与 webhook 共用 app.core.feishu_msg_dedup，双通道防重复处理）
# ==========================================
def _check_idempotency(message_id: str) -> bool:
    """检查消息是否已处理。未处理返回 True，已处理返回 False。"""
    from app.core.feishu_msg_dedup import check_and_mark
    if not check_and_mark(message_id):
        logger.info(f"[防重锁] 重复消息已忽略: {message_id}")
        return False
    return True


# ==========================================
# 文本清洗（复用 webhook.py 逻辑）
# ==========================================
def _clean_feishu_text(raw_text: str) -> str:
    """清除飞书文本中的 @标签 和多余空白。"""
    clean_text = re.sub(r'<at[^>]*>.*?</at>', '', raw_text, flags=re.DOTALL)
    clean_text = re.sub(r'@_user_\d+', '', clean_text)
    return re.sub(r'\s+', ' ', clean_text).strip()


# ==========================================
# 多维表格事件处理（Q-M9-1：反向同步事件链）
# ==========================================
def _on_bitable_record_changed(data) -> None:
    """
    drive.v1.file.bitable_record_changed 事件回调（多维表格记录新增/修改/删除）。
    仅标记岗位缓存为脏，实际刷新由下次读取时的消费者提前触发（app/jobs/service.py）。
    """
    try:
        from app.core.cache import JobCache
        from app.core.config import settings

        event = getattr(data, "event", None)
        file_token = str(getattr(event, "file_token", "") or "")
        table_id = str(getattr(event, "table_id", "") or "")
        # 只关心本系统 bitable 的变动（QA 表/简历库等共享同一 app_token，脏标记本身无害但减少噪音）
        if settings.FEISHU_APP_TOKEN and file_token and file_token != settings.FEISHU_APP_TOKEN:
            return
        JobCache.mark_dirty()
        logger.info(f"[Bitable] 检测到多维表格记录变更 (table={table_id or '未知'})，已标记缓存脏（下次读取立即后台刷新）")
    except Exception:
        logger.exception("[Bitable] 缓存标记失败")


# ==========================================
# 消息事件处理器
# ==========================================
def _on_message_receive(data: P2ImMessageReceiveV1) -> None:
    """
    im.message.receive_v1 事件回调。
    注意：此函数在 lark-oapi 的线程池中执行，需 3 秒内返回。
    耗时操作通过 asyncio.create_task 异步处理。
    """

    try:
        event = data.event
        message = event.message
        msg_type = message.message_type
        chat_id = message.chat_id
        message_id = message.message_id
        create_time = message.create_time  # 毫秒时间戳字符串

        # 提取话题 root_id（话题内消息才有，主对话流为空字符串或 None）
        root_id = getattr(message, "root_id", None) or None

        logger.info(f"[WS] 收到消息 | type={msg_type} | chat_id={chat_id} | msg_id={message_id} | root_id={root_id}")

        # 发送者守卫：机器人/应用自身发送的消息直接丢弃，严防死循环
        sender = getattr(event, "sender", None)
        sender_type = str(getattr(sender, "sender_type", "") or (sender.get("sender_type") if isinstance(sender, dict) else "") or "").lower()
        if sender_type in ("app", "bot"):
            logger.info(f"[发送者守卫] 忽略机器人自身消息 (type={sender_type}) | msg_id={message_id}")
            return

        # 时间戳守卫：超过 300 秒的过期消息丢弃（所有消息类型统一生效）
        if create_time:
            create_time_s = int(create_time) / 1000.0 if int(create_time) > 1e10 else float(create_time)
            msg_age = time.time() - create_time_s
            if msg_age > 300:
                logger.info(f"[时间守卫] 消息已过期 {msg_age:.0f}s，忽略: {message_id}")
                return

        # 幂等防重
        if not _check_idempotency(message_id):
            return

        # 图片消息 → 岗位截图录入链路（聚合窗口内攒图后走 Vision 解析建岗）
        if msg_type == "image":
            try:
                image_key = json.loads(message.content or "{}").get("image_key", "")
            except (json.JSONDecodeError, AttributeError):
                image_key = ""
            logger.info(f"[WS] 图片消息 | image_key={image_key}")
            if image_key and chat_id:
                _dispatch_coroutine(handle_image_message(chat_id, image_key, message_id))
            else:
                logger.warning(f"[WS] image_key 或 chat_id 为空，丢弃 | msg_id={message_id}")
            return

        # 富文本（多行/带格式文本）：提取正文后走文本管道
        if msg_type == "post":
            raw_text = extract_post_text(message.content or "{}")
            logger.info(f"[WS] 富文本提取 {len(raw_text)} 字符")
        elif msg_type == "text":
            raw_content = message.content or "{}"
            try:
                raw_text = json.loads(raw_content).get("text", "")
            except (json.JSONDecodeError, AttributeError):
                raw_text = raw_content
        else:
            # 暂不支持的消息类型：友好提示而非静默丢弃
            logger.info(f"[WS] 不支持的消息类型 (type={msg_type})，回复提示")
            if chat_id:
                _dispatch_coroutine(handle_unsupported_message(chat_id, msg_type))
            return

        # 文本清洗
        clean_text = _clean_feishu_text(raw_text)
        logger.info(f"[WS] 清洗后文本: '{clean_text[:100]}'")

        if not clean_text or not chat_id:
            logger.info("[WS] clean_text 或 chat_id 为空，丢弃")
            return

        # Ping-Pong 心跳测试
        if clean_text.strip().lower() in ("ping", "测试", "test"):
            from app.services.feishu_service import send_feishu_message
            send_feishu_message(chat_id, "🏓 pong！WebSocket 长连接链路畅通，Agent 引擎待命中～", "chat_id")
            return

        # 岗位链接补录回复拦截（截图录入后反问链接，回复链接/「跳过」在此消费）
        if should_intercept_link_reply(chat_id, clean_text):
            logger.info(f"[WS] 拦截岗位链接补录回复 | chat_id={chat_id}")
            _dispatch_coroutine(handle_link_reply(chat_id, clean_text))
            return

        # 全链路确认拦截（录入后反问，回复「走全链路」触发单岗位流水线）
        if should_intercept_pipeline_confirm(chat_id, clean_text):
            logger.info(f"[WS] 拦截全链路确认回复 | chat_id={chat_id}")
            _dispatch_coroutine(handle_pipeline_confirm(chat_id, clean_text))
            return

        clear_pending_link(chat_id)  # 用户回复了别的内容，静默清除待补录状态
        clear_pending_pipeline(chat_id)  # 同上，清除全链路待确认状态

        # 🚪 审批门禁（Q-M9-4）：文字快捷审批白名单（只读查询不受限）
        from app.core.chatops_authorizer import DENY_REPLY, denied_text_approval
        sender_open_id = str(getattr(getattr(sender, "sender_id", None), "open_id", "") or "")
        if denied_text_approval(sender_open_id, clean_text):
            logger.warning(f"[审批门禁] 文字快捷审批被拒绝（操作者={sender_open_id or '未知'}）")
            from app.services.feishu_service import send_feishu_message
            _dispatch_coroutine(asyncio.to_thread(send_feishu_message, chat_id, DENY_REPLY, "chat_id"))
            return

        # 🤖 ChatAgent（新一代智能中枢：模型自主意图路由 + 工具循环决策；全量自然语言优先由大模型处理）
        try:
            from app.services.chat_agent import agent as chat_agent
            if chat_agent.is_ready():
                logger.info(f"[WS] 投递 ChatAgent | chat_id={chat_id} | text='{clean_text[:60]}'")
                _dispatch_coroutine(chat_agent.handle_agent_message(chat_id, clean_text))
                return
        except Exception:
            logger.exception("[WS] ChatAgent 分发异常，回退老版规则拦截器与老 Agent")

        # 🔍 回退逻辑：显式岗位定位拦截（找岗位/切换岗位）
        if resume_edit_chat.should_intercept_locate(chat_id, clean_text):
            logger.info(f"[WS] [Fallback] 拦截岗位定位 | chat_id={chat_id}")
            _dispatch_coroutine(resume_edit_chat.handle_locate(chat_id, clean_text))
            return

        # 📮 回退逻辑：已投递 + ✏️ 简历修改指令拦截
        if resume_edit_chat.should_intercept_delivered(chat_id, clean_text):
            logger.info(f"[WS] [Fallback] 拦截已投递更新 | chat_id={chat_id}")
            _dispatch_coroutine(resume_edit_chat.handle_delivered_reply(chat_id, clean_text))
            return
        if resume_edit_chat.should_intercept_edit(chat_id, clean_text):
            logger.info(f"[WS] [Fallback] 拦截简历修改指令 | chat_id={chat_id}")
            _dispatch_coroutine(resume_edit_chat.handle_edit_message(chat_id, clean_text))
            return
        resume_edit_chat.clear_edit_session(chat_id)

        # 投给老版 Agent 处理（异步，不阻塞 handler）
        logger.info(f"[WS] [Fallback] 投递老 Agent | chat_id={chat_id} | root_id={root_id} | text='{clean_text[:60]}'")
        _dispatch_to_agent(chat_id, clean_text, root_id=root_id)

    except Exception as e:
        logger.exception(f"[WS] 消息处理异常: {e}")


# ==========================================
# 卡片按钮回调（card.action.trigger，长连接接收）
# ==========================================
def _on_card_action(data: P2CardActionTrigger) -> P2CardActionTriggerResponse:
    """
    用户点击卡片回传按钮时的回调。运行在 lark-oapi 的线程池中，需快速返回：
    先回 toast 给用户即时反馈，耗时动作通过事件循环异步处理。
    """
    try:
        event = data.event
        action_value = dict(event.action.value or {}) if (event and event.action) else {}
        chat_id = (event.context.open_chat_id if (event and event.context) else "") or str(action_value.get("chat_id") or "")
        action = str(action_value.get("action") or "")
        logger.info(f"[WS] 卡片按钮点击 | chat_id={chat_id} | action={action} | value={action_value}")

        # 🚪 审批门禁（Q-M9-4）：状态变更动作校验操作者白名单
        from app.core.chatops_authorizer import GUARDED_CARD_ACTIONS, is_authorized
        if action in GUARDED_CARD_ACTIONS:
            operator_open_id = str(getattr(event.operator, "open_id", "") or "") if (event and event.operator) else ""
            if not is_authorized(operator_open_id, action):
                logger.warning(f"[审批门禁] 卡片动作 {action!r} 被拒绝（操作者={operator_open_id or '未知'}）")
                resp = P2CardActionTriggerResponse()
                resp.toast = CallBackToast({"type": "failed", "content": "⛔ 此操作需要审批权限，请联系审批人"})
                return resp

        if not chat_id:
            logger.warning("[WS] 卡片回调缺少 chat_id，无法处理")
            resp = P2CardActionTriggerResponse()
            resp.toast = CallBackToast({"type": "failed", "content": "无法定位会话，请重试"})
            return resp

        # 战报卡片专属交互（精投放行/海投放行/召回/淘汰/调出子卡片）
        from app.services.report_card_actions import (
            handle_report_card_action,
            is_report_card_action,
        )
        if is_report_card_action(action):
            selected_options = None
            if event and event.action:
                if event.action.options:
                    selected_options = list(event.action.options)
                elif getattr(event.action, "form_value", None):
                    fv = dict(event.action.form_value)
                    val = fv.get("selected_jobs")
                    if val is None and fv:
                        val = next(iter(fv.values()), None)
                    if isinstance(val, list):
                        selected_options = [str(x) for x in val if x]
                    elif isinstance(val, str) and val.strip():
                        selected_options = [val.strip()]

            logger.info(f"[WS] 战报卡片专属交互 | action={action} | selected={selected_options}")
            _dispatch_coroutine(handle_report_card_action(chat_id, action_value, selected_options))
            resp = P2CardActionTriggerResponse()
            resp.toast = CallBackToast({"type": "info", "content": "正在处理操作，完成后在群内通知..."})
            return resp

        _dispatch_coroutine(handle_card_action(chat_id, action_value))

        toast_content = {
            "run_pipeline": "已开始评估，详情见聊天消息",
            "explain_pipeline": "说明已发送",
            "mark_delivered": "已更新为已投递",
        }.get(action, "已处理")
        # SDK 的 Response 只接受位置参数 dict（kwargs 会 TypeError，导致飞书显示报错 toast）
        resp = P2CardActionTriggerResponse()
        resp.toast = CallBackToast({"type": "success", "content": toast_content})
        return resp
    except Exception as e:
        logger.exception(f"[WS] 卡片按钮回调处理异常: {e}")
        resp = P2CardActionTriggerResponse()
        resp.toast = CallBackToast({"type": "failed", "content": "处理失败，请重试"})
        return resp


def _dispatch_coroutine(coro) -> None:
    """把任意协程调度到主事件循环执行（WS handler 运行在独立线程）。"""
    try:
        loop = _get_main_loop()
        if loop and loop.is_running():
            future = asyncio.run_coroutine_threadsafe(coro, loop)

            def _log_failure(fut):
                exc = fut.exception()
                if exc:
                    logger.error(f"[WS] 卡片动作处理协程异常: {exc}", exc_info=exc)

            future.add_done_callback(_log_failure)
        else:
            logger.warning("[WS] 主事件循环不可用，协程任务被丢弃")
    except Exception as e:
        logger.exception(f"[WS] 协程调度失败: {e}")


def _dispatch_to_agent(chat_id: str, text: str, root_id: str | None = None) -> None:
    """
    将消息投递给 Agent 引擎。
    由于 lark-oapi handler 运行在独立线程，需要通过 asyncio 事件循环调度。
    """
    import asyncio

    try:
        loop = _get_main_loop()
        if loop and loop.is_running():
            from app.agent_router import process_chatops_query
            asyncio.run_coroutine_threadsafe(process_chatops_query(chat_id, text, root_id=root_id), loop)
        else:
            # fallback: 同步执行（开发调试用）
            logger.warning("[WS] 主事件循环不可用，同步执行 Agent")
            from app.agent_router import process_chatops_query
            asyncio.run(process_chatops_query(chat_id, text, root_id=root_id))
    except Exception as e:
        logger.exception(f"[WS] Agent 投递失败: {e}")
        try:
            from app.services.feishu_service import send_feishu_message
            send_feishu_message(chat_id, f"❌ Agent 引擎异常: {str(e)}", "chat_id")
        except Exception:
            pass


# ==========================================
# 主事件循环引用（FastAPI 的 asyncio loop）
# ==========================================
_main_loop: asyncio.AbstractEventLoop | None = None


def _get_main_loop() -> asyncio.AbstractEventLoop | None:
    return _main_loop


# ==========================================
# WS Client 生命周期管理
# ==========================================
_ws_client: lark.ws.Client | None = None
_ws_thread: threading.Thread | None = None
_ws_loop: asyncio.AbstractEventLoop | None = None      # WS 线程内部事件循环（用于打断阻塞的 start()）
_ws_shutdown_event: threading.Event | None = None


def is_ws_running() -> bool:
    """长连接是否在线（诊断接口与前端 checklist 自动点亮用）。"""
    return bool(_ws_thread and _ws_thread.is_alive() and _ws_client is not None)


def start_feishu_ws(loop: asyncio.AbstractEventLoop | None = None) -> bool:
    """
    启动飞书 WebSocket 长连接客户端（后台守护线程）。

    Args:
        loop: FastAPI 主事件循环，用于跨线程调度异步任务。

    Returns:
        True 表示启动成功，False 表示配置缺失或启动失败。
    """
    global _ws_client, _ws_thread, _main_loop, _ws_loop, _ws_shutdown_event

    # 读取凭证的时刻即生效时刻：settings 已被 sync_settings_to_runtime() 原地更新，
    # 配置页保存凭证后调用 restart_feishu_ws() 即可用新值建立连接
    app_id = settings.FEISHU_APP_ID
    app_secret = settings.FEISHU_APP_SECRET

    if not app_id or not app_secret:
        logger.warning("[WS] FEISHU_APP_ID / FEISHU_APP_SECRET 未配置，跳过 WebSocket 长连接")
        return False

    _main_loop = loop

    # 构建事件处理器
    event_handler = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(_on_message_receive)
        .register_p2_card_action_trigger(_on_card_action)
        .register_p2_drive_file_bitable_record_changed_v1(_on_bitable_record_changed)
        .build()
    )

    # 创建 WS 客户端
    _ws_client = lark.ws.Client(
        app_id,
        app_secret,
        event_handler=event_handler,
        log_level=lark.LogLevel.INFO,
    )

    # 在守护线程中启动（ws.Client.start() 内部调用 run_until_complete，需要独立事件循环）
    _shutdown = threading.Event()
    _ws_shutdown_event = _shutdown
    client = _ws_client

    def _run():
        # 重置事件循环策略为默认，彻底避免 uvloop 与 uvicorn 冲突
        global _ws_loop
        asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())
        new_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(new_loop)
        _ws_loop = new_loop

        # 关键：lark_oapi.ws.client 在模块顶层捕获了 loop 变量，
        # start() 直接使用它而非 asyncio.get_event_loop()，必须手动替换
        import lark_oapi.ws.client as _ws_mod
        _ws_mod.loop = new_loop

        logger.info("[WS] 飞书 WebSocket 长连接启动中...")
        while not _shutdown.is_set():
            try:
                client.start()
                break  # start() 正常退出（极少发生）
            except Exception as e:
                if _shutdown.is_set():
                    break
                logger.warning(f"[WS] 长连接异常: {e}, 5秒后重连...")
                _shutdown.wait(5)  # 可中断的 sleep

    _ws_thread = threading.Thread(target=_run, name="feishu-ws-client", daemon=True)
    _ws_thread.start()
    logger.info("[WS] 飞书 WebSocket 长连接线程已启动")
    return True


def stop_feishu_ws(timeout: float = 5.0) -> None:
    """停止 WS 长连接：置停止事件并打断 lark ws 的事件循环，等待后台线程退出。

    lark-oapi 的 ws.Client 没有公开 stop 方法，start() 阻塞在自建事件循环的
    run_until_complete 上；对其 call_soon_threadsafe(loop.stop) 会令 start() 抛
    RuntimeError 退出，而停止事件已置位、重连循环随之终止，线程干净退出。
    """
    global _ws_client, _ws_thread, _ws_shutdown_event, _ws_loop

    ev = _ws_shutdown_event
    if ev:
        ev.set()

    loop = _ws_loop
    if loop is not None and loop.is_running():
        try:
            loop.call_soon_threadsafe(loop.stop)
        except Exception:
            pass

    t = _ws_thread
    if t and t.is_alive() and t is not threading.current_thread():
        t.join(timeout=timeout)

    _ws_client = None
    _ws_thread = None
    _ws_shutdown_event = None
    _ws_loop = None
    logger.info("[WS] 飞书 WebSocket 长连接已停止")


def restart_feishu_ws(loop: asyncio.AbstractEventLoop | None = None) -> bool:
    """用最新凭证重建长连接（配置页保存 FEISHU_APP_ID/SECRET 后调用）。"""
    try:
        stop_feishu_ws()
    except Exception:
        logger.exception("[WS] 停止旧长连接失败，继续尝试重启")
    started = start_feishu_ws(loop)
    if started:
        logger.info("[WS] 长连接已用最新凭证重启")
    else:
        logger.warning("[WS] 重启长连接失败（凭证缺失或无效）")
    return started
