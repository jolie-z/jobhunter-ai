"""投递失败自愈动作库（自愈体系 L2）：失败瞬间自动执行安全修复动作。

与 L1 分诊（failure_triage.py）的分工：
- L1 在「发射前」决定要不要试（持久性不试、暂时性限次试）；
- L2 在「失败后」主动消除环境类故障，让下一次发射大概率成功。

动作库（全部是可安全重放的环境操作，不碰业务数据）：
1. restart_browser  重启平台专用 Edge（优雅关闭落盘登录态 → 重新拉起）：
   根治僵尸标签页（NO_SUCH_TAB）、页面元素失效（NoRectError）等浏览器态故障；
2. probe_login      登录态探测（顺带续期滑动 cookie）；
3. refill_materials 物料补齐（海投 PDF/长图按当前启用简历重新渲染挂载）。

自愈结果记入 delivery_failures 台账的 heal_log 字段，供 L3 诊断官与前端展示。
"""

import asyncio
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# 错误关键词 → 自愈动作映射（未命中的错误不做动作，交给 L1 分诊/人工）
HEAL_ACTIONS = {
    "restart_browser": ("tab", "标签页", "norect", "页面", "浏览器", "browser", "崩溃"),
}


def pick_heal_action(error: str) -> str:
    """按错误文本挑选自愈动作；无需动作返回空串。"""
    text = str(error or "").lower()
    for action, keywords in HEAL_ACTIONS.items():
        if any(k in text for k in keywords):
            return action
    # 引擎吞掉细节统一报「执行失败」时，浏览器态故障是大头，重启无害且大概率有效
    if "引擎执行失败" in str(error or ""):
        return "restart_browser"
    return ""


async def restart_platform_browser(platform: str) -> tuple:
    """重启平台专用浏览器：close_edge 优雅关闭（登录态落盘）→ launch_edge 重新拉起。

    Returns:
        (是否成功, 说明)。平台未知/未配置返回 (False, 原因)。
    """
    from app.session.browser import close_edge, launch_edge
    from app.session.registry import resolve_platform

    cfg = resolve_platform((platform or "").lower())
    if not cfg:
        return False, f"未知平台 {platform}，无法重启浏览器"

    def _restart():
        closed = close_edge(cfg)
        # 关闭后稍等端口释放
        import time
        time.sleep(2)
        launch_edge(cfg, url=cfg.login_check_url or None)
        return closed

    try:
        await asyncio.to_thread(_restart)
        logger.info(f"🩹 [SelfHeal] {cfg.display_name} 浏览器已重启（旧进程退出，新实例拉起）")
        return True, f"{cfg.display_name} 浏览器已重启"
    except Exception as e:
        logger.warning(f"🩹 [SelfHeal] {platform} 浏览器重启失败: {e}")
        return False, f"浏览器重启失败: {str(e)[:80]}"


async def run_self_heal(platform: str, error: str) -> dict:
    """失败登记后自动执行匹配的自愈动作。返回 {action, success, detail} 或 None。"""
    action = pick_heal_action(error)
    if not action:
        return {}
    if action == "restart_browser":
        ok, detail = await restart_platform_browser(platform)
        return {"action": action, "success": ok, "detail": detail,
                "at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    return {}


def append_heal_log(job_id: str, heal: dict) -> None:
    """把一次自愈记录追加进失败台账的 heal_log（失败条目被清除时自然消失）。"""
    if not job_id or not heal:
        return
    try:
        from app.automation import run_snapshot as _rs
        with _rs._lock:
            entry = _rs._delivery_failures.get(str(job_id))
            if entry is not None:
                log = entry.setdefault("heal_log", [])
                log.append(heal)
                # 只保留最近 5 条，防止台账膨胀
                del log[:-5]
                _rs._save_to_db()
    except Exception as e:
        logger.warning(f"[SelfHeal] 自愈台账记录异常: {e}")
