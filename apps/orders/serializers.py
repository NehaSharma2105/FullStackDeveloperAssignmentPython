"""Serializers that walk related objects.

The N+1 is not in the view's queryset assignment. It appears when the
serializer (or a shared helper) accesses `order.customer`, `order.items`,
and `item.product` — the kind of adjacent change that can ship without
editing the view file itself.
"""

from decimal import Decimal


def serialize_order_naive(order) -> dict:
    # Each of these attribute accesses can emit SQL if the queryset was bare.
    customer_name = order.customer.name
    items = []
    total = Decimal("0.00")
    for item in order.items.all():
        line_total = item.line_total
        total += line_total
        items.append(
            {
                "sku": item.product.sku,
                "product": item.product.name,
                "quantity": item.quantity,
                "unit_price": str(item.unit_price),
                "line_total": str(line_total),
            }
        )
    return {
        "id": order.id,
        "status": order.status,
        "placed_at": order.placed_at.isoformat(),
        "customer_name": customer_name,
        "item_count": len(items),
        "total": str(total),
        "items": items,
    }


def serialize_summary(customer, orders) -> dict:
    payload_orders = [serialize_order_naive(order) for order in orders]
    grand_total = sum((Decimal(o["total"]) for o in payload_orders), Decimal("0.00"))
    return {
        "customer_id": customer.id,
        "customer_name": customer.name,
        "order_count": len(payload_orders),
        "total_spent": str(grand_total),
        "orders": payload_orders,
    }
