from datetime import timedelta
from django.conf import settings
from django.utils import timezone
from rest_framework import exceptions
from rest_framework.authentication import TokenAuthentication


class ExpiringTokenAuthentication(TokenAuthentication):
    """
    Extends Django REST Framework's standard TokenAuthentication to enforce
    token expiration. Tokens older than PAYSHIELD_TOKEN_LIFETIME_HOURS are revoked.
    """

    def authenticate_credentials(self, key):
        model = self.get_model()
        try:
            token = model.objects.select_related("user").get(key=key)
        except model.DoesNotExist:
            raise exceptions.AuthenticationFailed("Invalid or unknown authentication token.")

        if not token.user.is_active:
            raise exceptions.AuthenticationFailed("User account is inactive or disabled.")

        lifetime_hours = getattr(settings, "PAYSHIELD_TOKEN_LIFETIME_HOURS", 24)
        token_age = timezone.now() - token.created

        if token_age > timedelta(hours=lifetime_hours):
            token.delete()
            raise exceptions.AuthenticationFailed(
                "Authentication token has expired. Please log in again."
            )

        return (token.user, token)

