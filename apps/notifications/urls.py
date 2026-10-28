from django.urls import path

from apps.notifications.views import EnqueueEmailView

urlpatterns = [
    path("emails/", EnqueueEmailView.as_view(), name="enqueue-email"),
]
