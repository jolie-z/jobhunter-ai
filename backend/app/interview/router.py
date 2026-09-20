import asyncio
import json
import ssl
import time
import uuid

import websockets
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

import common.config as _ccfg
from app.interview.prompts import build_system_prompt
from app.interview.utils import pack_audio, pack_config, unpack_response
from common.config import get_openai_client

# 延迟导入或直接导入对应的 Engine
from services.llm_engine import LLMEngine
from services.tts_engine import TTSEngine

router = APIRouter()

async def generate_and_send_audio(text: str, ws: WebSocket, tts_engine: TTSEngine):
    """单独的音频生成与发送任务"""
    try:
        audio_base64 = await tts_engine.async_generate_audio(text)
        if audio_base64:
            if ws.client_state == WebSocketState.CONNECTED:
                await ws.send_json({"type": "audio", "audio_base64": audio_base64})
                print(f"  [👄] 语音块已下发: {text[:10]}...")
        elif ws.client_state == WebSocketState.CONNECTED:
            # 🌟 服务端 TTS 不可用（如当前 MiMo 端点无 audio/speech 能力，404）时
            # 降级为浏览器原生合成，避免面试中 AI 的句子整段静音只剩字幕
            await ws.send_json({"type": "native_tts", "text": text})
            print(f"  [🗣️] TTS 不可用，已降级浏览器合成: {text[:10]}...")
    except asyncio.CancelledError:
        print(f"  [⏹️] 语音块生成任务被及时取消（避免浪费 Token）: {text[:10]}...")
        raise
    except Exception as e:
        print(f"  [⚠️] 语音生成异常: {e}")

async def speak_fallback(text: str, ws: WebSocket):
    """开场白与兜底同步转异步的播报机制"""
    try:
        import base64
        audio_resp = await asyncio.to_thread(
            get_openai_client().audio.speech.create,
            model="tts-1",
            voice="onyx",
            input=text
        )

        if ws.client_state == WebSocketState.CONNECTED:
            await ws.send_json({"type": "audio", "audio_base64": base64.b64encode(audio_resp.content).decode('utf-8')})
    except asyncio.CancelledError:
        print("  [⏹️] 开场语音生成任务被取消")
        raise
    except Exception as e:
        if "close" in str(e).lower() or "disconnect" in str(e).lower():
            pass
        else:
            try:
                if ws.client_state == WebSocketState.CONNECTED:
                    await ws.send_json({"type": "native_tts", "text": text})
            except Exception:
                pass


