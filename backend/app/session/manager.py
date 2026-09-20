"""
SessionManager — 统一会话管理单例。
提供 check_all() / check_platform() 接口，带内存缓存避免频繁探测。
"""
import time

from .health_checker import check_platform
from .models import SessionState, SessionStatus
from .registry import PLATFORM_CONFIGS


class SessionManager:
    def __init__(self):
        self._cache: dict[str, SessionStatus] = {}
        self._cache_time: dict[str, float] = {}
        self._cache_ttl = 300  # 缓存 5 分钟
        self._prev_state: dict[str, SessionState] = {}  # 用于状态变迁检测

    def check_one(self, platform: str, force: bool = False) -> SessionStatus:
        """检查单个平台，带缓存"""
        now = time.time()
        if not force and platform in self._cache:
            if now - self._cache_time.get(platform, 0) < self._cache_ttl:
                return self._cache[platform]

        config = PLATFORM_CONFIGS.get(platform)
        if not config:
            return SessionStatus(
                platform=platform,
                state=SessionState.UNKNOWN,
                message=f"未知平台: {platform}",
            )

        status = check_platform(config)

        # 保留 last_healthy 历史
        prev = self._cache.get(platform)
        if prev and prev.last_healthy and not status.last_healthy:
            status.last_healthy = prev.last_healthy

        self._cache[platform] = status
        self._cache_time[platform] = now
        return status

    def check_all(self, force: bool = False) -> dict[str, SessionStatus]:
        """检查所有平台"""
        results = {}
        for platform in PLATFORM_CONFIGS:
            results[platform] = self.check_one(platform, force=force)
        return results

    def get_state_transitions(self) -> list[dict]:
        """
        检测状态变迁（healthy → expired），返回需要告警的平台列表。
        调用后自动更新 prev_state。
        """
        transitions = []
        for platform, status in self._cache.items():
            prev = self._prev_state.get(platform)
            if prev and prev != SessionState.EXPIRED and status.state == SessionState.EXPIRED:
                transitions.append({
                    "platform": platform,
                    "display_name": PLATFORM_CONFIGS[platform].display_name,
                    "from": prev.value,
                    "to": status.state.value,
                    "message": status.message,
                    "port": status.port,
                })
            self._prev_state[platform] = status.state
        return transitions

    def get_status_dict(self) -> dict:
        """返回兼容旧前端格式的 dict（platform → bool）+ 新格式详情"""
        statuses = self.check_all()
        result = {}
        for platform, s in statuses.items():
            result[platform] = {
                "available": s.state in (SessionState.HEALTHY, SessionState.DEGRADED),
                "state": s.state.value,
                "message": s.message,
                "last_checked": s.last_checked.isoformat() if s.last_checked else None,
                "last_healthy": s.last_healthy.isoformat() if s.last_healthy else None,
                "port": s.port,
                "profile_path": s.profile_path,
                "browser_type": s.browser_type,
            }
        return result


# 全局单例
session_manager = SessionManager()
