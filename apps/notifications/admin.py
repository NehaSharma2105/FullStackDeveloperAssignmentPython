from django.contrib import admin

from apps.notifications.models import EmailDeadLetter, EmailJob


@admin.register(EmailJob)
class EmailJobAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "idempotency_key",
        "to_email",
        "template",
        "status",
        "attempts",
        "created_at",
    )
    list_filter = ("status", "template")
    search_fields = ("idempotency_key", "to_email")


@admin.register(EmailDeadLetter)
class EmailDeadLetterAdmin(admin.ModelAdmin):
    list_display = ("id", "job", "reason", "created_at")
    search_fields = ("job__idempotency_key", "reason")
