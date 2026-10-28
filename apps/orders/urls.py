from django.urls import path

from apps.orders.views import order_summary

urlpatterns = [
    path("summary/", order_summary, name="order-summary"),
]
