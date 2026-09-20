"""
会话续期心跳 — 对抗平台登录 cookie 的滑动过期。

背景（2026-08 排查结论）：BOSS 的 wt2/zp_at、智联的 at 等核心登录 cookie
服务端只发约 7 天且为滑动续期——必须在过期前再访问一次平台页面才会延长。
autopilot 停跑超过该窗口时，cookie 自然过期，只能重新扫码。

本模块按低频节奏（默认每 2 天一次）用已登录的 profile 静默打开一次各平台
首页：请求携带 cookie，服务端 Set-Cookie 续期滑动窗口后立即优雅关闭。

风险控制：
- 仅当「本平台」端口已有浏览器在监听（任务运行中/用户在使用）→ 跳过该平台，其余平台照常续期。
  旧实现是任一平台活跃即整轮跳过——一个常驻浏览器会让全部平台永远续不上期，
  BOSS 的 7 天滑动 cookie 就是这样无声过期的（2026-09 实测根因）；
- 只访问 login_check_url（平台首页），不做任何自动化操作，行为等同真人随手打开网页；
- 关闭走 CDP Browser.close 优雅退出，保证续期后的 cookie 落盘。
- 各平台端口互不冲突（registry 固定端口），逐平台拉起/关闭串行执行，无并发抢锁风险。
"""
import asyncio
import logging
import time

from .browser import _close_port_gracefully, launch_edge
from .health_checker import probe_port
from .registry import PLATFORM_CONFIGS

logger = logging.getLogger(__name__)

# 四大求职平台（与 get_all_platform_sessions 口径一致，不含小红书）
_RENEWAL_PLATFORMS = ["boss", "zhilian", "51job", "liepin"]

# 打开首页后等待页面加载 + 服务端 Set-Cookie 的时间
_PAGE_SETTLE_SECONDS = 25


def renew_all_sessions() -> None:
    """对四个求职平台做一次静默续期访问。仅跳过端口被占用的那一个平台，其余照常续期。"""
    configs = [PLATFORM_CONFIGS[key] for key in _RENEWAL_PLATFORMS if key in PLATFORM_CONFIGS]
    if not configs:
        return

    # 逐平台判断：本平台端口被占用 → 该平台跳过（renew_platform_session 内部已探测），
    # 不影响其他平台。各平台 profile/端口完全独立，无跨平台牵连。
    renewed, skipped = [], []
    for cfg in configs:
        if renew_platform_session(cfg):
            renewed.append(cfg.display_name)
        else:
            skipped.append(cfg.display_name)
    logger.info(
        f"🔄 [会话续期] 本轮完成：已续期 {renewed or '无'}；跳过/失败 {skipped or '无'}"
        + "（跳过=端口被占用或续期失败，见上方逐条日志）"
    )


def renew_platform_session(config, settle_seconds: int = _PAGE_SETTLE_SECONDS) -> bool:
    """单个平台：用其 profile 打开首页等待续期，再优雅关闭。失败不抛出。"""
    try:
        if probe_port(config.port, timeout=0.4):
            logger.debug(f"[会话续期] {config.name} 端口 {config.port} 已有浏览器，跳过")
            return False
        # 打开 login_check_url（首页）而非 auth_url（登录页）：已登录时首页请求即触发滑动续期
        launch_edge(config, url=config.login_check_url)
        time.sleep(settle_seconds)
        _close_port_gracefully(config.port)
        return True
    except Exception as e:
        logger.warning(f"[会话续期] {config.name} 续期异常: {e}")
        try:
            _close_port_gracefully(config.port)
        except Exception:
            pass
        return False


async def _run_session_renewal():
    """调度入口：线程池中执行同步续期，避免阻塞事件循环。"""
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, renew_all_sessions)
