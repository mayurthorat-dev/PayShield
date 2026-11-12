import uuid
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import PayShieldUser
from banking.models import LinkedBankAccount


class Command(BaseCommand):
    help = "Seeds PayShield demo users (Rahul Sharma & Priya Patil) and their linked bank accounts."

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("Seeding default demo users in PayShield..."))

        demo_users = [
            {
                "phone": "9000000001",
                "name": "Rahul Sharma",
                "bank_acc_id": 1,
                "masked_acc": "•••• 0001",
                "customer_uuid": uuid.UUID("11111111-1111-1111-1111-111111111101"),
            },
            {
                "phone": "9000000002",
                "name": "Priya Patil",
                "bank_acc_id": 2,
                "masked_acc": "•••• 0002",
                "customer_uuid": uuid.UUID("22222222-2222-2222-2222-222222222202"),
            },
        ]

        with transaction.atomic():
            for item in demo_users:
                user = PayShieldUser.objects.filter(phone_number=item["phone"]).first()
                if not user:
                    user = PayShieldUser.create_user_with_phone(
                        phone_number=item["phone"],
                        full_name=item["name"],
                        is_phone_verified=True,
                    )
                    self.stdout.write(self.style.SUCCESS(f"Created user {item['name']} ({item['phone']})"))
                else:
                    if not user.is_phone_verified:
                        user.is_phone_verified = True
                        user.full_name = item["name"]
                        user.save(update_fields=["is_phone_verified", "full_name"])
                    self.stdout.write(self.style.SUCCESS(f"User {item['name']} ({item['phone']}) already exists."))

                # Ensure linked bank account exists
                linked_acc, created = LinkedBankAccount.objects.get_or_create(
                    user=user,
                    bank_account_id=item["bank_acc_id"],
                    defaults={
                        "bank_name": "PayShield Demo Bank",
                        "bank_customer_id": item["customer_uuid"],
                        "account_number_masked": item["masked_acc"],
                        "account_type": "SAVINGS",
                        "is_verified": True,
                        "status": "VERIFIED",
                        "is_active": True,
                    },
                )
                if created:
                    self.stdout.write(self.style.SUCCESS(f"Linked bank account {item['masked_acc']} to {item['name']}."))

        self.stdout.write(self.style.SUCCESS("PayShield demo seeding complete!"))
