from django.contrib import admin
from django.urls import path, include
from django.http import JsonResponse


def health_check(request):
    return JsonResponse({
        "project": "PayShield",
        "status": "running",
        "message": "PayShield backend is working!"
    })


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", health_check),
    path("api/auth/", include("accounts.urls")),
    path("api/accounts/", include("accounts.urls")),
    path("api/devices/", include("accounts.device_urls")),
    path("api/integration/", include("transactions.urls")),
    path("api/approvals/", include("authorization.urls")),
    path("api/banking/", include("banking.urls")),
]
