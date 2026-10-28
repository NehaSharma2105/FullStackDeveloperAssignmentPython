from __future__ import annotations

import uuid

import pytest
from django.conf import settings

from apps.notifications.emails import provider
from apps.orders.models import Customer, Order, OrderItem, Product


@pytest.fixture(autouse=True)
def _email_isolation(settings):
    settings.EMAIL_PROVIDER = "fake"
    settings.EMAIL_RATE_LIMIT_KEY = f"test:email:{uuid.uuid4()}"
    provider.reset()
    yield
    provider.reset()


@pytest.fixture
def customer_with_orders(db):
    customer = Customer.objects.create(name="Test User", email="test@example.com")
    p1 = Product.objects.create(sku="A", name="Alpha", unit_price="10.00")
    p2 = Product.objects.create(sku="B", name="Beta", unit_price="5.00")
    for _ in range(25):
        order = Order.objects.create(customer=customer, status=Order.Status.PAID)
        OrderItem.objects.create(order=order, product=p1, quantity=1, unit_price="10.00")
        OrderItem.objects.create(order=order, product=p2, quantity=2, unit_price="5.00")
    return customer


@pytest.fixture
def require_redis():
    import redis
    from redis.exceptions import ConnectionError as RedisConnectionError

    client = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        client.ping()
    except (RedisConnectionError, OSError):
        pytest.skip("Redis is not running on REDIS_URL")
    yield client
