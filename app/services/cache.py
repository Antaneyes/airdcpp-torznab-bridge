import asyncio
import time
from collections import OrderedDict
from collections.abc import Callable, Coroutine


class AsyncTTLCache[T]:
    def __init__(self, ttl: int, negative_ttl: int, max_size: int):
        self.ttl = ttl
        self.negative_ttl = negative_ttl
        self.max_size = max_size
        self._values: OrderedDict[str, tuple[float, T]] = OrderedDict()
        self._inflight: dict[str, asyncio.Task[T]] = {}
        self._lock = asyncio.Lock()

    async def get_or_create(self, key: str, factory: Callable[[], Coroutine[object, object, T]]) -> T:
        async with self._lock:
            entry = self._values.get(key)
            if entry and entry[0] > time.monotonic():
                self._values.move_to_end(key)
                return entry[1]
            self._values.pop(key, None)
            task = self._inflight.get(key)
            if task is None:
                task = asyncio.create_task(factory())
                self._inflight[key] = task
        try:
            value = await asyncio.shield(task)
            async with self._lock:
                ttl = self.negative_ttl if not value else self.ttl
                if ttl:
                    self._values[key] = (time.monotonic() + ttl, value)
                    while len(self._values) > self.max_size:
                        self._values.popitem(last=False)
            return value
        finally:
            async with self._lock:
                if self._inflight.get(key) is task and task.done():
                    self._inflight.pop(key, None)

    async def clear(self) -> None:
        async with self._lock:
            self._values.clear()
