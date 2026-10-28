from __future__ import annotations

import threading
import uuid

import pytest
import redis

from apps.notifications.rate_limit import (
    RateLimited,
    RateLimiterUnavailable,
    admit_send_attempt,
    require_admission,
)


def _member() -> str:
    return str(uuid.uuid4())


@pytest.mark.django_db
def test_sliding_window_admits_up_to_limit(require_redis, settings):
    settings.EMAIL_RATE_LIMIT = 3
    settings.EMAIL_RATE_WINDOW_SECONDS = 60
    now = 1_700_000_000.0
    for i in range(3):
        require_admission(_member(), now=now + i, client=require_redis)
    with pytest.raises(RateLimited):
        require_admission(_member(), now=now + 10, client=require_redis)


@pytest.mark.django_db
def test_sliding_window_rolls_off_old_events(require_redis, settings):
    settings.EMAIL_RATE_LIMIT = 2
    settings.EMAIL_RATE_WINDOW_SECONDS = 60
    t0 = 1_700_000_000.0
    require_admission("a", now=t0, client=require_redis)
    require_admission("b", now=t0 + 1, client=require_redis)
    with pytest.raises(RateLimited):
        require_admission("c", now=t0 + 2, client=require_redis)
    require_admission("d", now=t0 + 61, client=require_redis)


@pytest.mark.django_db
def test_never_exceeds_limit_in_any_recorded_window(require_redis, settings):
    settings.EMAIL_RATE_LIMIT = 5
    settings.EMAIL_RATE_WINDOW_SECONDS = 60
    t0 = 1_700_000_000.0
    admitted_at: list[float] = []
    for i in range(40):
        ts = t0 + i * 5
        result = admit_send_attempt(_member(), now=ts, client=require_redis)
        if result.admitted:
            admitted_at.append(ts)
        else:
            window_hits = [t for t in admitted_at if ts - 60 < t <= ts]
            assert len(window_hits) == 5
    for ts in admitted_at:
        window_hits = [t for t in admitted_at if ts - 60 < t <= ts]
        assert len(window_hits) <= 5


@pytest.mark.django_db
def test_fail_closed_when_redis_is_down(settings):
    settings.EMAIL_RATE_LIMIT_ON_REDIS_ERROR = "fail_closed"
    dead = redis.Redis(
        host="127.0.0.1",
        port=1,
        socket_connect_timeout=0.2,
        socket_timeout=0.2,
    )
    with pytest.raises(RateLimiterUnavailable):
        require_admission("x", client=dead)


@pytest.mark.django_db
def test_fail_open_when_configured(settings):
    settings.EMAIL_RATE_LIMIT_ON_REDIS_ERROR = "fail_open"
    dead = redis.Redis(
        host="127.0.0.1",
        port=1,
        socket_connect_timeout=0.2,
        socket_timeout=0.2,
    )
    result = admit_send_attempt("x", client=dead)
    assert result.admitted is True


@pytest.mark.django_db
def test_concurrent_admits_never_exceed_limit(require_redis, settings):
    settings.EMAIL_RATE_LIMIT = 20
    settings.EMAIL_RATE_WINDOW_SECONDS = 60
    now = 1_800_000_000.0
    admitted = []
    lock = threading.Lock()

    def worker() -> None:
        client = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
        for _ in range(15):
            result = admit_send_attempt(_member(), now=now, client=client)
            if result.admitted:
                with lock:
                    admitted.append(1)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(admitted) == 20
