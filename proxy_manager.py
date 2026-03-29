"""Proxy manager with rotation support."""

import itertools
import threading
from pathlib import Path


class ProxyManager:
    """Thread-safe rotating proxy manager."""

    def __init__(self, proxy_file: str | None = None):
        self._proxies: list[str] = []
        self._cycle = itertools.cycle([])
        self._lock = threading.Lock()

        if proxy_file:
            self.load(proxy_file)

    def load(self, path: str) -> int:
        """Load proxies from file. Supports formats:
        - ip:port
        - ip:port:user:pass
        - user:pass@ip:port
        - http://ip:port
        - socks5://ip:port
        """
        raw = Path(path).read_text(encoding="utf-8", errors="ignore").splitlines()
        self._proxies = [self._normalize(line.strip()) for line in raw if line.strip()]
        self._cycle = itertools.cycle(self._proxies)
        return len(self._proxies)

    def get(self) -> str | None:
        """Get next proxy in rotation (thread-safe)."""
        if not self._proxies:
            return None
        with self._lock:
            return next(self._cycle)

    @property
    def count(self) -> int:
        return len(self._proxies)

    @staticmethod
    def _normalize(proxy: str) -> str:
        """Normalize proxy string to httpx-compatible URL."""
        if proxy.startswith(("http://", "https://", "socks5://", "socks4://")):
            return proxy

        parts = proxy.split(":")
        if len(parts) == 4:
            ip, port, user, pwd = parts
            return f"http://{user}:{pwd}@{ip}:{port}"
        if len(parts) == 2:
            return f"http://{parts[0]}:{parts[1]}"
        if "@" in proxy:
            return f"http://{proxy}"
        return f"http://{proxy}"
