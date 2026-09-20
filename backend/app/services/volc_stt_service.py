import asyncio
import json
import struct
import uuid

import websockets
from fastapi import WebSocket, WebSocketDisconnect

from app.core.config import settings


async def handle_v3_binary_asr_stream(websocket: WebSocket, response_format: str = "standard"):
    """
    统一的火山引擎 V3 bigmodel_async 二进制流式 ASR 中转引擎
    """
    await websocket.accept()
    print("========== 🎙️ [Volc STT] 新的 WebSocket 连接已建立 ==========")

    if not settings.VOLC_ASR_APPID or not settings.VOLC_ASR_TOKEN:
        err_msg = "未配置火山引擎 API，请降级使用浏览器原生语音识别"
        print(f"⚠️ [Volc STT] {err_msg}")
        await websocket.send_json({"type": "fallback", "message": err_msg} if response_format == "simple" else {"status": "fallback", "message": err_msg})
        await websocket.close()
        return

    clean_appid = str(settings.VOLC_ASR_APPID).strip().strip("'").strip('"')
    clean_token = str(settings.VOLC_ASR_TOKEN).strip().strip("'").strip('"')
    clean_resource = str(settings.VOLC_ASR_RESOURCE_ID).strip().strip("'").strip('"') if settings.VOLC_ASR_RESOURCE_ID else "volc.bigasr.sauc.duration"

    volc_url = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async"
    volc_headers = {
        "X-Api-App-Key": clean_appid,
        "X-Api-Access-Key": clean_token,
        "X-Api-Resource-Id": clean_resource,
        "X-Api-Connect-Id": str(uuid.uuid4()),
    }

    def _pack_config() -> bytes:
        payload = json.dumps({
            "user": {"uid": "stt_user_v3"},
            "audio": {"format": "pcm", "rate": 16000, "channel": 1, "bits": 16},
            "request": {"model_name": "bigmodel"},
        }).encode("utf-8")
        return b"\x11\x10\x10\x00" + struct.pack(">I", len(payload)) + payload

    def _pack_audio(audio_bytes: bytes) -> bytes:
        return b"\x11\x20\x00\x00" + struct.pack(">I", len(audio_bytes)) + audio_bytes

    def _unpack_response(raw: bytes):
        if len(raw) < 8:
            return None
        msg_type = raw[1] >> 4
        flags = raw[1] & 0x0F
        if msg_type != 9:
            return None

        offset = 4 + (4 if flags & 0b0001 else 0)
        if len(raw) < offset + 4:
            return None

        size = struct.unpack(">I", raw[offset:offset + 4])[0]
        offset += 4
        try:
            result = json.loads(raw[offset:offset + size].decode("utf-8"))
            return result.get("result", {}).get("text", "")
        except Exception:
            return None

    try:
        print(f"🚀 [Volc STT] 正在连接火山引擎 WSS: {volc_url}")
        print(f"   - AppKey: {clean_appid}")
        print(f"   - ResourceId: {clean_resource}")

        import ssl
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

        async with websockets.connect(
            volc_url, additional_headers=volc_headers, ping_interval=20, ping_timeout=10, ssl=ssl_ctx,
            # 🌟 绕过 macOS 系统 SOCKS 代理（国内端点直连，与飞书 trust_env=False 策略一致）
            proxy=None,
        ) as volc_ws:
            print("✅ [Volc STT] 火山引擎 WSS 连接成功，发送初始配置...")
            await volc_ws.send(_pack_config())

            async def _forward_audio():
                try:
                    while True:
                        data = await websocket.receive_bytes()
                        await volc_ws.send(_pack_audio(data))
                except (WebSocketDisconnect, Exception):
                    pass

            async def _receive_results():
                try:
                    async for raw in volc_ws:
                        if not isinstance(raw, bytes):
                            continue
                        full_text = _unpack_response(raw)
                        if full_text:
                            if response_format == "simple":
                                await websocket.send_json({"type": "text", "text": full_text})
                            else:
                                await websocket.send_json({"status": "success", "text": full_text, "is_final": False})
                except Exception as e:
                    print(f"⚠️ [STT] 解析异常: {e}")

            await asyncio.gather(_forward_audio(), _receive_results())

    except WebSocketDisconnect:
        print("🔌 [Volc STT] 前端 WebSocket 客户端主动断开连接")
        pass
    except Exception as e:
        err_msg = str(e)
        print(f"❌ [Volc STT] 发生严重错误导致断开/降级: {err_msg}")
        import traceback
        traceback.print_exc()
        try:
            await websocket.send_json({"type": "fallback", "message": err_msg} if response_format == "simple" else {"status": "fallback", "message": err_msg})
        except Exception:
            pass
    finally:
        print("🛑 [Volc STT] 结束当前连接会话")
        try:
            await websocket.close()
        except Exception:
            pass
