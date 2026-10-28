from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status

from apps.orders.models import Customer
from apps.orders.querysets import naive_orders_queryset, optimized_orders_queryset
from apps.orders.serializers import serialize_summary


@api_view(["GET"])
def order_summary(request):
    """Mobile dashboard summary.

    Default path is the fixed queryset. Pass ?naive=1 to reproduce the
    N+1 behaviour for Silk / query-count comparison.
    """
    customer_id = request.query_params.get("customer_id")
    if not customer_id:
        return Response(
            {"detail": "customer_id query parameter is required."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        customer = Customer.objects.get(pk=int(customer_id))
    except (Customer.DoesNotExist, ValueError):
        return Response({"detail": "Customer not found."}, status=status.HTTP_404_NOT_FOUND)

    naive = request.query_params.get("naive") == "1"
    orders = (
        naive_orders_queryset(customer.id)
        if naive
        else optimized_orders_queryset(customer.id)
    )
    return Response(serialize_summary(customer, orders))
