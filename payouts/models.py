import uuid

from django.db import models
from django.db.models import Sum
from django.db.models.functions import Coalesce


class Merchant(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    email = models.EmailField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "merchants"

    def __str__(self):
        return self.name

    @property
    def available_balance(self):
        """Balance derived from ledger. Never stored, always computed."""
        result = self.ledger_entries.aggregate(
            balance=Coalesce(Sum("amount_paise"), 0)
        )
        return result["balance"]

    @property
    def held_balance(self):
        """Sum of funds held by pending/processing payouts."""
        result = self.ledger_entries.filter(
            entry_type=LedgerEntry.EntryType.DEBIT,
            payout__status__in=[Payout.Status.PENDING, Payout.Status.PROCESSING],
        ).aggregate(
            held=Coalesce(Sum("amount_paise"), 0)
        )
        # Debits are stored as negative, so negate to get positive held amount
        return abs(result["held"])


class BankAccount(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    merchant = models.ForeignKey(
        Merchant, on_delete=models.CASCADE, related_name="bank_accounts"
    )
    account_number = models.CharField(max_length=20)
    ifsc = models.CharField(max_length=11)
    account_holder_name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "bank_accounts"

    def __str__(self):
        return f"{self.account_holder_name} - {self.account_number[-4:]}"


class LedgerEntry(models.Model):
    """
    Immutable ledger entry. Balance is always SUM(amount_paise) for a merchant.
    - credit:   positive amount (customer payment received)
    - debit:    negative amount (funds held for payout)
    - reversal: positive amount (funds returned on failed payout)
    """

    class EntryType(models.TextChoices):
        CREDIT = "credit", "Credit"
        DEBIT = "debit", "Debit"
        REVERSAL = "reversal", "Reversal"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    merchant = models.ForeignKey(
        Merchant, on_delete=models.CASCADE, related_name="ledger_entries"
    )
    entry_type = models.CharField(max_length=10, choices=EntryType.choices)
    amount_paise = models.BigIntegerField(
        help_text="Positive for credit/reversal, negative for debit"
    )
    payout = models.ForeignKey(
        "Payout",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ledger_entries",
    )
    description = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ledger_entries"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["merchant", "created_at"]),
            models.Index(fields=["merchant", "entry_type"]),
        ]

    def __str__(self):
        return f"{self.entry_type} {self.amount_paise} paise - {self.merchant.name}"


class Payout(models.Model):
    """
    Payout lifecycle: pending -> processing -> completed | failed
    No backward transitions allowed.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    # Legal state transitions
    ALLOWED_TRANSITIONS = {
        "pending": {"processing"},
        "processing": {"completed", "failed"},
        "completed": set(),  # terminal state
        "failed": set(),  # terminal state
    }

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    merchant = models.ForeignKey(
        Merchant, on_delete=models.CASCADE, related_name="payouts"
    )
    bank_account = models.ForeignKey(
        BankAccount, on_delete=models.PROTECT, related_name="payouts"
    )
    amount_paise = models.BigIntegerField()
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING
    )
    idempotency_key = models.CharField(max_length=64, blank=True, default="")
    attempts = models.IntegerField(default=0)
    last_attempted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "payouts"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["merchant", "status"]),
            models.Index(fields=["status", "updated_at"]),
        ]

    def __str__(self):
        return f"Payout {self.id} - {self.amount_paise} paise ({self.status})"

    def transition_to(self, new_status):
        """
        Enforce state machine. Raises ValueError on illegal transition.
        This is where failed->completed is blocked.
        Also creates an audit log entry for observability.
        """
        allowed = self.ALLOWED_TRANSITIONS.get(self.status, set())
        if new_status not in allowed:
            raise ValueError(
                f"Illegal state transition: {self.status} -> {new_status}"
            )
        old_status = self.status
        self.status = new_status
        self.save(update_fields=["status", "updated_at"])

        # Record the transition for audit trail
        PayoutAuditLog.objects.create(
            payout=self,
            from_status=old_status,
            to_status=new_status,
        )


class IdempotencyKey(models.Model):
    """
    Stores idempotency keys per merchant to prevent duplicate payout creation.
    Keys expire after 24 hours.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    merchant = models.ForeignKey(
        Merchant, on_delete=models.CASCADE, related_name="idempotency_keys"
    )
    key = models.CharField(max_length=64)
    response_body = models.JSONField(null=True, blank=True)
    status_code = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        db_table = "idempotency_keys"
        constraints = [
            models.UniqueConstraint(
                fields=["merchant", "key"],
                name="unique_merchant_idempotency_key",
            )
        ]

    def __str__(self):
        return f"{self.merchant.name} - {self.key}"


class PayoutAuditLog(models.Model):
    """
    Immutable audit trail for every payout state transition.
    Records who changed what, when, and from/to which state.
    Critical for debugging money-moving systems in production.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    payout = models.ForeignKey(
        Payout, on_delete=models.CASCADE, related_name="audit_logs"
    )
    from_status = models.CharField(max_length=10)
    to_status = models.CharField(max_length=10)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "payout_audit_logs"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["payout", "created_at"]),
        ]

    def __str__(self):
        return f"Payout {self.payout_id}: {self.from_status} → {self.to_status}"
