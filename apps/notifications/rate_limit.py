"""Atomic Redis sliding-window rate limiter.

Admit at most `limit` send attempts in any rolling `window_seconds`.
Atomicity comes from a Lua script (EVAL), not a Python check-then-write.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import redis
from django.conf import settings

LUA_PATH = Path(__file__).resolve().parent / "lua" / "sliding_window.lua"
_LUA_SHA: str | None = None
_LUA_SCRIPT = LUA_PATH.read_text(encoding="utf-8")


class RateLimitError(Exception):
    """Base limiter error."""


class RateLimited(RateLimitError):
    """Window is full; caller should retry later (not send)."""


class RateLimiterUnavailable(RateLimitError):
    """Redis could not be reached. Policy decides fail-open vs fail-closed."""


@dataclass
class Admission:
    admitted: bool
    current_count: int


def redis_client() -> redis.Redis:
    return redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)


def _eval_lua(client: redis.Redis, keys, args):
    global _LUA_SHA
    try:
        if _LUA_SHA is None:
            _LUA_SHA = client.script_load(_LUA_SCRIPT)
        return client.evalsha(_LUA_SHA, len(keys), *keys, *args)
    except redis.exceptions.NoScriptError:
        _LUA_SHA = client.script_load(_LUA_SCRIPT)
        return client.evalsha(_LUA_SHA, len(keys), *keys, *args)


def admit_send_attempt(
    member: str,
    *,
    now: float | None = None,
    limit: int | None = None,
    window_seconds: int | None = None,
    client: redis.Redis | None = None,
) -> Admission:
    """Return whether this attempt may call the email provider.

    `now` is injectable so tests can advance a virtual clock without waiting.
    """
    limit = settings.EMAIL_RATE_LIMIT if limit is None else limit
    window_seconds = (
        settings.EMAIL_RATE_WINDOW_SECONDS if window_seconds is None else window_seconds
    )
    now = time.time() if now is None else now
    conn = client or redis_client()
    try:
        admitted, current = _eval_lua(
            conn,
            [settings.EMAIL_RATE_LIMIT_KEY],
            [str(now), str(window_seconds), str(limit), member],
        )
        return Admission(admitted=bool(int(admitted)), current_count=int(current))
    except (redis.RedisError, ConnectionError, OSError) as exc:
        policy = getattr(settings, "EMAIL_RATE_LIMIT_ON_REDIS_ERROR", "fail_closed")
        if policy == "fail_open":
            return Admission(admitted=True, current_count=-1)
        raise RateLimiterUnavailable(str(exc)) from exc


def require_admission(member: str, **kwargs) -> Admission:
    result = admit_send_attempt(member, **kwargs)
    if not result.admitted:
        raise RateLimited(
            f"rate limit reached ({result.current_count} in window)"
        )
    return result
