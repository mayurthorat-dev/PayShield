import os
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model


class Command(BaseCommand):
    help = "Creates or updates the superuser account from secure environment variables."

    def handle(self, *args, **options):
        User = get_user_model()
        username = os.getenv("DJANGO_SUPERUSER_USERNAME") or os.getenv("ADMIN_USERNAME")
        password = os.getenv("DJANGO_SUPERUSER_PASSWORD") or os.getenv("ADMIN_PASSWORD")
        email = os.getenv("DJANGO_SUPERUSER_EMAIL") or os.getenv("ADMIN_EMAIL", "admin@payshield.com")

        if not username or not password:
            self.stdout.write(
                self.style.WARNING(
                    "ADMIN_USERNAME and ADMIN_PASSWORD environment variables not configured. Skipping admin creation."
                )
            )
            return

        user, created = User.objects.get_or_create(
            username=username,
            defaults={
                "email": email,
                "is_staff": True,
                "is_superuser": True,
                "is_active": True,
            },
        )
        user.set_password(password)
        user.is_staff = True
        user.is_superuser = True
        user.is_active = True
        user.save()

        if created:
            self.stdout.write(self.style.SUCCESS(f"Superuser '{username}' created successfully."))
        else:
            self.stdout.write(self.style.SUCCESS(f"Superuser '{username}' updated successfully."))

