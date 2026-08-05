import asyncio

from app.services.cache import AsyncTTLCache


async def test_cache_coalesces_inflight_requests():
    cache = AsyncTTLCache[list[int]](60, 1, 10)
    calls = 0

    async def factory():
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        return [1]

    assert await asyncio.gather(*(cache.get_or_create("same", factory) for _ in range(5))) == [[1]] * 5
    assert calls == 1
