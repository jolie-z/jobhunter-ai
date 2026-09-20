# backend/app/api/routers/webhook.py
import asyncio
import json
import re
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.agent_router import process_chatops_query
from app.services import resume_edit_chat

# 🌟 干净地引入新版的飞书推送服务
from app.services.feishu_service import send_feishu_message
from app.services.job_entry_chat import (
    clear_pending_link,
    clear_pending_pipeline,
    extract_post_text,
    handle_image_message,
    handle_link_reply,
    handle_pipeline_confirm,
    handle_unsupported_message,
    should_intercept_link_reply,
    should_intercept_pipeline_confirm,
)

router = APIRouter()

# ==========================================
# 全局状态：后台任务集合（消息防重锁在 app.core.feishu_msg_dedup，双通道共用）
# ==========================================
_BACKGROUND_TASKS = set()


def _spawn_background(coro) -> None:
    """调度后台协程任务并持有引用防止被 GC。"""
    try:
        task = asyncio.create_task(coro)
        _BACKGROUND_TASKS.add(task)
        task.add_done_callback(_BACKGROUND_TASKS.discard)
    except Exception as e:
        print(f"⚠️ 后台任务调度失败: {e}")


def _clean_feishu_text(raw_text: str) -> str:
    """清除飞书文本中的特殊标记和多余空白。"""
    # 步骤1：清除飞书群聊 @机器人 产生的 XML at 标签
    clean_text = re.sub(r'<at[^>]*>.*?</at>', '', raw_text, flags=re.DOTALL)
    # 步骤2：清除 @_user_XXX 形式的脏标记
    clean_text = re.sub(r'@_user_\d+', '', clean_text)
    # 步骤3：压缩多余空白/换行
    return re.sub(r'\s+', ' ', clean_text).strip()


def _check_idempotency(message_id: str) -> bool:
    """检查消息是否已处理（与 WS 长连接共用同一把防重锁），处理过返回 False，未处理返回 True"""
    from app.core.feishu_msg_dedup import check_and_mark
    if not check_and_mark(message_id):
        print(f"🛡️ [防重锁] 重复消息已忽略: {message_id}")
        return False
    return True


def _handle_bitable_event(event_type: str) -> bool:
    """处理多维表格事件，返回 True 视为已处理该事件。

    兼容两种事件名：v1 正式名 drive.v1.file.bitable_record_changed（长连接/webhook 实际下发名）
    与历史遗留的 bitable.* 前缀（Q-M9-1：旧前缀过滤永远匹配不上正式名，属双重缺陷之一）。
    """
    if event_type.startswith("bitable.") or event_type == "drive.v1.file.bitable_record_changed":
        from app.core.cache import JobCache
        print(f"🔥🔥🔥 [X-Ray 4-BITABLE] 检测到多维表格数据变动 ({event_type})，标记岗位缓存为脏（读取时后台刷新）。")
        JobCache.mark_dirty()
        return True
    return False


