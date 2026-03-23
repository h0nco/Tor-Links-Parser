import asyncio
import time


class RateLimiter:
    def __init__(self, rate: float = 10.0, burst: int = 20) -> None:
        self.rate: float = rate
        self.burst: int = burst
        self.tokens: float = float(burst)
        self.last: float = time.monotonic()
        self._lock: asyncio.Lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now: float = time.monotonic()
            self.tokens = min(self.burst, self.tokens + (now - self.last) * self.rate)
            self.last = now
            if self.tokens >= 1:
                self.tokens -= 1
                return
        while True:
            await asyncio.sleep(1.0 / self.rate)
            async with self._lock:
                now = time.monotonic()
                self.tokens = min(self.burst, self.tokens + (now - self.last) * self.rate)
                self.last = now
                if self.tokens >= 1:
                    self.tokens -= 1
                    return