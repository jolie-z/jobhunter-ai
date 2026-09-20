"""
多平台在线简历编辑器 - 智联招聘自愈路由子模块 (/api/platforms/zhilian/*)

自 platforms_routes.py 拆出（500 行红线瘦身）：经 include_router 挂载，
路由路径/请求契约与拆分前完全一致。
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.session.registry import PLATFORM_CONFIGS

from .common import PLATFORMS

router = APIRouter(tags=["简历编辑器-平台浏览器"])

PLATFORM_PORTS = {p: PLATFORM_CONFIGS[p].port for p in PLATFORMS}


@router.post("/zhilian/probe-schema")
def zhilian_probe_schema_route(request: dict = None):
    """
    0-Token 极速反射探测智联官网当前 Vuex 模块、字段与字典结构，并返回差分报告
    """
    from resume_editor.platforms.zhilian_probe_healer import probe_official_schema
    # 默认端口从 registry 取（全项目唯一配置区），防止硬编码漂移
    port = (request or {}).get("port", PLATFORM_PORTS["zhilian"])
    report = probe_official_schema(port=port)
    return JSONResponse(content=report)


@router.post("/zhilian/self-heal")
def zhilian_self_heal_route(request: dict):
    """
    人机协同确认自愈：备份快照，并将选中的新增字段写入本地数据模型
    Body: { "selected_diffs": [...], "use_llm": false }
    """
    from resume_editor.platforms.zhilian_probe_healer import execute_self_heal
    selected_diffs = request.get("selected_diffs", [])
    use_llm = bool(request.get("use_llm", False))
    resume_markdown = request.get("resume_markdown")
    res = execute_self_heal(selected_diffs=selected_diffs, use_llm=use_llm, resume_markdown=resume_markdown)
    return JSONResponse(content=res)


@router.post("/zhilian/rollback-snapshot")
def zhilian_rollback_snapshot_route(request: dict = None):
    """
    一键撤销回滚至指定的历史快照备份（默认回退到最近一份）
    Body: { "snapshot_id": "zhilian_writeback_xxx.bak.json" }
    """
    from resume_editor.platforms.zhilian_probe_healer import SnapshotManager
    snapshot_id = (request or {}).get("snapshot_id")
    mgr = SnapshotManager()
    ok, msg = mgr.rollback(snapshot_id=snapshot_id)
    return JSONResponse(content={"ok": ok, "message": msg})


@router.get("/zhilian/snapshots")
def zhilian_list_snapshots_route():
    """
    获取智联历史数据快照列表（最近 10 份）
    """
    from resume_editor.platforms.zhilian_probe_healer import SnapshotManager
    mgr = SnapshotManager()
    snaps = mgr.list_snapshots()
    return JSONResponse(content={"ok": True, "snapshots": snaps})


@router.post("/zhilian/agent-diagnose")
def zhilian_agent_diagnose_route(request: dict):
    """
    派出 ZhilianWritebackHealerAgent 对指定失败模块进行真机深度诊断与根因分析
    Body: { "target_module": "certificates", "error_context": { ... }, "port": PLATFORM_PORTS["zhilian"] }
    """
    from resume_editor.platforms.zhilian_healer_agent import ZhilianHealerAgent
    target_module = request.get("target_module", "")
    error_context = request.get("error_context", {})
    port = request.get("port", PLATFORM_PORTS["zhilian"])

    agent = ZhilianHealerAgent(port=port)
    report = agent.diagnose_module(target_module=target_module, error_context=error_context)
    return JSONResponse(content=report)


@router.post("/zhilian/agent-apply-heal")
def zhilian_agent_apply_heal_route(request: dict):
    """
    一键执行 ZhilianWritebackHealerAgent 产出的自愈处方
    Body: { "recipe": { ... }, "resume_markdown": "..." }
    """
    from resume_editor.platforms.zhilian_healer_agent import ZhilianHealerAgent
    recipe = request.get("recipe", {})
    resume_markdown = request.get("resume_markdown")
    port = request.get("port", PLATFORM_PORTS["zhilian"])

    agent = ZhilianHealerAgent(port=port)
    res = agent.apply_recipe(recipe=recipe, resume_markdown=resume_markdown)
    return JSONResponse(content=res)
