"""
Concurrency: two simultaneous 60-rupee payouts against a 100-rupee balance.
Exactly one should succeed, the other must be rejected.
"""

import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

from django.test import TransactionTestCase

from payouts.models import BankAccount, LedgerEntry, Merchant, Payout
from payouts.services import InsufficientBalance, create_payout


class ConcurrentPayoutTest(TransactionTestCase):

    def setUp(self):
        self.merchant = Merchant.objects.create(
            name="Test Merchant",
            email="test@example.com",
        )
        self.bank_account = BankAccount.objects.create(
            merchant=self.merchant,
            account_number="12345678901234",
            ifsc="HDFC0001234",
            account_holder_name="Test Account",
        )
        LedgerEntry.objects.create(
            merchant=self.merchant,
            entry_type=LedgerEntry.EntryType.CREDIT,
            amount_paise=10000,
            description="Test seed credit",
        )

    def _attempt_payout(self, amount_paise, key):
        try:
            response, status_code, created = create_payout(
                merchant_id=self.merchant.id,
                amount_paise=amount_paise,
                bank_account_id=self.bank_account.id,
                idempotency_key=key,
            )
            return True, response
        except InsufficientBalance as e:
            return False, str(e)

    def test_concurrent_payouts_no_overdraft(self):
        key_a = str(uuid.uuid4())
        key_b = str(uuid.uuid4())

        results = []
        with ThreadPoolExecutor(max_workers=2) as executor:
            future_a = executor.submit(self._attempt_payout, 6000, key_a)
            future_b = executor.submit(self._attempt_payout, 6000, key_b)

            for future in as_completed([future_a, future_b]):
                results.append(future.result())

        successes = [r for r in results if r[0] is True]
        failures = [r for r in results if r[0] is False]

        self.assertEqual(len(successes), 1, f"Expected 1 success, got {len(successes)}")
        self.assertEqual(len(failures), 1, f"Expected 1 failure, got {len(failures)}")

        self.merchant.refresh_from_db()
        self.assertEqual(self.merchant.available_balance, 4000)

        self.assertEqual(Payout.objects.filter(merchant=self.merchant).count(), 1)
        self.assertEqual(
            LedgerEntry.objects.filter(
                merchant=self.merchant, entry_type=LedgerEntry.EntryType.DEBIT
            ).count(),
            1,
        )
