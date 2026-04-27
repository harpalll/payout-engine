"""
Concurrency test: Two simultaneous 60-rupee payouts against a 100-rupee balance.

Uses TransactionTestCase (not TestCase) because Django's default TestCase wraps
everything in a single transaction, which defeats the purpose of testing
concurrent transactions. TransactionTestCase commits after each operation,
allowing real concurrency to be tested.

Expected result:
- Exactly one payout succeeds (201)
- Exactly one payout is rejected (InsufficientBalance)
- Final available balance = 4000 paise (10000 - 6000)
- Exactly one Payout row, one debit LedgerEntry
"""

import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

from django.test import TransactionTestCase

from payouts.models import BankAccount, LedgerEntry, Merchant, Payout
from payouts.services import InsufficientBalance, create_payout


class ConcurrentPayoutTest(TransactionTestCase):
    """
    Test that two simultaneous payouts cannot overdraw a merchant's balance.
    This is the exact scenario from the challenge spec:
    'A merchant with 100 rupees balance submits two simultaneous 60 rupee
    payout requests. Exactly one should succeed.'
    """

    def setUp(self):
        """Create a merchant with exactly 10000 paise (₹100) balance."""
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
        # Seed with exactly ₹100 = 10000 paise
        LedgerEntry.objects.create(
            merchant=self.merchant,
            entry_type=LedgerEntry.EntryType.CREDIT,
            amount_paise=10000,
            description="Test seed credit",
        )

    def _attempt_payout(self, amount_paise, key):
        """
        Attempt a payout in a separate thread.
        Returns (success: bool, response_or_error).
        """
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
        """Two 6000 paise payouts against 10000 balance: exactly one succeeds."""
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

        # Exactly one should succeed, one should fail
        self.assertEqual(
            len(successes), 1,
            f"Expected exactly 1 success, got {len(successes)}. Results: {results}"
        )
        self.assertEqual(
            len(failures), 1,
            f"Expected exactly 1 failure, got {len(failures)}. Results: {results}"
        )

        # Verify final balance: 10000 - 6000 = 4000 paise
        self.merchant.refresh_from_db()
        final_balance = self.merchant.available_balance
        self.assertEqual(
            final_balance, 4000,
            f"Expected balance 4000, got {final_balance}. Overdraft occurred!"
        )

        # Verify exactly one payout and one debit entry
        payout_count = Payout.objects.filter(merchant=self.merchant).count()
        self.assertEqual(payout_count, 1, f"Expected 1 payout, got {payout_count}")

        debit_count = LedgerEntry.objects.filter(
            merchant=self.merchant,
            entry_type=LedgerEntry.EntryType.DEBIT,
        ).count()
        self.assertEqual(debit_count, 1, f"Expected 1 debit entry, got {debit_count}")
