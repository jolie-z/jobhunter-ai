# services/tts_engine.py
import base64
from openai import AsyncOpenAI
import common.config as _ccfg

class TTSEngine:
    def __init__(self):
        # 配置走动态属性访问（感知配置页保存），按请求实例化时取最新值
        self.client = AsyncOpenAI(api_key=_ccfg.LLM_API_KEY, base_url=_ccfg.LLM_BASE_URL)

    async def async_generate_audio(self, text: str) -> str:
        """接收单句文本，返回 base64 格式的音频"""
        if not text.strip():
            return ""
        try:
            audio_resp = await self.client.audio.speech.create(
                model="tts-1",
                voice="onyx",
                input=text
            )
            # 读取二进制并转为 base64
            return base64.b64encode(audio_resp.content).decode('utf-8')
        except Exception as e:
            print(f"❌ TTS 合成异常: {e}")
            return ""