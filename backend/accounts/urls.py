from django.urls import path
from .views import (
    get_current_user_profile,
    logout_user,
    register_user,
    request_login_otp,
    verify_login_otp,
)

urlpatterns = [
    path("register/", register_user, name="auth-register"),
    path("request-otp/", request_login_otp, name="auth-request-otp"),
    path("verify-otp/", verify_login_otp, name="auth-verify-otp"),
    path("me/", get_current_user_profile, name="auth-me"),
    path("logout/", logout_user, name="auth-logout"),
]
