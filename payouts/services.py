"""
Core business logic for payout creation.

This module contains the critical transactional logic that ensures:
1. No overdrafts via SELECT FOR UPDATE locking
2. No duplicate payouts via idempotency key handling
3. Atomic fund holds and releases
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

    Flow:
    1. Check idempotency key — if seen before, return stored response
    2. Acquire merchant lock (SELECT FOR UPDATE)
    3. Verify sufficient balance via DB aggregate
    4. Create payout (pending) + debit ledger entry (negative) atomically
    5. Store response in idempotency record

    Returns:
        tuple: (response_data: dict, status_code: int, created: bool)
    """

    # ---------------------------------------------------------------
    # Step 1: Idempotency check
    # We do this BEFORE acquiring the merchant lock to avoid holding
    # the expensive row lock for duplicate requests.
    # ---------------------------------------------------------------
    existing_key = _check_idempotency_key(merchant_id, idempotency_key)
    if existing_key is not None:
        return existing_key.response_body, existing_key.status_code, False

    # ---------------------------------------------------------------
    # Step 2-4: Lock merchant, verify balance, create payout — all atomic
    # ---------------------------------------------------------------
    with transaction.atomic():
        # ACQUIRE LOCK: SELECT ... FOR UPDATE on the merchant row.
        # This is a PostgreSQL row-level exclusive lock. Any other transaction
        # that tries to SELECT FOR UPDATE on the same merchant will BLOCK here
        # until this transaction commits or rolls back.
        #
        # This prevents two concurrent payout requests from both reading the
        # same balance and both passing the sufficiency check.
        merchant = Merchant.objects.select_for_update().get(id=merchant_id)

        # BALANCE CHECK: Compute via DB aggregate, not Python arithmetic.
        # This runs inside the same transaction that holds the lock, so
        # no other transaction can insert ledger entries for this merchant
        # while we're checking.
        available = LedgerEntry.objects.filter(merchant=merchant).aggregate(
            balance=Coalesce(Sum("amount_paise"), 0)
        )["balance"]

        if available < amount_paise:
            # Insufficient funds — store the rejection in idempotency record
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

        # CREATE PAYOUT: In pending state, ready for background processing.
        payout = Payout.objects.create(
            merchant=merchant,
            bank_account_id=bank_account_id,
            amount_paise=amount_paise,
            status=Payout.Status.PENDING,
            idempotency_key=idempotency_key,
        )

        # HOLD FUNDS: Create a debit ledger entry with negative amount.
        # This immediately reduces the merchant's available balance.
        # The debit is linked to the payout so we can reverse it on failure.
        LedgerEntry.objects.create(
            merchant=merchant,
            entry_type=LedgerEntry.EntryType.DEBIT,
            amount_paise=-amount_paise,  # negative = reduces balance
            payout=payout,
            description=f"Payout hold - {payout.id}",
        )

        # Serialize the response
        response_data = PayoutSerializer(payout).data

        # Store successful response in idempotency record
        _store_idempotency_response(
            merchant, idempotency_key, response_data, 201
        )

    # Queue background processing AFTER the transaction commits.
    # If we queued inside the transaction and it rolled back,
    # the worker would try to process a nonexistent payout.
    from .tasks import process_payout
    process_payout.delay(str(payout.id))

    return response_data, 201, True


def _check_idempotency_key(merchant_id, key):
    """
    Check if we've seen this idempotency key before.

    Uses SELECT FOR UPDATE on the IdempotencyKey row so that if two requests
    arrive simultaneously with the same key:
    - First request creates the row and proceeds
    - Second request blocks at the DB level until the first commits
    - Then reads the stored response and returns it

    This eliminates the race window between "check if key exists" and
    "create the key". Without the lock, both requests could see "key doesn't
    exist" and both proceed to create duplicate payouts.

    Returns:
        IdempotencyKey or None
    """
    try:
        with transaction.atomic():
            idempotency_record = (
                IdempotencyKey.objects
                .select_for_update()
                .get(
                    merchant_id=merchant_id,
                    key=key,
                    expires_at__gt=timezone.now(),
                )
            )
            # Key exists and hasn't expired.
            # select_for_update blocks until any concurrent transaction holding
            # this row commits. So by the time we read, the first request has
            # either stored a response or failed.
            if idempotency_record.response_body is not None:
                return idempotency_record
            # Response is None — first request failed before storing response.
            # Delete the stale record and let this request re-process.
            idempotency_record.delete()
            return None
    except IdempotencyKey.DoesNotExist:
        return None


def _store_idempotency_response(merchant, key, response_body, status_code):
    """
    Store or update the idempotency record with the response.
    Uses get_or_create to handle the race between checking and storing.
    """
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
            # Record already exists (created by _check_idempotency_key race)
            # Update with the response
            record.response_body = response_body
            record.status_code = status_code
            record.expires_at = expires_at
            record.save(update_fields=["response_body", "status_code", "expires_at"])
    except IntegrityError:
        # Unique constraint violation — another request created it simultaneously
        # This is fine; the other request will store its own response
        pass
