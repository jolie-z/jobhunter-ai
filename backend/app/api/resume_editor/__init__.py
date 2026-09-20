"""
多平台在线简历编辑器 API 模块集合
包含：
- /api/resume-editor/* (editor_routes)
- /api/unified/* (unified_routes)
- /api/platforms/* (platforms_routes)
- /api/agent-map/* (agent_map_routes)
"""

from fastapi import APIRouter

from .agent_map_routes import router as agent_map_router
from .editor_routes import router as editor_router
from .platforms_routes import router as platforms_router
from .unified_routes import router as unified_router

router = APIRouter()
router.include_router(editor_router)
router.include_router(unified_router)
router.include_router(platforms_router)
router.include_router(agent_map_router)

__all__ = ["router", "editor_router", "unified_router", "platforms_router", "agent_map_router"]
