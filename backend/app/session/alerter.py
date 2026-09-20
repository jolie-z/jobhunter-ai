"""
会话过期预警器 — 状态变迁时通过飞书通知用户。
4 小时去重，避免刷屏。
"""
import time


class SessionAlerter:
    def __init__(self, cooldown_seconds: int = 4 * 3600):
        self._last_alert: dict[str, float] = {}
        self._cooldown = cooldown_seconds

    async def alert_if_needed(self, transitions: list[dict]) -> None:
        """对状态变迁列表逐条检查并发送告警"""
        for t in transitions:
            platform = t["platform"]
            now = time.time()
            last = self._last_alert.get(platform, 0)
            if now - last < self._cooldown:
                continue  # 冷却期内不重复告警

            self._last_alert[platform] = now
            await self._send_alert(t)

    async def _send_alert(self, transition: dict) -> None:
        display_name = transition["display_name"]
        port = transition.get("port", "?")
        message = (
            f"⚠️ 【{display_name}】登录态已失效！\n"
            f"状态变迁: {transition['from']} → {transition['to']}\n"
            f"详情: {transition['message']}\n"
            f"端口: {port}\n"
            f"请打开对应浏览器重新登录，登录后系统将自动恢复。"
        )

        # 飞书通知
        try:
            from common.config import FEISHU_ALERT_RECEIVE_ID
            if FEISHU_ALERT_RECEIVE_ID:
                from app.core.feishu_messaging import send_feishu_message
                await send_feishu_message(
                    receive_id=FEISHU_ALERT_RECEIVE_ID,
                    text=message,
                    receive_id_type="chat_id" if FEISHU_ALERT_RECEIVE_ID.startswith("oc_") else "open_id",
                )
                print(f"📨 会话告警已发送: {display_name}")
                return
        except ImportError:
            pass
        except Exception as e:
            print(f"⚠️ 飞书告警发送失败: {e}")

        # 兜底：打印到控制台
        print(f"\n{'='*50}")
        print("🚨 会话过期告警")
        print(message)
        print(f"{'='*50}\n")


# 全局单例
session_alerter = SessionAlerter()
