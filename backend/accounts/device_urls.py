from django.urls import path
from .device_views import (
    get_device_status,
    register_device,
    replace_device,
    request_replacement_otp,
    revoke_device,
    update_push_token,
)

urlpatterns = [
    path("status/", get_device_status, name="device-status"),
    path("register/", register_device, name="device-register"),
    path("replace/request-otp/", request_replacement_otp, name="device-replace-request-otp"),
    path("replace/", replace_device, name="device-replace"),
    path("revoke/", revoke_device, name="device-revoke"),
    path("push-token/", update_push_token, name="device-update-push-token"),
]

