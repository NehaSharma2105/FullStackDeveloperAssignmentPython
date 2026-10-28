"""Fake transactional email provider.

Local runs and tests never open SMTP or call a vendor API.
The provider records attempts so tests can assert retries and duplicates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from typing import Any

from apps.notifications.exceptions import PermanentProviderError, TransientProviderError


@dataclass
class SendRecord:
    to_email: str
    template: str
    idempotency_key: str
    timestamp: float


@dataclass
class FakeEmailProvider:
    sent: list[SendRecord] = field(default_factory=list)
    attempts: list[SendRecord] = field(default_factory=list)
    fail_permanent_for: set[str] = field(default_factory=set)
    transient_failures_remaining: dict[str, int] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock)
    _seq: int = 0

    def reset(self) -> None:
        with self._lock:
            self.sent.clear()
            self.attempts.clear()
            self.fail_permanent_for.clear()
            self.transient_failures_remaining.clear()
            self._seq = 0

    def send(
        self,
        *,
        to_email: str,
        template: str,
        payload: dict[str, Any],
        idempotency_key: str,
        now: float,
    ) -> str:
        record = SendRecord(
            to_email=to_email,
            template=template,
            idempotency_key=idempotency_key,
            timestamp=now,
        )
        with self._lock:
            self.attempts.append(record)
            if idempotency_key in self.fail_permanent_for or to_email.endswith(
                "@fail-permanent.example"
            ):
                raise PermanentProviderError(f"rejected {to_email}")
            remaining = self.transient_failures_remaining.get(idempotency_key, 0)
            if remaining > 0:
                self.transient_failures_remaining[idempotency_key] = remaining - 1
                raise TransientProviderError("provider timeout")
            if to_email.endswith("@fail-transient.example"):
                raise TransientProviderError("provider timeout")
            existing = next(
                (item for item in self.sent if item.idempotency_key == idempotency_key),
                None,
            )
            if existing:
                return f"dup-{existing.idempotency_key}"
            self._seq += 1
            self.sent.append(record)
            return f"msg-{self._seq}"


provider = FakeEmailProvider()