def _process_webhook_event(data: dict):
    """处理飞书 Webhook 核心事件逻辑。"""
    header = data.get("header", {})
    event = data.get("event", {})
    event_type = header.get("event_type", "")
    print(f"🔥🔥🔥 [X-Ray 4] event_type='{event_type}'")

    if _handle_bitable_event(event_type):
        return

    if event_type != "im.message.receive_v1":
        print(f"🔥🔥🔥 [X-Ray 4-SKIP] 非消息事件 ({event_type})，跳过。")
        return

    message = event.get("message", {})
    msg_type = message.get("message_type", "")
    chat_id = message.get("chat_id", "")
    message_id = message.get("message_id", "")
    # 🔥🔥🔥 [X-Ray 5.5] 发送者守卫（机器人自身消息直接丢弃，严防死循环）
    sender = event.get("sender", {})
    sender_type = str(sender.get("sender_type") or "").lower()
    if sender_type in ("app", "bot"):
        print(f"🤖 [发送者守卫] 忽略机器人自身消息 (type={sender_type}) | message_id={message_id}")
        return

    # 🔥🔥🔥 [X-Ray 8] 时间戳守卫（文本/图片等所有消息类型统一生效）
    _create_time_ms = int(message.get("create_time", 0))
    _create_time_s = _create_time_ms / 1000.0 if _create_time_ms > 1e10 else float(_create_time_ms)
    _msg_age = time.time() - _create_time_s if _create_time_s else 0.0
    print(f"🔥🔥🔥 [X-Ray 8] 消息年龄: {_msg_age:.1f} 秒")
    if _create_time_s and _msg_age > 300:
        print(f"🛡️ [时间守卫拦截] 消息已过期 {_msg_age:.0f} 秒，忽略: {message_id}")
        return

    # 🔥🔥🔥 [X-Ray 9] 幂等性防重锁
    if not _check_idempotency(message_id):
        return
    print("🔥🔥🔥 [X-Ray 9] 幂等锁通过 ✅")

    if msg_type == "image":
        # 🖼️ 岗位截图录入链路：聚合窗口内攒图后走 Vision 解析建岗
        try:
            image_key = json.loads(message.get("content", "{}")).get("image_key", "")
        except Exception:
            image_key = ""
        print(f"🖼️ [X-Ray 5-IMAGE] image_key='{image_key}'")
        if image_key and chat_id:
            _spawn_background(handle_image_message(chat_id, image_key, message_id))
        else:
            print(f"⚠️ [X-Ray 5-IMAGE] image_key 或 chat_id 为空，丢弃 | message_id={message_id}")
        return

    if msg_type == "post":
        # 📝 富文本（多行/带格式文本）：提取正文后走文本管道
        raw_content = message.get("content", "{}")
        raw_text = extract_post_text(raw_content)
        print(f"📝 [X-Ray 5-POST] 富文本提取 {len(raw_text)} 字符")
    elif msg_type == "text":
        raw_content = message.get("content", "{}")
        print(f"🔥🔥🔥 [X-Ray 6] raw_content: {raw_content[:300]}")
        try:
            raw_text = json.loads(raw_content).get("text", "")
        except Exception:
            raw_text = raw_content
    else:
        # 🔇 暂不支持的消息类型：友好提示而非静默丢弃
        print(f"🔥🔥🔥 [X-Ray 5-UNSUPPORTED] 非文本/图片消息 (type={msg_type})，回复提示。")
        if chat_id:
            _spawn_background(handle_unsupported_message(chat_id, msg_type))
        return
    print(f"🔥🔥🔥 [X-Ray 6] raw_text: '{raw_text}'")

    # 🔥🔥🔥 [X-Ray 7] 强力文本清洗
    clean_text = _clean_feishu_text(raw_text)
    print(f"🔥🔥🔥 [X-Ray 7] clean_text: '{clean_text}'")

    if not clean_text or not chat_id:
        print("🔥🔥🔥 [X-Ray 9-SKIP] clean_text 或 chat_id 为空，丢弃。")
        return

    # 🔥🔥🔥 [X-Ray 10] Ping-Pong 控制变量测试
    if clean_text.strip().lower() in ("ping", "测试", "test"):
        print("🔥🔥🔥 [X-Ray 10-PING] 命中 Ping-Pong 测试，同步回复 pong！")
        send_feishu_message(chat_id, "🏓 pong！后端链路完全畅通，Agent 引擎待命中～", "chat_id")
        return

    # 🔗 岗位链接补录回复拦截（截图录入后反问链接，回复链接/「跳过」在此消费）
    if should_intercept_link_reply(chat_id, clean_text):
        print(f"🔗 [X-Ray 10-LINK] 拦截岗位链接补录回复 | chat_id='{chat_id}'")
        _spawn_background(handle_link_reply(chat_id, clean_text))
        return

    # 🚀 全链路确认拦截（录入后反问，回复「走全链路」触发单岗位流水线）
    if should_intercept_pipeline_confirm(chat_id, clean_text):
        print(f"🚀 [X-Ray 10-PIPELINE] 拦截全链路确认回复 | chat_id='{chat_id}'")
        _spawn_background(handle_pipeline_confirm(chat_id, clean_text))
        return

    clear_pending_link(chat_id)  # 用户回复了别的内容，静默清除待补录状态
    clear_pending_pipeline(chat_id)  # 同上，清除全链路待确认状态

    # 🚪 审批门禁（Q-M9-4）：文字快捷审批白名单（与 WS 通道同口径、同词表单一事实源）
    from app.core.chatops_authorizer import DENY_REPLY, denied_text_approval
    _oid = str((((event.get("sender") or {}).get("sender_id") or {}).get("open_id")) or "")
    if denied_text_approval(_oid, clean_text):
        print(f"🚪 [审批门禁] 文字快捷审批被拒绝（操作者={_oid or '未知'}）")
        send_feishu_message(chat_id, DENY_REPLY, "chat_id")
        return

    # 🤖 ChatAgent（新一代智能中枢：模型自主意图路由 + 工具循环决策；全量自然语言优先由大模型处理）
    try:
        from app.services.chat_agent import agent as chat_agent
        if chat_agent.is_ready():
            print(f"🤖 [X-Ray 11-ChatAgent] 投递 ChatAgent | chat_id='{chat_id}' | text='{clean_text[:60]}'")
            _spawn_background(chat_agent.handle_agent_message(chat_id, clean_text))
            return
    except Exception:
        import logging
        logging.getLogger(__name__).exception("[webhook] ChatAgent 分发异常，回退老版规则拦截器与老 Agent")

    # 🔍 回退逻辑：显式岗位定位拦截（找岗位/切换岗位）
    if resume_edit_chat.should_intercept_locate(chat_id, clean_text):
        print(f"🔍 [X-Ray 10-LOCATE] [Fallback] 拦截岗位定位 | chat_id='{chat_id}'")
        _spawn_background(resume_edit_chat.handle_locate(chat_id, clean_text))
        return

    # 📮 回退逻辑：已投递 + ✏️ 简历修改指令拦截
    if resume_edit_chat.should_intercept_delivered(chat_id, clean_text):
        print(f"📮 [X-Ray 10-DELIVERED] [Fallback] 拦截已投递更新 | chat_id='{chat_id}'")
        _spawn_background(resume_edit_chat.handle_delivered_reply(chat_id, clean_text))
        return
    if resume_edit_chat.should_intercept_edit(chat_id, clean_text):
        print(f"✏️ [X-Ray 10-EDIT] [Fallback] 拦截简历修改指令 | chat_id='{chat_id}'")
        _spawn_background(resume_edit_chat.handle_edit_message(chat_id, clean_text))
        return
    resume_edit_chat.clear_edit_session(chat_id)

    # 🔥🔥🔥 [X-Ray 11] 回退投递老版 LangGraph Agent（非阻塞）
    print(f"🔥🔥🔥 [X-Ray 11] [Fallback] 投递 process_chatops_query | chat_id='{chat_id}' | text='{clean_text[:60]}'")
    _spawn_background(process_chatops_query(chat_id, clean_text))


