import json
import struct


def pack_config() -> bytes:
    """打包火山引擎语音识别配置"""
    payload = json.dumps({
        "user": {"uid": "user_1"},
        "audio": {"format": "pcm", "rate": 16000, "channel": 1, "bits": 16},
        "request": {"model_name": "bigmodel"},
    }).encode("utf-8")
    return b"\x11\x10\x10\x00" + struct.pack(">I", len(payload)) + payload

def pack_audio(audio_bytes: bytes) -> bytes:
    """打包前端传来的 PCM 音频流用于火山识别"""
    return b"\x11\x20\x00\x00" + struct.pack(">I", len(audio_bytes)) + audio_bytes

def unpack_response(raw: bytes) -> str | None:
    """解包火山引擎的二进制响应，提取文本"""
    if len(raw) < 8:
        return None
    header = raw[:4]
    if header[1] >> 4 != 9:
        return None
    offset = 8 if (header[1] & 0x0F) & 0b0001 else 4
    if len(raw) < offset + 4:
        return None
    payload_size = struct.unpack(">I", raw[offset:offset + 4])[0]
    try:
        data = json.loads(raw[offset + 4: offset + 4 + payload_size].decode("utf-8"))
        return data.get("result", {}).get("text", "")
    except Exception:
        return None
