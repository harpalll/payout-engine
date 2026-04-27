"""Background tasks for payout processing and retry."""

import logging
import random
from datetime import timedelta

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from .models import LedgerEntry, Payout

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=0)
def process_payout(self, payout_id):
    """
    Process a single payout: pending -> processing -> completed|failed.
    Simulates bank settlement with 70/20/10 success/fail/hang split.
    """
    try:
        with transaction.atomic():
            payout = Payout.objects.select_for_update().get(id=payout_id)

            if payout.status not in (Payout.Status.PENDING, Payout.Status.PROCESSING):
                logger.info(f"Payout {payout_id}: already {payout.status}, skipping.")
                return

            if payout.status == Payout.Status.PENDING:
                payout.transition_to(Payout.Status.PROCESSING)

            payout.attempts += 1
            payout.last_attempted_at = timezone.now()
            payout.save(update_fields=["attempts", "last_attempted_at", "updated_at"])

        # Simulate bank call outside the lock
        outcome = _simulate_bank_settlement()
        logger.info(f"Payout {payout_id}: bank simulation result = {outcome}")

        if outcome == "success":
            _complete_payout(payout_id)
        elif outcome == "failure":
            _fail_payout(payout_id)
        else:
            logger.info(f"Payout {payout_id}: simulated hang, will be retried.")

    except Payout.DoesNotExist:
        logger.error(f"Payout {payout_id} not found.")
    except ValueError as e:
        logger.error(f"Payout {payout_id}: illegal state transition — {e}")


@shared_task
def retry_stuck_payouts():
    """
    Periodic task (every 30s via Beat). Retries payouts stuck in processing
    for >30s, or fails them after 3 attempts.
    """
    cutoff = timezone.now() - timedelta(seconds=30)
    stuck = Payout.objects.filter(
        status=Payout.Status.PROCESSING,
        updated_at__lt=cutoff,
    )

    for payout in stuck:
        if payout.attempts >= 3:
            logger.warning(f"Payout {payout.id}: max attempts reached, failing.")
            _fail_payout(payout.id)
        else:
            backoff = 30 * (2 ** payout.attempts)
            logger.info(
                f"Payout {payout.id}: retry {payout.attempts + 1}/3, "
                f"backoff {backoff}s."
            )
            process_payout.apply_async(
                args=[str(payout.id)],
                countdown=backoff,
            )


def _simulate_bank_settlement():
    """70% success, 20% failure, 10% hang."""
    roll = random.random()
    if roll < 0.70:
        return "success"
    elif roll < 0.90:
        return "failure"
    return "hang"


def _complete_payout(payout_id):
    with transaction.atomic():
        payout = Payout.objects.select_for_update().get(id=payout_id)
        payout.transition_to(Payout.Status.COMPLETED)
        logger.info(f"Payout {payout_id}: completed successfully.")


def _fail_payout(payout_id):
    """Fail payout and return funds — both in one transaction."""
    with transaction.atomic():
        payout = Payout.objects.select_for_update().get(id=payout_id)

        if payout.status != Payout.Status.PROCESSING:
            logger.warning(f"Payout {payout_id}: can't fail, status is {payout.status}.")
            return

        payout.transition_to(Payout.Status.FAILED)

        LedgerEntry.objects.create(
            merchant=payout.merchant,
            entry_type=LedgerEntry.EntryType.REVERSAL,
            amount_paise=payout.amount_paise,
            payout=payout,
            description=f"Payout failed - funds returned - {payout.id}",
        )

        logger.info(
            f"Payout {payout_id}: failed, {payout.amount_paise} paise "
            f"returned to {payout.merchant.name}."
        )
