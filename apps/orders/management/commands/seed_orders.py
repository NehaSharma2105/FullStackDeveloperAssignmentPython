from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.orders.models import Customer, Order, OrderItem, Product


class Command(BaseCommand):
    help = "Create a customer with many orders so the N+1 summary endpoint is visible."

    def add_arguments(self, parser):
        parser.add_argument("--orders", type=int, default=220)
        parser.add_argument("--items-per-order", type=int, default=3)

    @transaction.atomic
    def handle(self, *args, **options):
        order_count = options["orders"]
        items_per_order = options["items_per_order"]

        customer, _ = Customer.objects.get_or_create(
            email="dashboard@example.com",
            defaults={"name": "Priya Dashboard"},
        )
        products = []
        for i in range(items_per_order):
            product, _ = Product.objects.get_or_create(
                sku=f"SKU-{i+1:03d}",
                defaults={
                    "name": f"Widget {i+1}",
                    "unit_price": Decimal("19.99") + i,
                },
            )
            products.append(product)

        existing = customer.orders.count()
        to_create = max(0, order_count - existing)
        orders = [Order(customer=customer, status=Order.Status.PAID) for _ in range(to_create)]
        Order.objects.bulk_create(orders)
        # Re-fetch so we have PKs for items.
        recent = list(customer.orders.order_by("-id")[:to_create] if to_create else [])
        items = []
        for order in recent:
            for idx, product in enumerate(products):
                items.append(
                    OrderItem(
                        order=order,
                        product=product,
                        quantity=idx + 1,
                        unit_price=product.unit_price,
                    )
                )
        OrderItem.objects.bulk_create(items)

        self.stdout.write(
            self.style.SUCCESS(
                f"Customer {customer.id} ({customer.email}) has "
                f"{customer.orders.count()} orders. "
                f"GET /api/orders/summary/?customer_id={customer.id}"
            )
        )
