# DESIGN.md — Rate-limited transactional email queue

## Problem

Transactional email (order confirmations, OTPs, alerts) must survive flash-sale bursts of ~2,000 enqueue requests in under 10 seconds while the provider accepts **at most 200 send attempts per rolling 60 seconds**. Jobs must retry on transient failure, land in a dead-letter store when they cannot succeed, and not vanish if a worker process is killed. Celery’s broker delivery is **at-least-once**, not exactly-once.

## Architecture choice

### Celery + Redis (chosen)

Celery is the execution engine; Redis is the broker, the result backend, and the rate-limit store.

**Fits this problem:** retry with exponential countdown, `acks_late`, `reject_on_worker_lost`, visibility timeout on the Redis transport, and a worker we can run locally in one extra process. The assessment also requires this stack, which matches what most Django product teams already operate.

**Cost:** you operate Redis and a worker. You must understand redelivery and idempotency (see below). Result keys expire; durable accounting lives in `EmailJob` / `EmailDeadLetter`, not in Celery results.

### Django Q (not chosen)

Django Q (or Django-Q2) stores work in ORM/Redis with a simpler Django-native API. It is enough for low-volume “send this email later” jobs.

**Trade-off:** weaker, less documented worker-loss and visibility-timeout behaviour than Celery’s Redis transport. Retry/backoff and dead-letter patterns are DIY. Fine for a small internal app; a poor fit when the brief asks for SIGKILL semantics and a custom limiter next to a bursty queue.

### Custom Redis list/queue (not chosen)

`LPUSH`/`BRPOP` plus your own ack key, heartbeat, and retry ZSET is fully controllable.

**Trade-off:** you now own poison messages, crash recovery, and idempotency. Easy to get “at-most-once” (lost jobs) or unbounded duplicates. Not appropriate for a 4–6 hour assessment when Celery already solves the boring parts.

## Rate limiter

### Algorithm: sliding window on a Redis sorted set

Provider contract: **200 accepted send attempts per rolling 60 seconds**. That is not a clock-aligned fixed window.

| Option | Behaviour | Why not (or why) |
| --- | --- | --- |
| Fixed window (`INCR` + `EXPIRE`) | 200 at 00:00:59 and 200 at 00:01:00 → 400 in one rolling minute | Violates a rolling cap. Simplest, cheapest, wrong semantics here. |
| Token bucket (`DECR` + TTL / Lua refill) | Smooths bursts; refill rate 200/60s | Excellent for “average rate”. Harder to explain as a strict rolling count of *attempts*. |
| **Sliding window (`ZREMRANGEBYSCORE` + `ZADD` + `ZCARD`)** | Count of members with score in `(now-60, now]` | Matches the rolling definition. Memory is O(admits in the window). |

Implementation: `apps/notifications/lua/sliding_window.lua`, called with `EVALSHA` from `apps/notifications/rate_limit.py`. Members are `{idempotency_key}:{attempt}` so retries are distinct attempts. `EXPIRE` on the key is a safety TTL, not the window itself.

Admission happens **immediately before** the provider call, not at enqueue time. Enqueue can accept 2,000 rows in SQLite/Postgres in a few hundred milliseconds; workers drip sends at the provider’s pace.

We never `time.sleep()` to throttle. Celery `retry(countdown=…)` puts the message back on the broker.

### Atomicity

The check-and-admit path is one Lua script. Redis runs Lua as a single-threaded EVAL: no other command interleaves between `ZCARD` and `ZADD`. That is stronger than a Python `GET` then `INCR` (race) and simpler than `MULTI/EXEC` for this branching logic (a transaction cannot `ZCARD` and then conditionally `ZADD` without Lua or optimistic WATCH).

### Redis failure policy: **fail-closed** (default)

If Redis raises `RedisError`, `admit_send_attempt` raises `RateLimiterUnavailable`. The task does **not** send. It retries with backoff.

**Why:** the provider’s 200/min cap is the hard constraint. Fail-open would send during an outage and can ban the account. Fail-closed stalls email until Redis returns. That is the correct production default for this brief. `EMAIL_RATE_LIMIT_ON_REDIS_ERROR=fail_open` exists only to document the opposite trade-off.

## Retries and dead letters

- **Transient provider errors** (timeouts, 5xx, simulated 429): Celery `retry` with countdown 1, 2, 4, 8 seconds, max 4 provider retries, then `EmailDeadLetter`.
- **Permanent provider errors** (invalid recipient): no retry; dead-letter immediately.
- **Rate-limited / Redis down:** retry with the same backoff, **without** counting toward the provider retry budget and **without** incrementing `EmailJob.attempts`. A flash-sale burst must not dead-letter healthy jobs because they waited for a token.

Durable state is the `EmailJob` row. Celery results are optional debug data (`CELERY_RESULT_BACKEND`) and expire in one hour.

## Worker crash, SIGKILL, and duplicates

Configured in `config/settings.py` and on the task:

- `CELERY_TASK_ACKS_LATE = True` / `acks_late=True` — the Redis transport ACKs **after** the task returns. SIGKILL mid-task leaves the message unacked.
- Redis broker **visibility timeout** (`CELERY_BROKER_TRANSPORT_OPTIONS["visibility_timeout"] = 3600`) — if the worker dies without ACK, another worker may take the message after this timeout. It must exceed the longest reasonable runtime including retry countdowns executed in-worker. Too low → overlapping execution of the same message.
- `CELERY_TASK_REJECT_ON_WORKER_LOST = True` — if the worker process is lost, the message is requeued rather than silently dropped.
- `CELERY_WORKER_PREFETCH_MULTIPLIER = 1` — a killed worker holds at most one extra reserved message, which matters more with late ack.

**What SIGKILL does not give you:** exactly-once email. If the process dies **after** the HTTP/SMTP send succeeds and **before** ACK + `EmailJob.status = sent`, Celery redelivers. We mitigate with:

1. `select_for_update` on the job row;
2. early return if `status == sent`;
3. provider-side skip if the same `idempotency_key` was already sent in-process.

A real vendor should be passed that idempotency key. If they ignore it, a duplicate email can still arrive. Celery cannot prevent that; only the provider can.

## Test strategy

- **Unit-ish Django tests:** serializer/query budgets; fail-closed limiter against a closed port.
- **Redis integration tests** (`require_redis`): Lua window, concurrent admits, 500-job accounting with a **virtual clock** and a test limit of **20 / 60s**.
- Tests never send real email (`FakeEmailProvider`).
- Production 200/60s is exercised by a documented manual procedure in `README.md`, not by sleeping for minutes in CI.
