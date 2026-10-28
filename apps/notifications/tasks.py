from __future__ import annotations

import time

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from apps.notifications.emails import provider
from apps.notifications.exceptions import PermanentProviderError, TransientProviderError
from apps.notifications.models import EmailDeadLetter, EmailJob
from apps.notifications.rate_limit import (
    RateLimited,
    RateLimiterUnavailable,
    require_admission,
)

MAX_PROVIDER_RETRIES = 4
RETRY_COUNTDOWNS = (1, 2, 4, 8)
# Rate-limit / Redis-down retries must not dead-letter a healthy job during a burst.
RATE_LIMIT_MAX_RETRIES = 10_000


def _countdown(retries: int) -> int:
    if retries < len(RETRY_COUNTDOWNS):
        return RETRY_COUNTDOWNS[retries]
    return RETRY_COUNTDOWNS[-1]


def _dead_letter(job: EmailJob, reason: str, error: str) -> None:
    job.status = EmailJob.Status.DEAD_LETTER
    job.last_error = error
    job.save(update_fields=["status", "last_error", "updated_at"])
    EmailDeadLetter.objects.get_or_create(
        job=job, defaults={"reason": reason, "error": error}
    )


@shared_task(
    bind=True,
    name="notifications.send_transactional_email",
    max_retries=MAX_PROVIDER_RETRIES,
    acks_late=True,
    reject_on_worker_lost=True,
)
def send_transactional_email(self, job_id: int, now: float | None = None) -> str:
    """Send one transactional email, rate-limited and idempotent.

    `now` is injectable so tests can advance a virtual clock.
    """
    clock = time.time() if now is None else now

    with transaction.atomic():
        try:
            job = EmailJob.objects.select_for_update().get(pk=job_id)
        except EmailJob.DoesNotExist:
            return "missing"

        if job.status == EmailJob.Status.SENT:
            return "duplicate_skipped"
        if job.status == EmailJob.Status.DEAD_LETTER:
            return "already_dead_lettered"

    member = f"{job.idempotency_key}:{job.attempts + 1}"
    try:
        require_admission(member, now=clock)
    except RateLimited as exc:
        job.status = EmailJob.Status.RETRYING
        job.last_error = str(exc)
        job.save(update_fields=["status", "last_error", "updated_at"])
        raise self.retry(
            exc=exc,
            countdown=_countdown(self.request.retries),
            max_retries=RATE_LIMIT_MAX_RETRIES,
            kwargs={"job_id": job.id, "now": now},
        )
    except RateLimiterUnavailable as exc:
        job.status = EmailJob.Status.RETRYING
        job.last_error = str(exc)
        job.save(update_fields=["status", "last_error", "updated_at"])
        raise self.retry(
            exc=exc,
            countdown=_countdown(self.request.retries),
            max_retries=RATE_LIMIT_MAX_RETRIES,
            kwargs={"job_id": job.id, "now": now},
        )

    job.attempts += 1
    job.status = EmailJob.Status.SENDING
    job.save(update_fields=["attempts", "status", "updated_at"])

    try:
        message_id = provider.send(
            to_email=job.to_email,
            template=job.template,
            payload=job.payload,
            idempotency_key=job.idempotency_key,
            now=clock,
        )
    except TransientProviderError as exc:
        return _retry_or_dead_letter(self, job, "provider_transient", str(exc), now=now)
    except PermanentProviderError as exc:
        _dead_letter(job, "provider_permanent", str(exc))
        return "dead_lettered"

    job.status = EmailJob.Status.SENT
    job.provider_message_id = message_id
    job.sent_at = timezone.now()
    job.last_error = ""
    job.save(
        update_fields=[
            "status",
            "provider_message_id",
            "sent_at",
            "last_error",
            "updated_at",
        ]
    )
    return "sent"


def _retry_or_dead_letter(task, job: EmailJob, reason: str, error: str, now: float | None):
    if task.request.retries >= MAX_PROVIDER_RETRIES:
        _dead_letter(job, reason, error)
        return "dead_lettered"

    job.status = EmailJob.Status.RETRYING
    job.last_error = error
    job.save(update_fields=["status", "last_error", "updated_at"])
    raise task.retry(
        exc=RuntimeError(error),
        countdown=_countdown(task.request.retries),
        kwargs={"job_id": job.id, "now": now},
    )


def enqueue_email(
    *,
    to_email: str,
    template: str,
    payload: dict | None = None,
    idempotency_key: str,
    delay: bool = True,
) -> tuple[EmailJob, bool]:
    job, created = EmailJob.objects.get_or_create(
        idempotency_key=idempotency_key,
        defaults={
            "to_email": to_email,
            "template": template,
            "payload": payload or {},
        },
    )
    if job.status in {EmailJob.Status.SENT, EmailJob.Status.DEAD_LETTER}:
        return job, created
    if delay:
        send_transactional_email.delay(job.id)
    return job, created
