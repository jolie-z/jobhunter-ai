from fastapi import APIRouter, HTTPException, WebSocket

from app.copilot import service
from app.copilot.schemas import (
    CheckIntelRequest,
    CopilotChatRequest,
    InterviewRequest,
    VoiceCopilotChatRequest,
)
from app.services import volc_stt_service

router = APIRouter()

@router.post("/api/copilot_chat")
async def copilot_chat_endpoint(payload: CopilotChatRequest):
    try:
        return await service.process_copilot_chat(payload)
    except ValueError as ve:
        raise HTTPException(status_code=500, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Copilot Chat 服务暂时不可用: {str(e)}")


@router.post("/api/voice_copilot/chat")
async def voice_copilot_chat_endpoint(payload: VoiceCopilotChatRequest):
    try:
        return await service.process_voice_copilot_chat(payload)
    except ValueError as ve:
        raise HTTPException(status_code=500, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM 调用失败: {str(e)}")

# 统一接管两个高度重复的 WebSockets 路由
@router.websocket("/ws/stt")
async def ws_stt_legacy_endpoint(websocket: WebSocket):
    await volc_stt_service.handle_v3_binary_asr_stream(websocket, response_format="simple")

@router.websocket("/api/ws/asr")
async def ws_asr_proxy_endpoint(websocket: WebSocket):
    await volc_stt_service.handle_v3_binary_asr_stream(websocket, response_format="standard")

@router.post("/api/v1/check_intel_update")
async def check_intel_update(req: CheckIntelRequest):
    try:
        return await service.check_intel_update_action(req)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/api/v1/init_interviewer")
async def init_interviewer(req: InterviewRequest):
    try:
        return await service.init_interviewer_action(req)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
