"""
PlatformSemaphore - 平台级信号量类

用于实现对每个平台的互斥访问控制，并支持超时机制。
当某个平台操作卡住时，强制释放锁并切换到下一个平台。
"""

import asyncio
from contextlib import asynccontextmanager


class DeliveryTimeoutError(Exception):
    """投递超时异常"""
    pass


class PlatformSemaphore:
    """
    平台级信号量 + 超时保护

    功能：
    - 同一时间只允许一个线程访问某个平台
    - 支持设置超时时间（默认 30 分钟）
    - 超时后自动释放锁并抛出异常
    """

    def __init__(self):
        """初始化 4 个平台的信号量"""
        self.lockers = {}

        for platform in ["boss", "51job", "liepin", "zhilian"]:
            # Semaphore(1) = 单线程互斥锁
            self.lockers[platform] = asyncio.Semaphore(1)

    @asynccontextmanager
    async def acquire_with_timeout(self, platform: str,
                                   timeout_seconds: int = 1800):
        """
        获取平台锁，带超时机制

        Args:
            platform: 平台名称
            timeout_seconds: 超时时间（秒），默认 30 分钟

        Yields:
            无返回值，仅作为上下文管理器使用

        Raises:
            DeliveryTimeoutError: 如果超时仍未完成，强制解锁并抛出异常
        """
        try:
            # 尝试获取锁（最多等 timeout_seconds 秒）
            async with asyncio.timeout(timeout_seconds):
                async with self.lockers[platform]:
                    yield  # 执行业务逻辑

        except asyncio.TimeoutError:
            logger_error(f"🚨 [{platform}] 投递超时 ({timeout_seconds}s)，强制解锁")

            # 强制释放锁（注意：可能导致数据不一致）
            if not self.lockers[platform].locked():
                logger_warning(f"⚠️ [{platform}] 锁已被释放，无需重复操作")
            else:
                # 手动解锁（不安全但必要）
                while self.lockers[platform]._value < 1:
                    self.lockers[platform]._value += 1

                logger_success(f"🔓 [{platform}] 已强制解锁")

            # 抛出异常，让调用者处理
            raise DeliveryTimeoutError(
                f"{platform} 投递超时 ({timeout_seconds}s)，请人工核查"
            )

    def is_locked(self, platform: str) -> bool:
        """检查某平台是否被锁定"""
        return self.lockers[platform].locked()

    def get_unlocked_platforms(self) -> list[str]:
        """获取所有未锁定的平台列表"""
        return [p for p in self.lockers if not self.is_locked(p)]


# 全局日志辅助函数（避免直接导入导致循环依赖）
def logger_error(msg: str):
    print(f"[ERROR] {msg}")

def logger_warning(msg: str):
    print(f"[WARNING] {msg}")

def logger_success(msg: str):
    print(f"[SUCCESS] {msg}")
