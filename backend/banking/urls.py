from django.urls import path
from .views import (
    discover_bank_accounts,
    initiate_link_account,
    link_and_verify_account,
    link_discovered_account,
    list_linked_accounts,
    unlink_account,
    verify_link_account,
)

urlpatterns = [
    path("accounts/", list_linked_accounts, name="list-linked-accounts"),
    path("accounts/discover/", discover_bank_accounts, name="discover-bank-accounts"),
    path(
        "accounts/link-discovered/",
        link_discovered_account,
        name="link-discovered-account",
    ),
    path(
        "accounts/<int:link_id>/unlink/",
        unlink_account,
        name="unlink-account",
    ),
    path("accounts/initiate/", initiate_link_account, name="initiate-link-account"),
    path(
        "accounts/<int:link_id>/verify/",
        verify_link_account,
        name="verify-link-account",
    ),
    path(
        "accounts/link-and-verify/",
        link_and_verify_account,
        name="link-and-verify-account",
    ),
]