@router.websocket("/{job_id}")
async def interview_websocket(websocket: WebSocket, job_id: str):
    await websocket.accept()
    print(f"\n[🟢 WS] 考场大门已锁死，面试官入座！岗位 ID: {job_id}")

    chat_history = []
    last_voice_time = time.time()
    ai_speaking = False
    is_paused = False

    # 🌟 追踪当前 WebSocket 会话中派发的所有异步语音生成与大模型思考任务
    # 防止客户端断开或用户抢话打断后，后台还在继续跑 TTS 白烧 Token
    active_speech_tasks: set[asyncio.Task] = set()

    def spawn_speech_task(coro):
        task = asyncio.create_task(coro)
        active_speech_tasks.add(task)
        task.add_done_callback(active_speech_tasks.discard)
        return task

    def cancel_all_speech_tasks():
        canceled_count = 0
        for t in list(active_speech_tasks):
            if not t.done():
                t.cancel()
                canceled_count += 1
        active_speech_tasks.clear()
        if canceled_count > 0:
            print(f"  [🧹] 已取消 {canceled_count} 个后台语音/思考协程，杜绝 Token 浪费！")

    use_volc = bool(_ccfg.VOLC_ASR_APPID and _ccfg.VOLC_ASR_TOKEN)

    async def connect_volc():
        clean_appid = str(_ccfg.VOLC_ASR_APPID).strip().strip("'").strip('"')
        clean_token = str(_ccfg.VOLC_ASR_TOKEN).strip().strip("'").strip('"')
        clean_resource = str(_ccfg.VOLC_ASR_RESOURCE_ID).strip().strip("'").strip('"') if _ccfg.VOLC_ASR_RESOURCE_ID else "volc.bigasr.sauc.duration"
        volc_headers = {
            "X-Api-App-Key": clean_appid,
            "X-Api-Access-Key": clean_token,
            "X-Api-Resource-Id": clean_resource,
            "X-Api-Connect-Id": str(uuid.uuid4())
        }

        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

        ws = await websockets.connect(
            "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async",
            additional_headers=volc_headers,
            ssl=ssl_context,
            # 🌟 火山为国内端点，绕过 macOS 系统 SOCKS 代理（websockets 15 会自动读系统代理，
            # 但未装 python-socks 时直接报错），与飞书调用 trust_env=False 的策略保持一致
            proxy=None,
        )
        await ws.send(pack_config())
        return ws

    volc_ws = None
    if use_volc:
        try:
            volc_ws = await connect_volc()
            print("  [✅] 成功连接到火山引擎语音识别大模型！")
        except Exception as e:
            print(f"  [❌] 火山引擎连接失败，原因: {str(e)}")

    if not volc_ws:
        await websocket.send_json({"type": "control", "status": "fallback"})

    async def think_and_reply(history, ws):
        nonlocal ai_speaking
        try:
            # 🌟 history 就是真实的 chat_history 引用：修剪与 AI 回复都必须写回它，
            # 否则面试官永远看不到自己上一轮问了什么（会话上下文断裂）
            if len(history) > 11:
                system_msg = history[0]
                history_to_keep = history[-10:]
                history.clear()
                history.extend([system_msg] + history_to_keep)
                print("  [🧹] 触发滑动窗口修剪，保持极速低成本响应！")

            messages_to_send = list(history)

            if len(history) > 0 and history[-1]["role"] == "user":
                user_msg = history[-1]["content"]
                if any(kw in user_msg for kw in ["下一题", "下一个", "跳过", "弱点", "弱项", "继续"]):
                    messages_to_send.append({
                        "role": "system",
                        "content": "【阅后即焚指令】：候选人想跳过本题。请回复：'已为你记录该弱点项。我们来看下一个问题...'，然后抛出新题。禁止打分！"
                    })
                elif any(kw in user_msg for kw in ["重试", "重练", "再来", "重新", "重答"]):
                    messages_to_send.append({
                        "role": "system",
                        "content": "【阅后即焚指令】：候选人想重新回答。请简短鼓励并让他开始。禁止打分！"
                    })

            print("  [🧠] 面试官正在思考 (启用极速流式引擎)...")

            ai_speaking = True
            llm_engine = LLMEngine()
            tts_engine = TTSEngine()

            buffer = ""
            full_ai_text = ""
            punctuation_marks = {'，', '。', '！', '？', '；', '?', '!'}

            async for chunk_text in llm_engine.async_stream_generate(messages_to_send):
                buffer += chunk_text
                full_ai_text += chunk_text

                clean_buffer = buffer.replace("**", "").replace("*", "").replace("#", "")

                if clean_buffer and clean_buffer[-1] in punctuation_marks:
                    sentence_to_speak = clean_buffer.strip()
                    buffer = ""

                    if sentence_to_speak:
                        if ws.client_state == WebSocketState.CONNECTED:
                            await ws.send_json({"type": "text", "role": "ai", "content": sentence_to_speak})
                        spawn_speech_task(generate_and_send_audio(sentence_to_speak, ws, tts_engine))

            clean_buffer = buffer.replace("**", "").replace("*", "").replace("#", "").strip()
            if clean_buffer:
                if ws.client_state == WebSocketState.CONNECTED:
                    await ws.send_json({"type": "text", "role": "ai", "content": clean_buffer})
                spawn_speech_task(generate_and_send_audio(clean_buffer, ws, tts_engine))

            history.append({"role": "assistant", "content": full_ai_text})
            print(f"  [🤖] 思考完毕！完整回复: {full_ai_text[:30]}...")

        except Exception as e:
            print(f"❌ 大脑短路: {e}")
        finally:
            ai_speaking = False

    committed_user_text = ""
    current_volc_sentence = ""

    async def listen_frontend():
        nonlocal last_voice_time, committed_user_text, current_volc_sentence, is_paused
        try:
            while True:
                msg = await websocket.receive()
                if "bytes" in msg:
                    if volc_ws:
                        try:
                            await volc_ws.send(pack_audio(msg["bytes"]))
                        except Exception:
                            pass
                elif "text" in msg:
                    data = json.loads(msg["text"])
                    if data.get("action") == "stop":
                        break
                    elif data.get("action") == "pause":
                        is_paused = data.get("state", False)
                        print(f"  [⏸️] 面试已{'暂停' if is_paused else '恢复'}")
                    elif data.get("action") == "interrupt":
                        nonlocal ai_speaking
                        ai_speaking = False
                        cancel_all_speech_tasks()
                        print("  [🛑] 收到前端抢话信号，强行终止当前回答状态并取消未完成 TTS 任务")
                    elif data.get("type") == "init":
                        sys_prompt_base = data.get("system_prompt", "你是一个面试官。")
                        role = data.get("role", "business")
                        style = data.get("style", "coach")
                        drill_question = (data.get("drill_question") or "").strip()
                        drill_answer = (data.get("drill_answer") or "").strip()

                        sys_prompt, welcome = build_system_prompt(
                            sys_prompt_base, role, style, drill_question, drill_answer
                        )

                        chat_history.append({"role": "system", "content": sys_prompt})
                        chat_history.append({"role": "assistant", "content": welcome})
                        if websocket.client_state == WebSocketState.CONNECTED:
                            await websocket.send_json({"type": "text", "role": "ai", "content": welcome})
                        spawn_speech_task(speak_fallback(welcome, websocket))

                    elif data.get("type") == "user_fallback_text":
                        text = data.get("text")
                        if text:
                            committed_user_text += text
                            full_text = committed_user_text + current_volc_sentence
                            if websocket.client_state == WebSocketState.CONNECTED:
                                await websocket.send_json({"type": "user_text_replace", "role": "user", "content": full_text})
                            last_voice_time = time.time()
        except WebSocketDisconnect:
            pass

    async def listen_volc():
        nonlocal last_voice_time, committed_user_text, current_volc_sentence, ai_speaking, volc_ws
        while True:
            if not volc_ws:
                await asyncio.sleep(0.1)
                if use_volc:
                    try:
                        volc_ws = await connect_volc()
                        print("  [🔄] 火山引擎断线重连成功！")
                    except Exception as e:
                        print(f"  [⚠️] 火山引擎重连失败 (防刷屏延时1秒): {e}")
                        await asyncio.sleep(1.0)
                continue
            try:
                async for raw in volc_ws:
                    if not isinstance(raw, bytes):
                        continue
                    text = unpack_response(raw)
                    if ai_speaking or is_paused:
                        committed_user_text = ""
                        current_volc_sentence = ""
                        continue
                    if text:
                        if len(text) < len(current_volc_sentence) / 2 or (len(current_volc_sentence) > 0 and text[0] != current_volc_sentence[0]):
                            if current_volc_sentence:
                                committed_user_text += current_volc_sentence + "，"
                            current_volc_sentence = text
                        else:
                            current_volc_sentence = text
                        full_text = committed_user_text + current_volc_sentence
                        if websocket.client_state == WebSocketState.CONNECTED:
                            await websocket.send_json({"type": "user_text_replace", "role": "user", "content": full_text})
                        last_voice_time = time.time()
            except Exception:
                pass
            volc_ws = None

    async def silence_monitor():
        nonlocal last_voice_time, committed_user_text, current_volc_sentence, ai_speaking, is_paused, volc_ws
        while True:
            await asyncio.sleep(0.2)
            full_text = committed_user_text + current_volc_sentence

            if full_text and (time.time() - last_voice_time >= 4.0) and not ai_speaking and not is_paused:
                ai_speaking = True
                final_text = full_text.strip("，")
                print(f"  [👂] 候选人回答完毕 (严格4.0秒截断): {final_text}")
                chat_history.append({"role": "user", "content": final_text})

                committed_user_text = ""
                current_volc_sentence = ""

                if volc_ws:
                    try:
                        await volc_ws.close()
                    except Exception:
                        pass
                    volc_ws = None

                # 🌟 传真实 chat_history 引用（非拷贝）：AI 的回答必须写回会话历史，
                # 否则下一轮 LLM 看不到自己问过什么，多轮追问退化为单轮失忆模式
                spawn_speech_task(think_and_reply(chat_history, websocket))

    tasks = [
        asyncio.create_task(listen_frontend()),
        asyncio.create_task(silence_monitor()),
        asyncio.create_task(listen_volc())
    ]
    # 🌟 只等前端监听任务退出（stop 指令或断连）；
    # 另两个是无限循环任务，gather 会永远挂起导致连接任务泄漏
    frontend_task = tasks[0]
    try:
        await frontend_task
    finally:
        for t in tasks[1:]:
            t.cancel()
        cancel_all_speech_tasks()
        await asyncio.gather(*tasks[1:], return_exceptions=True)

    if volc_ws:
        try:
            await volc_ws.close()
        except Exception:
            pass

