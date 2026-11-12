from django.urls import path
from .views import receive_transaction_context

urlpatterns = [
    path(
        "transaction-context/",
        receive_transaction_context,
        name="receive-transaction-context",
    ),
]