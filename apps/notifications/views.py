from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.notifications.tasks import enqueue_email


class EnqueueEmailView(APIView):
    """Enqueue a fake transactional email for local demos. Never sends real mail."""

    def post(self, request: Request) -> Response:
        data = request.data
        required = ("to_email", "template", "idempotency_key")
        missing = [field for field in required if not data.get(field)]
        if missing:
            return Response({"detail": f"missing fields: {missing}"}, status=400)
        job, created = enqueue_email(
            to_email=data["to_email"],
            template=data["template"],
            payload=data.get("payload") or {},
            idempotency_key=data["idempotency_key"],
        )
        return Response(
            {
                "job_id": job.id,
                "created": created,
                "status": job.status,
                "idempotency_key": job.idempotency_key,
            },
            status=202 if created else 200,
        )
