"""Простой in-memory rate limiter для Спринта 1.

На старте достаточно одного процесса; при горизонтальном масштабировании
заменяется на Redis (интерфейс сохранён).

Клиентский IP берётся из TCP-соединения. `X-Forwarded-For` принимается только
от доверенных reverse-proxy (`TRUSTED_PROXIES`, IP или CIDR), иначе заголовок
игнорируется — иначе клиент подделывал бы IP и обходил лимиты/подменял аудит.
"""

from __future__ import annotations

import ipaddress
import threading
import time
from collections import deque

from app.core.config import settings


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, *, limit: int, window_seconds: int) -> bool:
        now = time.monotonic()
        with self._lock:
            bucket = self._hits.setdefault(key, deque())
            while bucket and now - bucket[0] > window_seconds:
                bucket.popleft()
            if len(bucket) >= limit:
                return False
            bucket.append(now)
            return True

    def reset(self, key: str | None = None) -> None:
        with self._lock:
            if key is None:
                self._hits.clear()
            else:
                self._hits.pop(key, None)


limiter = SlidingWindowLimiter()


def _is_trusted_proxy(peer: str | None, trusted: list[str]) -> bool:
    """Является ли адрес TCP-соединения доверенным прокси (IP или CIDR)."""
    if not peer:
        return False
    for entry in trusted:
        try:
            network = ipaddress.ip_network(entry, strict=False)
        except ValueError:
            # не IP/CIDR — допускаем точное сравнение (например, "testclient")
            if peer.lower() == entry.lower():
                return True
            continue
        try:
            address = ipaddress.ip_address(peer)
        except ValueError:
            continue
        if address in network:
            return True
    return False


def client_ip(request) -> str:
    """Клиентский IP: заголовок X-Forwarded-For — только от доверенного прокси."""
    peer = request.client.host if request.client else "unknown"
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded and _is_trusted_proxy(peer, settings.trusted_proxies):
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return peer
