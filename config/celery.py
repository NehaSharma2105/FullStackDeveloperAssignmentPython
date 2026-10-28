import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("fullstack_assessment")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
if os.environ.get("PYTEST_VERSION"):
    app.conf.task_always_eager = True
    app.conf.task_eager_propagates = True
