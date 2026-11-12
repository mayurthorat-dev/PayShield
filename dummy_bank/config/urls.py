from django.contrib import admin
from django.urls import path, include
from django.http import JsonResponse
from payments.views import portal_view


def health_check(request):
    return JsonResponse({
        "project": "Dummy Bank",
        "status": "running",
    })


urlpatterns = [
    path("", portal_view, name="bank-portal"),
    path("portal/", portal_view, name="bank-portal-alt"),
    path("admin/", admin.site.urls),
    path("api/health/", health_check),
    path("api/transactions/", include("payments.urls")),
    path("api/otp/", include("otp.urls")),
    path("api/accounts/", include("accounts.urls")),
]
