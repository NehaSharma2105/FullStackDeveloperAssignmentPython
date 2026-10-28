from __future__ import annotations

import uuid

import pytest
from celery.exceptions import Retry

from apps.notifications.emails import provider
from apps.notifications.models import EmailDeadLetter, EmailJob
from apps.notifications.tasks import (
    MAX_PROVIDER_RETRIES,
    enqueue_email,
    send_transactional_email,
)


def _job(**kwargs) -> EmailJob:
    defaults = {
        "idempotency_key": f"key-{uuid.uuid4()}",
        "to_email": "user@example.com",
        "template": "order_confirm",
        "payload": {"order_id": 1},
    }
    defaults.update(kwargs)
    return EmailJob.objects.create(**defaults)


def _apply(job: EmailJob, now: float, retries: int = 0):
    return send_transactional_email.apply(
        kwargs={"job_id": job.id, "now": now},
        retries=retries,
    )


@pytest.mark.django_db
def test_transient_failure_is_retried_then_sent(require_redis):
    job = _job()
    provider.transient_failures_remaining[job.idempotency_key] = 1
    now = 1_700_000_000.0
    with pytest.raises(Retry):
        _apply(job, now)
    job.refresh_from_db()
    assert job.status == EmailJob.Status.RETRYING
    assert job.attempts == 1
    assert provider.sent == []

    result = _apply(job, now + 1)
    assert result.result == "sent"
    job.refresh_from_db()
    assert job.status == EmailJob.Status.SENT
    assert len(provider.sent) == 1


@pytest.mark.django_db
def test_permanent_failure_goes_to_dead_letter(require_redis):
    job = _job(to_email="bad@fail-permanent.example")
    result = _apply(job, 1_700_000_000.0)
    assert result.result == "dead_lettered"
    job.refresh_from_db()
    assert job.status == EmailJob.Status.DEAD_LETTER
    assert EmailDeadLetter.objects.filter(job=job).exists()


@pytest.mark.django_db
def test_exhausted_transient_retries_dead_letter(require_redis):
    job = _job(to_email="always@fail-transient.example")
    now = 1_700_000_000.0
    outcomes = []
    for i in range(MAX_PROVIDER_RETRIES + 1):
        try:
            outcomes.append(_apply(job, now + i, retries=i).result)
        except Retry:
            outcomes.append("retry")
    assert "retry" in outcomes
    assert outcomes[-1] == "dead_lettered"
    assert EmailDeadLetter.objects.filter(job_id=job.id).exists()


@pytest.mark.django_db
def test_duplicate_idempotency_key_does_not_create_second_job(require_redis):
    first, created1 = enqueue_email(
        to_email="user@example.com",
        template="otp",
        payload={},
        idempotency_key="order-42-otp",
        delay=False,
    )
    second, created2 = enqueue_email(
        to_email="user@example.com",
        template="otp",
        payload={},
        idempotency_key="order-42-otp",
        delay=False,
    )
    assert created1 is True
    assert created2 is False
    assert first.id == second.id
    assert EmailJob.objects.filter(idempotency_key="order-42-otp").count() == 1


@pytest.mark.django_db
def test_already_sent_job_is_not_sent_again(require_redis):
    job = _job()
    now = 1_700_000_000.0
    assert _apply(job, now).result == "sent"
    assert _apply(job, now + 1).result == "duplicate_skipped"
    assert len(provider.sent) == 1


@pytest.mark.django_db
def test_dead_lettered_job_is_not_re_enqueued(require_redis):
    job = _job(to_email="bad@fail-permanent.example")
    assert _apply(job, 1_700_000_000.0).result == "dead_lettered"

    second, created = enqueue_email(
        to_email=job.to_email,
        template=job.template,
        payload=job.payload,
        idempotency_key=job.idempotency_key,
        delay=False,
    )

    assert created is False
    assert second.id == job.id
    assert second.status == EmailJob.Status.DEAD_LETTER
    assert EmailDeadLetter.objects.filter(job=job).exists()


@pytest.mark.django_db
def test_five_hundred_jobs_are_accounted_and_rate_limited(require_redis, settings):
    """Submit 500 jobs. Every job is accounted for; admits stay within the window.

    Uses a test limit of 20 admits / 60s and a controllable clock so the suite
    does not wait a real minute. Production 200/60s is documented in README.md.
    """
    settings.EMAIL_RATE_LIMIT = 20
    settings.EMAIL_RATE_WINDOW_SECONDS = 60

    jobs: list[EmailJob] = []
    for i in range(500):
        key = f"batch-{i}"
        jobs.append(
            EmailJob.objects.create(
                idempotency_key=key,
                to_email="retry-me@example.com" if i == 0 else f"user{i}@example.com",
                template="alert",
                payload={"n": i},
            )
        )
    provider.transient_failures_remaining["batch-0"] = 1

    t0 = 1_700_000_000.0
    now = t0
    pending = {job.id for job in jobs}
    admits: list[float] = []
    safety = 0

    while pending:
        safety += 1
        assert safety < 20_000, "processing loop failed to drain"
        progress = False
        for job_id in list(pending):
            job = EmailJob.objects.get(pk=job_id)
            try:
                result = send_transactional_email.apply(
                    kwargs={"job_id": job_id, "now": now}
                ).result
            except Retry:
                job.refresh_from_db()
                if job.last_error.startswith("rate limit"):
                    continue
                admits.append(now)
                progress = True
                continue
            if result in {"sent", "duplicate_skipped", "dead_lettered"}:
                pending.remove(job_id)
                if result == "sent":
                    admits.append(now)
                progress = True
            else:
                raise AssertionError(result)
        if not progress:
            now += 60

    assert EmailJob.objects.count() == 500
    statuses = set(EmailJob.objects.values_list("status", flat=True))
    assert statuses <= {EmailJob.Status.SENT, EmailJob.Status.DEAD_LETTER}
    assert EmailJob.objects.filter(status=EmailJob.Status.SENT).count() == 500
    retry_job = EmailJob.objects.get(idempotency_key="batch-0")
    assert retry_job.attempts == 2
    assert retry_job.status == EmailJob.Status.SENT

    for ts in admits:
        window_hits = [t for t in admits if ts - 60 < t <= ts]
        assert len(window_hits) <= 20
