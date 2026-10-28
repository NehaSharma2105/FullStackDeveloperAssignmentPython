"""Django settings for the assessment project.

Local defaults favour a 5-minute Windows setup: SQLite + Redis.
Secrets come from the environment / optional .env file.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-only-insecure-key-change-me")
DEBUG = os.getenv("DJANGO_DEBUG", "true").lower() in {"1", "true", "yes"}
ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")
    if host.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "silk",
    "apps.orders.apps.OrdersConfig",
    "apps.notifications.apps.NotificationsConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "silk.middleware.SilkyMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
}

# Silk: keep profiling on in local DEBUG. Tests disable it via SILKY_INTERCEPT_PERCENT.
SILKY_PYTHON_PROFILER = False
SILKY_AUTHENTICATION = False
SILKY_AUTHORISATION = False
SILKY_META = True
if os.getenv("PYTEST_VERSION"):
    SILKY_INTERCEPT_PERCENT = 0
    MIDDLEWARE = [mw for mw in MIDDLEWARE if mw != "silk.middleware.SilkyMiddleware"]
    CELERY_TASK_ALWAYS_EAGER = True
    CELERY_TASK_EAGER_PROPAGATES = True

REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://127.0.0.1:6379/1")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://127.0.0.1:6379/2")

# At-least-once delivery: ack after the task returns. A SIGKILL before ack redelivers.
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_ACKS_ON_FAILURE_OR_TIMEOUT = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_BROKER_TRANSPORT_OPTIONS = {
    # Must exceed the longest expected task runtime, including backoff waits
    # that Celery applies in the worker. Too low → duplicate execution.
    "visibility_timeout": 3600,
}
CELERY_RESULT_EXPIRES = 3600
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TIMEZONE = "UTC"

# Rate limiter (provider: 200 accepted send attempts / rolling 60s).
EMAIL_RATE_LIMIT = int(os.getenv("EMAIL_RATE_LIMIT", "200"))
EMAIL_RATE_WINDOW_SECONDS = int(os.getenv("EMAIL_RATE_WINDOW_SECONDS", "60"))
EMAIL_RATE_LIMIT_ON_REDIS_ERROR = os.getenv(
    "EMAIL_RATE_LIMIT_ON_REDIS_ERROR", "fail_closed"
)
EMAIL_PROVIDER = os.getenv("EMAIL_PROVIDER", "fake")
EMAIL_RATE_LIMIT_KEY = "email:send:rolling-window"