from pathlib import Path  # noqa: E402

from fastapi import BackgroundTasks  # noqa: E402
from fastapi.responses import HTMLResponse  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.interview.render import render_waiting_page  # noqa: E402
from app.interview.schemas import GeneratePDFRequest  # noqa: E402
from app.interview.service import generate_handbook_action  # noqa: E402
from app.services.feishu_service import extract_record_id  # noqa: E402

http_router = APIRouter()

@http_router.get("/api/get_pdf/{job_id}")
@http_router.get("/get_pdf/{job_id}")
async def get_pdf_endpoint(job_id: str):
    """
    活链接代理：如果 H5 文件存在直接返回网页；
    如果后台还在生成中，返回一个带动画的友好等待页面，并每隔 3 秒自动刷新重试。
    """
    pure_record_id = extract_record_id(job_id)
    html_filename = f"handbook_{pure_record_id}.html"

    base_dir = getattr(settings, "BASE_DIR", Path(__file__).parent.parent.parent)
    html_path = Path(base_dir) / "static" / "pdfs" / html_filename

    def _read_html():
        if html_path.exists():
            return html_path.read_text(encoding="utf-8")
        return None

    content = await asyncio.to_thread(_read_html)

    if content:
        return HTMLResponse(content=content)
    else:
        waiting_html = render_waiting_page()
        return HTMLResponse(content=waiting_html)

@http_router.post("/api/generate_handbook_pdf")
async def generate_handbook_pdf(payload: GeneratePDFRequest, background_tasks: BackgroundTasks):
    # 🌟 核心提速：接口瞬间返回，把耗时的 PDF 生成任务丢进后台工作线程默默执行！
    background_tasks.add_task(generate_handbook_action, payload.job_id)
    return {"status": "success", "message": "H5 锦囊生成任务已转入后台执行"}
