"""Querysets for /api/orders/summary/.

`naive_orders_queryset` is the post-deploy regression: a filter on Order
with no related-object loading. The view still looks like
`Order.objects.filter(customer=...)`.

`optimized_orders_queryset` is the fix:
- select_related("customer") because Customer is a ForeignKey (SQL JOIN)
- prefetch_related("items__product") because items are reverse FK + nested FK
"""

from apps.orders.models import Order


def naive_orders_queryset(customer_id: int):
    return Order.objects.filter(customer_id=customer_id).order_by("-placed_at", "-id")


def optimized_orders_queryset(customer_id: int):
    return (
        Order.objects.filter(customer_id=customer_id)
        .select_related("customer")
        .prefetch_related("items__product")
        .order_by("-placed_at", "-id")
    )
