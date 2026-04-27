"""
Background tasks for payout processing.

Two tasks:
1. process_payout — picks up a pending payout, simulates bank settlement
2. retry_stuck_payouts — periodic task that retries stuck payouts or fails them
"""

import logging
import random
from datetime import timedelta

from celery import shared_task
from django.db import transaction
from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from .models import LedgerEntry, Payout

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=0)
def process_payout(self, payout_id):
    """
    Process a single payout through the bank settlement simulation.

    Flow:
    1. Lock the payout row (SELECT FOR UPDATE)
    2. Transition pending → processing
    3. Simulate bank API call:
       - 70% → completed (payout is final)
       - 20% → failed (funds returned atomically)
       - 10% → stays in processing (simulates a hang, retry will pick it up)
    """
    try:
        with transaction.atomic():
            payout = Payout.objects.select_for_update().get(id=payout_id)

            # Only process payouts in pending or processing state
            if payout.status not in (Payout.Status.PENDING, Payout.Status.PROCESSING):
                logger.info(
                    f"Payout {payout_id} is in {payout.status} state, skipping."
                )
                return

            # Transition to processing if still pending
            if payout.status == Payout.Status.PENDING:
                payout.transition_to(Payout.Status.PROCESSING)

            # Update attempt tracking
            payout.attempts += 1
            payout.last_attempted_at = timezone.now()
            payout.save(update_fields=["attempts", "last_attempted_at", "updated_at"])

        # --- Simulate bank settlement (outside the lock) ---
        outcome = _simulate_bank_settlement()
        logger.info(f"Payout {payout_id}: bank simulation result = {outcome}")

        if outcome == "success":
            _complete_payout(payout_id)
        elif outcome == "failure":
            _fail_payout(payout_id)
        else:
            # outcome == "hang" — do nothing, retry_stuck_payouts will catch it
            logger.info(f"Payout {payout_id}: simulated hang, will be retried.")

    except Payout.DoesNotExist:
        logger.error(f"Payout {payout_id} not found.")
    except ValueError as e:
        logger.error(f"Payout {payout_id}: illegal state transition — {e}")


@shared_task
def retry_stuck_payouts():
    """
    Periodic task (runs every 30s via Celery Beat).

    Finds payouts stuck in 'processing' for >30 seconds and either:
    - Re-queues them if attempts < 3 (with exponential backoff)
    - Fails them atomically if attempts >= 3 (returns funds)
    """
    cutoff = timezone.now() - timedelta(seconds=30)
    stuck_payouts = Payout.objects.filter(
        status=Payout.Status.PROCESSING,
        updated_at__lt=cutoff,
    )

    for payout in stuck_payouts:
        if payout.attempts >= 3:
            # Max retries exhausted — fail and return funds
            logger.warning(
                f"Payout {payout.id}: max attempts ({payout.attempts}) reached, "
                f"failing and returning funds."
            )
            _fail_payout(payout.id)
        else:
            # Retry with exponential backoff: 30s, 60s, 120s
            backoff_seconds = 30 * (2 ** payout.attempts)
            logger.info(
                f"Payout {payout.id}: retrying (attempt {payout.attempts + 1}/3), "
                f"backoff {backoff_seconds}s."
            )
            process_payout.apply_async(
                args=[str(payout.id)],
                countdown=backoff_seconds,
            )


def _simulate_bank_settlement():
    """
    Simulate bank API response.
    70% success, 20% failure, 10% hang (no response).
    """
    roll = random.random()
    if roll < 0.70:
        return "success"
    elif roll < 0.90:
        return "failure"
    else:
        return "hang"


def _complete_payout(payout_id):
    """
    Mark payout as completed. No fund movement needed —
    the debit entry already holds the funds.
    """
    with transaction.atomic():
        payout = Payout.objects.select_for_update().get(id=payout_id)
        payout.transition_to(Payout.Status.COMPLETED)
        logger.info(f"Payout {payout_id}: completed successfully.")


def _fail_payout(payout_id):
    """
    Mark payout as failed AND return funds to merchant — atomically.

    Both the state transition and the reversal ledger entry happen in
    the same transaction. If either fails, neither is committed.
    This prevents money from disappearing (state=failed but no reversal).
    """
    with transaction.atomic():
        payout = Payout.objects.select_for_update().get(id=payout_id)

        # Guard: only fail payouts that are in processing state
        if payout.status != Payout.Status.PROCESSING:
            logger.warning(
                f"Payout {payout_id}: cannot fail, status is {payout.status}."
            )
            return

        # Atomic: transition + reversal in one transaction
        payout.transition_to(Payout.Status.FAILED)

        LedgerEntry.objects.create(
            merchant=payout.merchant,
            entry_type=LedgerEntry.EntryType.REVERSAL,
            amount_paise=payout.amount_paise,  # positive — returns funds
            payout=payout,
            description=f"Payout failed - funds returned - {payout.id}",
        )

        logger.info(
            f"Payout {payout_id}: failed, {payout.amount_paise} paise "
            f"returned to {payout.merchant.name}."
        )
