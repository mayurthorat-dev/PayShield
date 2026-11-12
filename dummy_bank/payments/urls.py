from django.urls import path
from .views import (
    TransactionCreateView,
    portal_data_api,
    portal_view,
    receive_payshield_decision,
    transaction_status_api,
)

urlpatterns = [
    path("portal/", portal_view, name="portal-view"),
    path("portal-data/", portal_data_api, name="portal-data"),
    path(
        "create/",
        TransactionCreateView.as_view(),
        name="transaction-create",
    ),
    path(
        "payshield-decision/",
        receive_payshield_decision,
        name="payshield-decision",
    ),
    path(
        "<uuid:transaction_id>/status/",
        transaction_status_api,
        name="transaction-status",
    ),
]
