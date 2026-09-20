import asyncio
import time
import pytest
from app.services.redis_service import RedisService

@pytest.mark.asyncio
async def test_redis_service_fallback_cache():
    # 测试在 fallback 模式下的 get, set, delete 以及 TTL
    service = RedisService(url="redis://non_existent_host:9999/0")
    service.use_fallback = True
    
    # 1. set and get
    await service.set("test:key1", {"name": "test_job", "score": 95}, expire_seconds=10)
    data = await service.get("test:key1")
    assert data == {"name": "test_job", "score": 95}
    
    # 2. delete
    await service.delete("test:key1")
    assert await service.get("test:key1") is None

    # 3. ttl expire
    await service.set("test:key2", "quick_expire", expire_seconds=1)
    assert await service.get("test:key2") == "quick_expire"
    await asyncio.sleep(1.1)
    assert await service.get("test:key2") is None
