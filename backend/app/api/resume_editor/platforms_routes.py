"""
多平台在线简历编辑器 - 平台浏览器状态与会话管理 API 路由 (/api/platforms/*)
"""

import json
import os
import subprocess
import sys
import time

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.session.browser import launch_edge
from app.session.health_checker import probe_port
from app.session.manager import session_manager
from app.session.registry import PLATFORM_CONFIGS

from .common import DATA_DIR, PLATFORMS, PLATFORMS_DIR, UNIFIED_PATH, atomic_write_json
from .platforms_zhilian_heal_routes import router as zhilian_heal_router

router = APIRouter(prefix="/api/platforms", tags=["简历编辑器-平台浏览器"])

PLATFORM_PORTS = {p: PLATFORM_CONFIGS[p].port for p in PLATFORMS}


@router.get("/status")
def platforms_status():
    """探测各平台 Edge 浏览器端口 + 登录状态（Tier2 CDP 轻量启发式，低频快速）。

    注意：本判定基于 Tab URL 启发式，可能与官网真实会话脱节（如 BOSS code=7 场景）；
    需要权威结论请用 POST /api/platforms/status/deep（DOM 级判定）。
    """
    statuses = {}
    for platform in PLATFORMS:
        port = PLATFORM_PORTS[platform]
        online = probe_port(port, timeout=0.6)
        if online:
            s = session_manager.check_one(platform, force=True)
            logged_in = s.state.value in ("healthy", "degraded")
            message = s.message
        else:
            # 离线平台直接短路，不再进 check_one 重复探针
            # （旧实现路由与 check_platform 各探测一次，四平台全离线最坏 ~16s 才返回）
            logged_in = False
            message = "浏览器未启动"
        statuses[platform] = {
            "port": port,
            "online": online,
            "logged_in": logged_in,
            "message": message,
        }

    return JSONResponse(content={"success": True, "platforms": statuses})


@router.post("/status/deep")
def platforms_status_deep():
    """DOM 级登录态深度校验（权威判定，前端「深度校验」按钮专用）。

    逐平台附加浏览器 → 导航 login_check_url → 按 registry login_indicators 判定，
    与 autopilot 预检同一标准（check_login_via_dom），四平台并行执行。
    会把平台浏览器导航到官网首页（短暂占用），故不替代低频轻量的 GET /status。
    """
    from concurrent.futures import ThreadPoolExecutor

    from app.session.health_checker import check_login_via_dom

    def _deep_check(platform: str):
        config = PLATFORM_CONFIGS[platform]
        if not probe_port(config.port, timeout=0.6):
            return {"port": config.port, "online": False, "logged_in": False, "message": "浏览器未启动"}
        status = check_login_via_dom(config)
        return {
            "port": config.port,
            "online": True,
            "logged_in": status.state.value == "healthy",
            "message": status.message,
        }

    with ThreadPoolExecutor(max_workers=len(PLATFORMS)) as executor:
        statuses = dict(zip(PLATFORMS, executor.map(_deep_check, PLATFORMS), strict=False))

    return JSONResponse(content={"success": True, "platforms": statuses, "mode": "dom"})


@router.post("/clear-data")
def clear_platform_data(request: dict = None):
    """清空指定平台（或全部）的采集数据（fields.json 重置为空）"""
    # 仅当请求体未提供 platforms 键时才默认清空全部；
    # 显式传空列表 = 无操作（防止 falsy 误判导致全量清空）
    if not request or not isinstance(request.get("platforms"), list):
        target_platforms = PLATFORMS
    else:
        target_platforms = [p for p in request["platforms"] if p in PLATFORMS]
    cleared = []
    for platform in target_platforms:
        fields_path = os.path.join(DATA_DIR, f"{platform}_fields.json")
        if os.path.exists(fields_path):
            # 清空前备份到 snapshots/（与采集落盘同一保险机制，误清事故不再只能靠 git/回写快照找回）
            try:
                from resume_editor.platforms.browser_common import backup_json_file
                bak = backup_json_file(fields_path, f"{platform}_clear")
                if bak:
                    print(f"[clear-data] {platform} 旧数据已备份: {bak}")
            except Exception as be:
                print(f"[clear-data] {platform} 备份失败（继续清空）: {be}")
            atomic_write_json(fields_path, {})
        # 文件本就不存在 = 已处于清空状态，同样计入
        cleared.append(platform)
    # 只有清空全部平台时才同时清空汇总数据
    if set(cleared) == set(PLATFORMS):
        if os.path.exists(UNIFIED_PATH):
            try:
                from resume_editor.platforms.browser_common import backup_json_file
                backup_json_file(UNIFIED_PATH, "unified_clear")
            except Exception:
                pass
            atomic_write_json(UNIFIED_PATH, {})
    return JSONResponse(content={"success": True, "cleared": cleared})


