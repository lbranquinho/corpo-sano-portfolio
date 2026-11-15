"""Limitação de requisições em memória (janela deslizante).

Adequado para uma instância de API. Em escala horizontal, aplique também
limitação no Nginx (configurado em nginx/conf.d).
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        self._last_cleanup = time.monotonic()

    def hit(self, key: str, limit: int, window_seconds: int = 60) -> bool:
        """Registra uma tentativa; retorna False se o limite foi excedido."""
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and q[0] <= now - window_seconds:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            if now - self._last_cleanup > 300:
                self._cleanup(now, window_seconds)
            return True

    def _cleanup(self, now: float, window: int) -> None:
        for key in [k for k, q in self._hits.items() if not q or q[-1] <= now - window]:
            del self._hits[key]
        self._last_cleanup = now

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = SlidingWindowLimiter()
