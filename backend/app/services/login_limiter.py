"""Blocks repeated wrong-password attempts (simple in-memory brute-force protection).

5 failures within 15 minutes for the same e-mail + IP => blocked until the oldest
failure is 15 minutes old. State lives in memory, so it resets when the server restarts.
"""
import threading
import time
from collections import defaultdict, deque

MAX_FAILURES = 5
WINDOW_SECONDS = 15 * 60

_failures: dict[str, deque] = defaultdict(deque)
_lock = threading.Lock()


def _key(email: str, ip: str | None) -> str:
    return f"{email}|{ip or 'unknown'}"


def _prune(queue: deque, now: float) -> None:
    while queue and now - queue[0] > WINDOW_SECONDS:
        queue.popleft()


def seconds_until_unblocked(email: str, ip: str | None) -> int:
    """0 when the login attempt is allowed, otherwise the seconds to wait."""
    now = time.monotonic()
    with _lock:
        queue = _failures[_key(email, ip)]
        _prune(queue, now)
        if len(queue) < MAX_FAILURES:
            return 0
        return int(WINDOW_SECONDS - (now - queue[0])) + 1


def record_failure(email: str, ip: str | None) -> None:
    with _lock:
        _failures[_key(email, ip)].append(time.monotonic())


def reset(email: str, ip: str | None) -> None:
    with _lock:
        _failures.pop(_key(email, ip), None)


def clear_all() -> None:
    """Used by the tests."""
    with _lock:
        _failures.clear()
