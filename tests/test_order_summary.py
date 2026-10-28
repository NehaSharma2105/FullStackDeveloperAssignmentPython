from __future__ import annotations

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from apps.orders.querysets import naive_orders_queryset, optimized_orders_queryset
from apps.orders.serializers import serialize_order_naive


@pytest.mark.django_db
def test_summary_payload_is_correct(customer_with_orders):
    customer = customer_with_orders
    response = APIClient().get("/api/orders/summary/", {"customer_id": customer.id})
    assert response.status_code == 200
    body = response.json()
    assert body["customer_id"] == customer.id
    assert body["order_count"] == 25
    assert body["total_spent"] == "500.00"
    first = body["orders"][0]
    assert {item["sku"] for item in first["items"]} == {"A", "B"}
    assert first["item_count"] == 2
    assert first["total"] == "20.00"


@pytest.mark.django_db
def test_summary_requires_customer_id():
    response = APIClient().get("/api/orders/summary/")
    assert response.status_code == 400


@pytest.mark.django_db
def test_summary_404_for_unknown_customer():
    response = APIClient().get("/api/orders/summary/", {"customer_id": 999999})
    assert response.status_code == 404


@pytest.mark.django_db
def test_query_count_regresses_without_prefetch(customer_with_orders):
    customer = customer_with_orders
    order_count = customer.orders.count()

    with CaptureQueriesContext(connection) as naive:
        for order in naive_orders_queryset(customer.id):
            serialize_order_naive(order)

    with CaptureQueriesContext(connection) as optimized:
        for order in optimized_orders_queryset(customer.id):
            serialize_order_naive(order)

    # Naive: 1 orders query + 1 customer + 1 items + 2 products per order (uncached FKs).
    assert len(naive) >= 1 + order_count * 2
    assert len(optimized) <= 5
    assert len(optimized) < len(naive)


@pytest.mark.django_db
def test_endpoint_stays_within_query_budget(customer_with_orders):
    customer = customer_with_orders
    client = APIClient()

    with CaptureQueriesContext(connection) as ctx:
        response = client.get("/api/orders/summary/", {"customer_id": customer.id})

    assert response.status_code == 200
    assert len(ctx) <= 8


@pytest.mark.django_db
def test_naive_flag_uses_more_queries(customer_with_orders):
    customer = customer_with_orders
    client = APIClient()

    with CaptureQueriesContext(connection) as naive:
        naive_resp = client.get(
            "/api/orders/summary/",
            {"customer_id": customer.id, "naive": "1"},
        )
    with CaptureQueriesContext(connection) as optimized:
        opt_resp = client.get("/api/orders/summary/", {"customer_id": customer.id})

    assert naive_resp.status_code == 200
    assert opt_resp.status_code == 200
    assert naive_resp.json()["total_spent"] == opt_resp.json()["total_spent"]
    assert len(naive) > len(optimized)
