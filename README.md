# Full-Stack Developer Assessment

Django implementation of the three required assessment sections:

1. Diagnose and fix a slow `/api/orders/summary/` endpoint (ORM N+1).
2. Celery + Redis transactional-email queue with an atomic sliding-window limiter, retries, and dead letters.
3. Written architecture answers in `ANSWERS.md` (Questions A and B).

Local setup is SQLite + Redis. Email never leaves this process (`FakeEmailProvider`).

## Prerequisites

- Windows 10/11, PowerShell
- Python 3.12
- Git
- Redis listening on `127.0.0.1:6379` (Celery broker, results, and the rate limiter)

Python 3.12 can be installed with:

```powershell
winget install --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
```

Redis is **not** optional for Section 2 integration tests. Options:

```powershell
winget install --id taizod1024.redis-windows-fork --accept-package-agreements --accept-source-agreements
# or Memurai Developer:
# winget install --id Memurai.MemuraiDeveloper --accept-package-agreements --accept-source-agreements
```

Docker/WSL also works (`docker run -p 6379:6379 redis:7`). There is no Docker install on the machine this project was developed on unless you add one.

Confirm Redis:

```powershell
# after redis-server is running
redis-cli ping
```

## Setup (PowerShell)

```powershell
cd $env:USERPROFILE\Desktop\FullStackDeveloperAssessment
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
python manage.py migrate
python manage.py seed_orders
```

If `py` is not on PATH, use:

`& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"`

## Environment

Copy `.env.example` to `.env`. Do not commit `.env`. Placeholders only; the fake provider needs no API keys.

| Variable | Meaning |
| --- | --- |
| `DJANGO_SECRET_KEY` | Django secret (local default is insecure) |
| `REDIS_URL` | Rate-limiter Redis DB |
| `CELERY_BROKER_URL` | Celery broker |
| `CELERY_RESULT_BACKEND` | Celery results (ephemeral) |
| `EMAIL_RATE_LIMIT` / `EMAIL_RATE_WINDOW_SECONDS` | Production default `200` / `60` |
| `EMAIL_RATE_LIMIT_ON_REDIS_ERROR` | `fail_closed` (default) or `fail_open` |

## Run the apps

Terminal 1 — Redis (if not already a Windows service).

Terminal 2 — Django:

```powershell
.\.venv\Scripts\Activate.ps1
python manage.py runserver
```

Terminal 3 — Celery worker:

```powershell
.\.venv\Scripts\Activate.ps1
celery -A config worker -l info --pool=solo
```

`--pool=solo` is the reliable Windows pool (prefork is a Unix default).

## API

- `GET /api/orders/summary/?customer_id=<id>` — optimized summary
- `GET /api/orders/summary/?customer_id=<id>&naive=1` — unoptimized queryset (for Silk)
- `POST /api/notifications/emails/` — enqueue fake email JSON: `to_email`, `template`, `idempotency_key`, optional `payload`
- `http://127.0.0.1:8000/silk/` — django-silk request/SQL profiler
- `http://127.0.0.1:8000/admin/` — jobs and dead letters

Create a superuser only if you want admin: `python manage.py createsuperuser`.

## Tests

```powershell
.\.venv\Scripts\Activate.ps1
python manage.py check
pytest
```

If Redis is down, Section 1 tests still run; Section 2 tests `pytest.skip`. That is reported honestly — do not treat skipped limiter tests as a pass of Section 2.

## Reproduce Section 1 (N+1 → fix)

```powershell
python manage.py seed_orders --orders 220 --items-per-order 3
python scripts\capture_query_counts.py
python manage.py runserver
```

Then in a browser or `Invoke-WebRequest`:

- Naive: `http://127.0.0.1:8000/api/orders/summary/?customer_id=1&naive=1`
- Fixed: `http://127.0.0.1:8000/api/orders/summary/?customer_id=1`

Compare SQL counts in Silk. The capture script writes genuine counts from `CaptureQueriesContext` (not invented). Save a run to `docs/query-counts.txt` if you need a file for submission. Investigation notes: `docs/incident-log.md`.

## Demonstrate Section 2

With Redis + worker running:

```powershell
# enqueue (does not send real mail)
Invoke-RestMethod -Method POST -Uri http://127.0.0.1:8000/api/notifications/emails/ -ContentType "application/json" -Body '{"to_email":"a@example.com","template":"otp","idempotency_key":"demo-1"}'
```

- **Rate limit:** set `EMAIL_RATE_LIMIT=5` in `.env`, restart worker, enqueue 20 jobs; Redis `ZCARD email:send:rolling-window` stays ≤ 5 in any 60s window. Restore `200` afterwards.
- **Retry:** mark a job’s key in the fake provider’s `transient_failures_remaining` via a test, or run `pytest tests/test_email_queue.py -k transient`.
- **Dead letter:** `to_email` ending in `@fail-permanent.example` writes `EmailDeadLetter`.
- **500-job accounting** (virtual clock, 20/60s test limit): `pytest tests/test_email_queue.py -k five_hundred`.

### Production 200/minute check (manual, not CI)

Leave `EMAIL_RATE_LIMIT=200` and `EMAIL_RATE_WINDOW_SECONDS=60`. Enqueue >200 jobs to a **live** worker (not eager). Sample Redis:

```powershell
redis-cli ZCARD email:send:rolling-window
```

The Lua script refuses admits at 200. Do not put this wait in pytest.

## Known limitations

- SQLite is for local demo speed. Use PostgreSQL in production (`select_for_update` and write concurrency are stronger there).
- Fake provider only. Duplicate protection is in-process + `EmailJob.status`; a real vendor must honour `idempotency_key`.
- Celery on Windows uses `--pool=solo`.
- Silk timings depend on this machine; we do not invent profiler screenshots.
- Optional Loom recording is not included.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| `pytest` skips Redis tests | Redis not on `6379`; `redis-cli ping` |
| Celery `Connection refused` | Broker URL; Redis running |
| Worker hangs on Windows | Use `--pool=solo` |
| Silk empty | `DEBUG=true`; hit the URL again; open `/silk/` |
| `python` is the Store stub | Use Python 3.12 from `AppData\Local\Programs\Python\Python312` |

## Submission checklist

- [ ] `README.md`, `DESIGN.md`, `ANSWERS.md` at repo root
- [ ] Section 1 view, seed data, incident log, Silk or `capture_query_counts.py` evidence
- [ ] Section 2 Celery + Redis limiter, retries, dead letter, SIGKILL write-up
- [ ] Tests pass from a clean venv with Redis up
- [ ] No `.env`, secrets, or `.venv` committed
- [ ] GitHub/GitLab access granted to the contact (when you publish)

## Project layout

```
config/                 Django + Celery
apps/orders/            Section 1
apps/notifications/     Section 2 (tasks, Lua limiter, fake provider)
tests/
scripts/
docs/
```
