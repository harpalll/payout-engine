"""
Core business logic for payout creation.

Handles concurrency (SELECT FOR UPDATE), idempotency (DB-level key locking),
and atomic fund holds.
"""

from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from .models import IdempotencyKey, LedgerEntry, Merchant, Payout
from .serializers import PayoutSerializer


class InsufficientBalance(Exception):
    pass


class PayoutCreationError(Exception):
    pass


def create_payout(merchant_id, amount_paise, bank_account_id, idempotency_key):
    """
    Create a payout with idempotency and concurrency protection.
    Returns (response_data, status_code, created).
    """
    # Check idempotency BEFORE acquiring the merchant lock
    existing_key = _check_idempotency_key(merchant_id, idempotency_key)
    if existing_key is not None:
        return existing_key.response_body, existing_key.status_code, False

    with transaction.atomic():
        # Row-level exclusive lock — blocks concurrent payout attempts
        merchant = Merchant.objects.select_for_update().get(id=merchant_id)

        # Balance check via DB aggregate inside the locked transaction
        available = LedgerEntry.objects.filter(merchant=merchant).aggregate(
            balance=Coalesce(Sum("amount_paise"), 0)
        )["balance"]

        if available < amount_paise:
            error_response = {
                "error": "insufficient_balance",
                "detail": f"Available balance is {available} paise, "
                          f"requested {amount_paise} paise.",
                "available_balance": available,
            }
            _store_idempotency_response(
                merchant, idempotency_key, error_response, 400
            )
            raise InsufficientBalance(error_response["detail"])

        payout = Payout.objects.create(
            merchant=merchant,
            bank_account_id=bank_account_id,
            amount_paise=amount_paise,
            status=Payout.Status.PENDING,
            idempotency_key=idempotency_key,
        )

        # Debit entry holds funds immediately
        LedgerEntry.objects.create(
            merchant=merchant,
            entry_type=LedgerEntry.EntryType.DEBIT,
            amount_paise=-amount_paise,
            payout=payout,
            description=f"Payout hold - {payout.id}",
        )

        response_data = PayoutSerializer(payout).data
        _store_idempotency_response(
            merchant, idempotency_key, response_data, 201
        )

    # Queue after commit so the worker never sees a nonexistent payout
    from .tasks import process_payout
    process_payout.delay(str(payout.id))

    return response_data, 201, True


def _check_idempotency_key(merchant_id, key):
    """
    Returns the stored IdempotencyKey if this key was already used,
    or None if it's a new key. Uses SELECT FOR UPDATE to handle the
    race where two requests arrive with the same key simultaneously.
    """
    try:
        with transaction.atomic():
            record = (
                IdempotencyKey.objects
                .select_for_update()
                .get(
                    merchant_id=merchant_id,
                    key=key,
                    expires_at__gt=timezone.now(),
                )
            )
            if record.response_body is not None:
                return record
            # First request failed before storing response — clean up
            record.delete()
            return None
    except IdempotencyKey.DoesNotExist:
        return None


def _store_idempotency_response(merchant, key, response_body, status_code):
    """Store or update the idempotency record with the response."""
    expires_at = timezone.now() + timedelta(hours=24)

    try:
        record, created = IdempotencyKey.objects.get_or_create(
            merchant=merchant,
            key=key,
            defaults={
                "response_body": response_body,
                "status_code": status_code,
                "expires_at": expires_at,
            },
        )
        if not created:
            record.response_body = response_body
            record.status_code = status_code
            record.expires_at = expires_at
            record.save(update_fields=["response_body", "status_code", "expires_at"])
    except IntegrityError:
        pass
