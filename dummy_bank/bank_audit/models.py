from django.db import models
from payments.models import BankTransaction


class BankTransactionEvent(models.Model):

    event_id = models.BigAutoField(primary_key=True)

    transaction = models.ForeignKey(
        BankTransaction,
        on_delete=models.PROTECT,
        related_name="events"
    )

    event_type = models.CharField(max_length=50)
    description = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.event_type} - {self.transaction_id}"