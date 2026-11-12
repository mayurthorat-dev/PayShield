from django.db import models
import uuid


class BankCustomer(models.Model):
    customer_id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )
    full_name = models.CharField(max_length=100)
    email = models.EmailField(unique=True)
    phone_number = models.CharField(max_length=15, unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.full_name