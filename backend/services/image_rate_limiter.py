"""图片生成本进程限流器。"""
import threading
import time
from contextlib import contextmanager


class ImageRateLimiter:
    """限制同一进程内图片上游请求的并发数和启动间隔。"""

    def __init__(self, max_concurrent: int = 1, interval_seconds: float = 3.0):
        self.max_concurrent = max(1, int(max_concurrent or 1))
        self.interval_seconds = max(0.0, float(interval_seconds or 0))
        self._semaphore = threading.Semaphore(self.max_concurrent)
        self._lock = threading.Lock()
        self._last_start_at = 0.0

    @contextmanager
    def acquire(self):
        self._semaphore.acquire()
        try:
            with self._lock:
                now = time.monotonic()
                wait_for = self._last_start_at + self.interval_seconds - now
                if wait_for > 0:
                    time.sleep(wait_for)
                self._last_start_at = time.monotonic()
            yield
        finally:
            self._semaphore.release()
