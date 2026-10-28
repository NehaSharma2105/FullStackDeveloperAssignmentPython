from django.db import models


class EmailJob(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        SENDING = "sending", "Sending"
        SENT = "sent", "Sent"
        RETRYING = "retrying", "Retrying"
        DEAD_LETTER = "dead_letter", "Dead letter"

    idempotency_key = models.CharField(max_length=64, unique=True)
    to_email = models.EmailField()
    template = models.CharField(max_length=64)
    payload = models.JSONField(default=dict)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.QUEUED, db_index=True
    )
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True)
    provider_message_id = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.idempotency_key} ({self.status})"


class EmailDeadLetter(models.Model):
    """Permanent failures after bounded retries, or non-retryable provider errors."""

    job = models.OneToOneField(
        EmailJob, on_delete=models.CASCADE, related_name="dead_letter"
    )
    reason = models.CharField(max_length=120)
    error = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"DLQ {self.job.idempotency_key}: {self.reason}"
