import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.orders.querysets import naive_orders_queryset, optimized_orders_queryset


@pytest.mark.django_db
def test_summary_payload(client, customer_with_orders):
    url = reverse("order-summary")
    response = client.get(url, {"customer_id": customer_with_orders.id})
    assert response.status_code == 200
    body = response.json()
    assert body["order_count"] == 25
    assert body["customer_name"] == "Test User"
    assert len(body["orders"]) == 25
    first = body["orders"][0]
    assert first["item_count"] == 2
    assert first["total"] == "20.00"
    assert {item["sku"] for item in first["items"]} == {"A", "B"}


@pytest.mark.django_db
def test_summary_requires_customer(client):
    response = client.get(reverse("order-summary"))
    assert response.status_code == 400


@pytest.mark.django_db
def test_optimized_queryset_avoids_n_plus_one(customer_with_orders):
    naive = naive_orders_queryset(customer_with_orders.id)
    optimized = optimized_orders_queryset(customer_with_orders.id)

    def consume(qs):
        total_items = 0
        for order in qs:
            total_items += len(list(order.items.all()))
            _ = order.customer.name
            for item in order.items.all():
                _ = item.product.name
        return total_items

    with CaptureQueriesContext(connection) as naive_ctx:
        consume(naive)
    with CaptureQueriesContext(connection) as opt_ctx:
        consume(optimized)

    # 25 orders * (customer + items + 2 products) is far above the optimized path.
    assert len(naive_ctx) > 50
    # orders JOIN customer, prefetch items, prefetch products — small constant.
    assert len(opt_ctx) <= 5
    assert len(opt_ctx) < len(naive_ctx)


@pytest.mark.django_db
def test_endpoint_query_count_regression_guard(client, customer_with_orders):
    url = reverse("order-summary")
    with CaptureQueriesContext(connection) as ctx:
        response = client.get(url, {"customer_id": customer_with_orders.id})
    assert response.status_code == 200
    # Customer lookup + orders/select_related + items prefetch + products prefetch.
    assert len(ctx) <= 8
