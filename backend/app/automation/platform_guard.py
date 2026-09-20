"""
PlatformGuard - 平台操作守卫类（SQLite 版）

用于控制各平台的爬虫和投递操作，防止并发触发反爬机制。
复用 autopilot.db（SQLite），与现有 automation/db.py 架构保持一致。

核心策略：
1. 同一时间只允许一个平台在执行爬虫或投递
2. 爬虫和投递之间需要冷却时间（可配置）
3. 记录每次操作的时间戳，用于后续查询和分析
"""

import logging
import sqlite3
import time

logger = logging.getLogger(__name__)

# 与 automation/db.py 共用同一个库文件，路径定义收敛到一处
from app.automation.db import DB_PATH  # noqa: E402


def init_platform_status_table():
    """创建 platform_status 表（在 init_autopilot_db 中调用）"""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS platform_status (
                    platform TEXT PRIMARY KEY,
                    status TEXT NOT NULL DEFAULT 'idle',
                    last_operation_start INTEGER,
                    last_operation_end INTEGER,
                    operations_count INTEGER NOT NULL DEFAULT 0
                )
            ''')
            conn.commit()
    except Exception as e:
        logger.error(f"初始化 platform_status 表失败: {e}", exc_info=True)


class PlatformGuard:
    """
    平台操作 Guard：基于 SQLite 状态表的互斥控制

    功能：
    - 检查是否可以开始爬虫/投递
    - 更新平台状态
    - 获取历史操作记录
    """

    # 默认冷却策略（单位：分钟）
    DEFAULT_COOLDOWN_POLICY = {
        "boss": {"scraping": 90, "delivery": 180, "between_platforms": 60},
        "51job": {"scraping": 60, "delivery": 120, "between_platforms": 45},
        "liepin": {"scraping": 45, "delivery": 90, "between_platforms": 30},
        "zhilian": {"scraping": 30, "delivery": 60, "between_platforms": 20},
    }

    async def can_start_scraping(self, platform: str) -> tuple[bool, str]:
        """
        检查是否可以开始爬虫

        规则：
        1. 如果最近有投递操作，需等待 delivery 冷却时间
        2. 今日操作次数不超过上限（20 次）

        Returns:
            (是否允许，拒绝原因说明)
        """
        record = self._get_or_create_record(platform)

        now_ms = int(time.time() * 1000)

        # 检查今日操作次数
        if record["operations_count"] >= 20:
            return False, f"今日已达抓取上限 ({record['operations_count']} 次)"

        # 检查是否有最近的投递操作
        if record["last_operation_end"] and record["status"] == "delivering":
            minutes_since = (now_ms - record["last_operation_end"]) / 60000
            cooldown = self.DEFAULT_COOLDOWN_POLICY.get(platform, {}).get("delivery", 120)

            if minutes_since < cooldown:
                remaining = cooldown - minutes_since
                return False, f"近期有投递记录，还需等待 {remaining:.0f} 分钟"

        return True, "OK"

    async def can_start_delivery(self, platform: str) -> tuple[bool, str]:
        """
        检查是否可以开始投递

        规则：
        1. 如果最近有爬虫操作，需等待 scraping 冷却时间
        2. 今日操作次数不超过上限（50 次）

        Returns:
            (是否允许，拒绝原因说明)
        """
        record = self._get_or_create_record(platform)

        now_ms = int(time.time() * 1000)

        # 检查今日操作次数
        if record["operations_count"] >= 50:
            return False, f"今日已达投递上限 ({record['operations_count']} 次)"

        # 检查是否有最近的爬虫操作
        if record["last_operation_end"] and record["status"] == "scraping":
            minutes_since = (now_ms - record["last_operation_end"]) / 60000
            cooldown = self.DEFAULT_COOLDOWN_POLICY.get(platform, {}).get("scraping", 60)

            if minutes_since < cooldown:
                remaining = cooldown - minutes_since
                return False, f"近期有爬虫记录，还需等待 {remaining:.0f} 分钟"

        return True, "OK"

    async def check_between_platforms(self, current_platform: str,
                                      previous_platform: str) -> tuple[bool, str]:
        """
        检查不同平台之间的切换冷却时间

        Returns:
            (是否允许，拒绝原因说明)
        """
        prev_record = self._get_or_create_record(previous_platform)

        if not prev_record["last_operation_end"]:
            return True, "上一平台无操作记录，无需等待"

        now_ms = int(time.time() * 1000)
        minutes_since_prev = (now_ms - prev_record["last_operation_end"]) / 60000
        cooldown = self.DEFAULT_COOLDOWN_POLICY.get(current_platform, {}).get(
            "between_platforms", 30
        )

        if minutes_since_prev < cooldown:
            remaining = cooldown - minutes_since_prev
            return False, f"刚完成 {previous_platform} 平台操作，还需等待 {remaining:.0f} 分钟"

        return True, "OK"

    def update_platform_status(self, platform: str, operation: str):
        """
        更新平台状态

        Args:
            platform: 平台名称
            operation: "start" 或 "end"
        """
        now_ms = int(time.time() * 1000)

        try:
            with sqlite3.connect(DB_PATH) as conn:
                cursor = conn.cursor()

                if operation == "start":
                    cursor.execute(
                        "UPDATE platform_status SET status = 'scraping', last_operation_start = ? WHERE platform = ?",
                        (now_ms, platform)
                    )
                elif operation == "end":
                    cursor.execute(
                        "UPDATE platform_status SET status = 'idle', last_operation_end = ?, operations_count = operations_count + 1 WHERE platform = ?",
                        (now_ms, platform)
                    )

                conn.commit()
        except Exception as e:
            logger.error(f"更新平台状态失败 [{platform}]: {e}", exc_info=True)

    def _get_or_create_record(self, platform: str) -> dict:
        """获取或创建平台状态记录"""
        try:
            with sqlite3.connect(DB_PATH) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()

                cursor.execute(
                    "SELECT * FROM platform_status WHERE platform = ?", (platform,)
                )
                row = cursor.fetchone()

                if not row:
                    cursor.execute(
                        "INSERT INTO platform_status (platform, status, operations_count) VALUES (?, 'idle', 0)",
                        (platform,)
                    )
                    conn.commit()
                    return {
                        "platform": platform,
                        "status": "idle",
                        "last_operation_start": None,
                        "last_operation_end": None,
                        "operations_count": 0,
                    }

                return dict(row)
        except Exception as e:
            logger.error(f"读取平台状态失败 [{platform}]: {e}", exc_info=True)
            return {
                "platform": platform,
                "status": "idle",
                "last_operation_start": None,
                "last_operation_end": None,
                "operations_count": 0,
            }

    def get_today_operations_count(self, platform: str) -> int:
        """获取今日操作次数"""
        record = self._get_or_create_record(platform)
        return record["operations_count"]