@router.post("/launch")
def launch_platform_browser(request: dict = None):
    """启动指定平台的 Edge 浏览器"""
    body = request or {}
    platform = body.get("platform", "")
    if platform not in PLATFORM_PORTS:
        return JSONResponse(content={"success": False, "message": f"不支持的平台: {platform}"}, status_code=400)

    config = PLATFORM_CONFIGS[platform]
    try:
        result = launch_edge(config)
    except RuntimeError as e:
        return JSONResponse(content={"success": False, "message": str(e)})

    # 就绪确认：Popen 只是派发进程，Edge 冷启动需要时间；最多等 10 秒探测调试端口，
    # 端口被占用/Edge 启动失败时不再假报成功
    ready = probe_port(config.port, timeout=0.6)
    deadline = time.time() + 10
    while not ready and time.time() < deadline:
        time.sleep(0.5)
        ready = probe_port(config.port, timeout=0.6)
    if ready:
        return JSONResponse(content={
            "success": True,
            "message": f"{result['message']}请在浏览器中完成登录",
        })
    return JSONResponse(content={
        "success": False,
        "message": f"{config.display_name}浏览器已尝试启动，但调试端口 {config.port} 10 秒内未就绪，请稍后点「全部刷新」检查状态",
    })


@router.post("/goto-login")
def goto_login_page(request: dict = None):
    """让已启动的浏览器跳转到对应平台的登录页"""
    body = request or {}
    platform = body.get("platform", "")
    if platform not in PLATFORM_PORTS:
        return JSONResponse(content={"success": False, "message": f"不支持的平台: {platform}"}, status_code=400)

    config = PLATFORM_CONFIGS[platform]
    port = config.port
    login_url = config.login_url or config.auth_url or config.login_check_url

    # 预检：端口无响应绝不进入连接流程——DrissionPage 在端口无响应时会自动拉起
    # 默认浏览器（Chrome），正是「谷歌浏览器被弹出」事故的根因（见 browser_common 模块注释）
    if not probe_port(port, timeout=0.6):
        return JSONResponse(content={
            "success": False,
            "message": f"{config.display_name}浏览器未启动（端口 {port} 无响应），请先在「登录状态」栏点击「启动」",
        })

    # 子进程隔离执行（DrissionPage 异常不拖垮主服务）；端口/URL/脚本目录走 argv 传参，
    # 不再拼进源码字符串；连接配置复用 browser_common.make_options（显式 Edge 路径双保险）
    script = '''
import sys
sys.path.insert(0, sys.argv[3])
from DrissionPage import ChromiumPage
from browser_common import make_options

port, url = int(sys.argv[1]), sys.argv[2]
page = ChromiumPage(make_options(port))
if page.get(url, timeout=12):
    print("OK")
else:
    # 页面加载超时也算导航已下发：浏览器仍在继续打开登录页，不误报失败
    print("OK-SLOW")
'''
    env = {**os.environ, "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"}
    try:
        result = subprocess.run(
            [sys.executable, "-c", script, str(port), login_url, PLATFORMS_DIR],
            capture_output=True, text=True, timeout=25, env=env,
        )
        if result.returncode == 0 and result.stdout.strip().startswith("OK"):
            # macOS 下激活 Edge 窗口，方便用户直接扫码（其他平台跳过，避免 osascript 不存在导致误报失败）
            if sys.platform == "darwin":
                subprocess.run([
                    "osascript", "-e",
                    'tell application "Microsoft Edge" to activate'
                ], capture_output=True, timeout=5)
            return JSONResponse(content={"success": True, "message": "已跳转到登录页，请在浏览器中完成登录"})
        return JSONResponse(content={
            "success": False,
            "message": (result.stdout.strip() or result.stderr.strip() or "跳转失败")[-300:],
        })
    except subprocess.TimeoutExpired:
        return JSONResponse(content={"success": False, "message": "跳转超时，请到浏览器中确认登录页是否已打开"})
    except Exception as e:
        return JSONResponse(content={"success": False, "message": f"跳转失败: {str(e)}"})


# 智联自愈路由已拆至 platforms_zhilian_heal_routes.py（include_router 挂载，行为不变）
router.include_router(zhilian_heal_router)


