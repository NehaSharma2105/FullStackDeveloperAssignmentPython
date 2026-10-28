"""Compare naive vs optimized /api/orders/summary/ query counts.

Uses Django's connection.queries (DEBUG=True). Also prints how to open Silk.
This script records genuine counts from this machine; it does not invent them.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from django.conf import settings
from django.db import connection, reset_queries
from django.test.utils import CaptureQueriesContext
from django.test import Client

from apps.orders.models import Customer


def run() -> None:
    if not settings.DEBUG:
        print("DEBUG must be True to collect connection.queries.")
        sys.exit(1)

    customer = Customer.objects.order_by("id").first()
    if customer is None:
        print("No customer found. Run: python manage.py seed_orders")
        sys.exit(1)

    client = Client()
    results = {}
    for label, naive in (("naive", "1"), ("optimized", "0")):
        with CaptureQueriesContext(connection) as ctx:
            response = client.get(
                "/api/orders/summary/",
                {"customer_id": customer.id, "naive": naive},
            )
        results[label] = {
            "status": response.status_code,
            "order_count": response.json().get("order_count"),
            "queries": len(ctx),
        }

    print(f"customer_id={customer.id}")
    print(f"naive      queries={results['naive']['queries']} status={results['naive']['status']} orders={results['naive']['order_count']}")
    print(f"optimized  queries={results['optimized']['queries']} status={results['optimized']['status']} orders={results['optimized']['order_count']}")
    print()
    print("Silk UI (when the dev server is running): http://127.0.0.1:8000/silk/")
    print("Reproduce in Silk: hit the naive URL then the optimized URL and compare SQL counts.")


if __name__ == "__main__":
    reset_queries()
    run()
