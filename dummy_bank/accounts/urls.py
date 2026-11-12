from django.urls import path
from .views import discover_accounts_by_phone, verify_account_link

urlpatterns = [
    path("verify-link/", verify_account_link, name="verify-account-link"),
    path("discover/", discover_accounts_by_phone, name="discover-accounts"),
]