# ============================================================
# 前程无忧 (51job) 专属自愈 Agent 路由
# ============================================================

@router.post("/51job/agent-diagnose")
def job51_agent_diagnose_route(request: dict):
    """
    派出 Job51HealerAgent 对指定失败模块进行真机深度诊断与根因分析
    Body: { "target_module": "certifications", "error_context": { ... }, "port": PLATFORM_PORTS["51job"] }
    """
    from resume_editor.platforms.job51_healer_agent import Job51HealerAgent
    target_module = request.get("target_module", "")
    error_context = request.get("error_context", {})
    port = request.get("port", PLATFORM_PORTS["51job"])

    agent = Job51HealerAgent(port=port)
    report = agent.diagnose_module(target_module=target_module, error_context=error_context)
    return JSONResponse(content=report)


@router.post("/51job/agent-apply-heal")
def job51_agent_apply_heal_route(request: dict):
    """
    一键执行 Job51HealerAgent 产出的自愈处方
    Body: { "recipe": { ... }, "resume_markdown": "..." }
    """
    from resume_editor.platforms.job51_healer_agent import Job51HealerAgent
    recipe = request.get("recipe", {})
    resume_markdown = request.get("resume_markdown")
    port = request.get("port", PLATFORM_PORTS["51job"])

    agent = Job51HealerAgent(port=port)
    res = agent.apply_recipe(recipe=recipe, resume_markdown=resume_markdown)
    return JSONResponse(content=res)


@router.post("/51job/rollback-snapshot")
def job51_rollback_snapshot_route(request: dict = None):
    """
    一键撤销回滚至指定的 51job 历史快照备份
    """
    from resume_editor.platforms.job51_healer_agent import Job51SnapshotManager
    snapshot_id = (request or {}).get("snapshot_id")
    mgr = Job51SnapshotManager()
    ok, msg = mgr.rollback(snapshot_id=snapshot_id)
    return JSONResponse(content={"ok": ok, "message": msg})


@router.get("/51job/snapshots")
def job51_list_snapshots_route():
    """
    获取 51job 历史数据快照列表（最近 10 份）
    """
    from resume_editor.platforms.job51_healer_agent import Job51SnapshotManager
    mgr = Job51SnapshotManager()
    snaps = mgr.list_snapshots()
    return JSONResponse(content={"ok": True, "snapshots": snaps})


# ============================================================
# BOSS直聘 (Boss) 专属自愈 Agent 路由
# ============================================================

@router.post("/boss/agent-diagnose")
def boss_agent_diagnose_route(request: dict):
    """
    派出 BossHealerAgent 对指定失败模块进行真机深度诊断与根因分析
    Body: { "target_module": "projects", "error_context": { ... }, "port": PLATFORM_PORTS["boss"] }
    """
    from resume_editor.platforms.boss_healer_agent import BossHealerAgent
    target_module = request.get("target_module", "")
    error_context = request.get("error_context", {})
    port = request.get("port", PLATFORM_PORTS["boss"])

    agent = BossHealerAgent(port=port)
    report = agent.diagnose_module(target_module=target_module, error_context=error_context)
    return JSONResponse(content=report)


@router.post("/boss/agent-apply-heal")
def boss_agent_apply_heal_route(request: dict):
    """
    一键执行 BossHealerAgent 产出的自愈处方
    Body: { "recipe": { ... }, "resume_markdown": "..." }
    """
    from resume_editor.platforms.boss_healer_agent import BossHealerAgent
    recipe = request.get("recipe", {})
    resume_markdown = request.get("resume_markdown")
    port = request.get("port", PLATFORM_PORTS["boss"])

    agent = BossHealerAgent(port=port)
    res = agent.apply_recipe(recipe=recipe, resume_markdown=resume_markdown)
    return JSONResponse(content=res)


@router.post("/boss/rollback-snapshot")
def boss_rollback_snapshot_route(request: dict = None):
    """
    一键撤销回滚至指定的 BOSS 历史快照备份
    """
    from resume_editor.platforms.boss_healer_agent import BossSnapshotManager
    snapshot_id = (request or {}).get("snapshot_id")
    mgr = BossSnapshotManager()
    ok, msg = mgr.rollback(snapshot_id=snapshot_id)
    return JSONResponse(content={"ok": ok, "message": msg})


