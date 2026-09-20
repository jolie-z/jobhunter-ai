import json
import logging
import time
from typing import Any

import redis.asyncio as redis

logger = logging.getLogger(__name__)

class RedisService:
    def __init__(self, url: str = "redis://localhost:6379/0"):
        self.url = url
        self.redis_client: redis.Redis | None = None
        self._memory_fallback: dict[str, tuple[str, float]] = {}
        self.use_fallback = False

    async def connect(self):
        if self.redis_client and not self.use_fallback:
            return

        try:
            client = redis.from_url(self.url, decode_responses=True)
            await client.ping()
            self.redis_client = client
            self.use_fallback = False
            logger.info("[RedisService] ✅ Successfully connected to Redis.")
        except Exception as e:
            logger.warning(f"[RedisService] ⚠️ Redis connection failed: {e}. Falling back to In-Memory dictionary. (Data will be lost on restart)")
            self.use_fallback = True

    async def get(self, key: str) -> Any | None:
        if not self.redis_client and not self.use_fallback:
            await self.connect()

        if self.use_fallback:
            item = self._memory_fallback.get(key)
            if not item:
                return None
            val_str, expire_at = item
            if expire_at and time.time() > expire_at:
                self._memory_fallback.pop(key, None)
                return None
            try:
                return json.loads(val_str)
            except Exception:
                return val_str
        else:
            try:
                val = await self.redis_client.get(key)
                if val is None:
                    return None
                try:
                    return json.loads(val)
                except Exception:
                    return val
            except Exception as e:
                logger.error(f"[RedisService] ❌ Redis get error for key={key}: {e}")
                return None

    async def set(self, key: str, data: Any, expire_seconds: int = 3600):
        val_str = json.dumps(data, ensure_ascii=False) if not isinstance(data, str) else data
        if not self.redis_client and not self.use_fallback:
            await self.connect()

        if self.use_fallback:
            expire_at = time.time() + expire_seconds if expire_seconds > 0 else 0
            self._memory_fallback[key] = (val_str, expire_at)
        else:
            try:
                if expire_seconds > 0:
                    await self.redis_client.set(key, val_str, ex=expire_seconds)
                # 0/负数=永不过期（与内存回退分支 >0 判断同契约）；redis 拒绝 ex<=0，故不带 ex
                else:
                    await self.redis_client.set(key, val_str)
            except Exception as e:
                logger.error(f"[RedisService] ❌ Redis set error for key={key}: {e}")

    async def delete(self, key: str):
        if not self.redis_client and not self.use_fallback:
            await self.connect()

        if self.use_fallback:
            self._memory_fallback.pop(key, None)
        else:
            try:
                await self.redis_client.delete(key)
            except Exception as e:
                logger.error(f"[RedisService] ❌ Redis delete error for key={key}: {e}")

    async def get_task(self, task_id: str) -> dict[str, Any] | None:
        return await self.get(f"task:{task_id}")

    async def set_task(self, task_id: str, data: dict[str, Any], expire_seconds: int = 3600):
        await self.set(f"task:{task_id}", data, expire_seconds=expire_seconds)

    async def update_task(self, task_id: str, **fields: Any):
        task = await self.get_task(task_id)
        if not task:
            task = {}
        task.update(fields)
        await self.set_task(task_id, task)

# 单例模式导出
redis_service = RedisService()