@router.post("/feishu/webhook")
async def feishu_webhook(request: Request):
    """飞书 Webhook 唯一入口 — X-Ray 全链路日志 + 转交 LangGraph Agent，秒回 success。"""

    # 🔥🔥🔥 [X-Ray 1] 原始请求接收
    try:
        data = await request.json()
    except Exception as _e:
        print(f"🔥🔥🔥 [X-Ray 1-FAIL] 请求 JSON 解析失败: {_e}")
        return JSONResponse(content={"error": "not_json"})
    print(f"🔥🔥🔥 [X-Ray 1] 收到请求，顶层 keys: {list(data.keys())}")

    # 🔥🔥🔥 [X-Ray 2] 加密拦截
    if "encrypt" in data:
        print("🔥🔥🔥 [X-Ray 2-BLOCK] 收到加密消息！请在飞书后台关闭【消息加解密】！")
        return JSONResponse(content={"error": "need_decrypt"})

    # 🔥🔥🔥 [X-Ray 3] URL 校验 Challenge
    if "challenge" in data:
        print(f"🔥🔥🔥 [X-Ray 3-CHALLENGE] 飞书 URL 校验: challenge={data['challenge']}")
        return JSONResponse(content={"challenge": data["challenge"]})

    # 🔥🔥🔥 [X-Ray 4] 事件结构解析
    try:
        _process_webhook_event(data)
    except Exception as _e:
        import traceback
        traceback.print_exc()
        print(f"⚠️ 飞书Webhook解析异常: {_e}")

    # 🔥🔥🔥 [X-Ray END] 瞬间返回，绝不超时
    return JSONResponse(content={"status": "success"})