@router.get("/boss/snapshots")
def boss_list_snapshots_route():
    """
    获取 BOSS 历史数据快照列表（最近 10 份）
    """
    from resume_editor.platforms.boss_healer_agent import BossSnapshotManager
    mgr = BossSnapshotManager()
    snaps = mgr.list_snapshots()
    return JSONResponse(content={"ok": True, "snapshots": snaps})


# ============================================================
# 猎聘 (Liepin) 专属自愈 Agent 路由
# ============================================================

@router.post("/liepin/agent-diagnose")
def liepin_agent_diagnose_route(request: dict):
    """
    派出 LiepinHealerAgent 对指定失败模块进行真机深度诊断与根因分析
    Body: { "target_module": "languages", "error_context": { ... }, "port": PLATFORM_PORTS["liepin"] }
    """
    from resume_editor.platforms.liepin_healer_agent import LiepinHealerAgent
    target_module = request.get("target_module", "")
    error_context = request.get("error_context", {})
    # 历史事故修复：此处曾硬编码 9224（小红书的端口），导致猎聘取证连错浏览器或自动拉起 Chrome
    port = request.get("port", PLATFORM_PORTS["liepin"])

    agent = LiepinHealerAgent(port=port)
    report = agent.diagnose_module(target_module=target_module, error_context=error_context)
    return JSONResponse(content=report)


@router.post("/liepin/agent-apply-heal")
def liepin_agent_apply_heal_route(request: dict):
    """
    一键执行 LiepinHealerAgent 产出的自愈处方
    Body: { "recipe": { ... }, "resume_markdown": "..." }
    """
    from resume_editor.platforms.liepin_healer_agent import LiepinHealerAgent
    recipe = request.get("recipe", {})
    resume_markdown = request.get("resume_markdown")
    port = request.get("port", PLATFORM_PORTS["liepin"])

    agent = LiepinHealerAgent(port=port)
    res = agent.apply_recipe(recipe=recipe, resume_markdown=resume_markdown)
    return JSONResponse(content=res)


@router.post("/liepin/rollback-snapshot")
def liepin_rollback_snapshot_route(request: dict = None):
    """
    一键撤销回滚至指定的猎聘历史快照备份
    """
    from resume_editor.platforms.liepin_healer_agent import LiepinSnapshotManager
    snapshot_id = (request or {}).get("snapshot_id")
    mgr = LiepinSnapshotManager()
    ok, msg = mgr.rollback(snapshot_id=snapshot_id)
    return JSONResponse(content={"ok": ok, "message": msg})


@router.get("/liepin/snapshots")
def liepin_list_snapshots_route():
    """
    获取猎聘历史数据快照列表（最近 10 份）
    """
    from resume_editor.platforms.liepin_healer_agent import LiepinSnapshotManager
    mgr = LiepinSnapshotManager()
    snaps = mgr.list_snapshots()
    return JSONResponse(content={"ok": True, "snapshots": snaps})


@router.post("/{platform}/schema-diff")
def get_platform_schema_diff(platform: str, request: dict = None):  # noqa: ARG001  # FastAPI body 参数
    """
    获取指定平台的 Schema 差分比对报告（对比当前采集数据与已知模版）
    """
    if platform not in PLATFORMS:
        return JSONResponse(content={"success": False, "message": f"不支持的平台: {platform}"}, status_code=400)
    from resume_editor.schema_diff_engine import diff_platform_schema
    fields_file = os.path.join(DATA_DIR, f"{platform}_fields.json")
    if not os.path.exists(fields_file):
        return JSONResponse(content={"success": False, "message": f"{platform}_fields.json 不存在"})
    with open(fields_file, encoding="utf-8") as f:
        fresh_data = json.load(f)
    diff = diff_platform_schema(platform, fresh_data)
    return JSONResponse(content={"success": True, "diff": diff})


@router.post("/{platform}/apply-schema-patch")
def apply_platform_schema_patch(platform: str, request: dict):
    """
    用户确认后，一键将 Schema 变动对齐到本地模版文件中
    Body: { "diff_result": { ... } }
    """
    if platform not in PLATFORMS:
        return JSONResponse(content={"success": False, "message": f"不支持的平台: {platform}"}, status_code=400)
    from resume_editor.schema_diff_engine import apply_schema_patch
    diff_result = request.get("diff_result", {})
    fields_file = os.path.join(DATA_DIR, f"{platform}_fields.json")
    fresh_data = None
    if os.path.exists(fields_file):
        with open(fields_file, encoding="utf-8") as f:
            fresh_data = json.load(f)
    res = apply_schema_patch(platform, diff_result, fresh_data=fresh_data)
    return JSONResponse(content=res)
