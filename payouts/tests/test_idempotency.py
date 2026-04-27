"""
Idempotency test: Same request twice with same key returns same response.

Expected result:
- Second call returns the exact same payout ID as the first
- Only one Payout row exists in the database
- Only one debit LedgerEntry exists
- Balance is only deducted once
"""

import uuid

from django.test import TransactionTestCase

from payouts.models import BankAccount, LedgerEntry, Merchant, Payout
from payouts.services import create_payout


class IdempotencyTest(TransactionTestCase):
    """
    Test that duplicate requests with the same idempotency key
    do not create duplicate payouts.
    """

    def setUp(self):
        self.merchant = Merchant.objects.create(
            name="Idempotency Test Merchant",
            email="idempotency@example.com",
        )
        self.bank_account = BankAccount.objects.create(
            merchant=self.merchant,
            account_number="98765432101234",
            ifsc="ICIC0005678",
            account_holder_name="Test Account",
        )
        LedgerEntry.objects.create(
            merchant=self.merchant,
            entry_type=LedgerEntry.EntryType.CREDIT,
            amount_paise=100000,  # ₹1,000
            description="Test seed credit",
        )

    def test_duplicate_request_returns_same_response(self):
        """Same idempotency key → same response, no duplicate payout."""
        key = str(uuid.uuid4())

        # First request
        response_1, status_1, created_1 = create_payout(
            merchant_id=self.merchant.id,
            amount_paise=25000,
            bank_account_id=self.bank_account.id,
            idempotency_key=key,
        )

        # Second request with same key
        response_2, status_2, created_2 = create_payout(
            merchant_id=self.merchant.id,
            amount_paise=25000,
            bank_account_id=self.bank_account.id,
            idempotency_key=key,
        )

        # Same payout ID returned
        self.assertEqual(
            response_1["id"], response_2["id"],
            "Second call should return the same payout ID"
        )

        # Same status code
        self.assertEqual(status_1, status_2)

        # First call created, second did not
        self.assertTrue(created_1, "First call should create the payout")
        self.assertFalse(created_2, "Second call should NOT create a new payout")

        # Only one payout in the database
        payout_count = Payout.objects.filter(merchant=self.merchant).count()
        self.assertEqual(
            payout_count, 1,
            f"Expected 1 payout, got {payout_count}. Duplicate was created!"
        )

        # Only one debit entry
        debit_count = LedgerEntry.objects.filter(
            merchant=self.merchant,
            entry_type=LedgerEntry.EntryType.DEBIT,
        ).count()
        self.assertEqual(
            debit_count, 1,
            f"Expected 1 debit, got {debit_count}. Balance was deducted twice!"
        )

        # Balance deducted only once: 100000 - 25000 = 75000
        self.merchant.refresh_from_db()
        self.assertEqual(
            self.merchant.available_balance, 75000,
            "Balance should only be deducted once"
        )

    def test_different_keys_create_separate_payouts(self):
        """Different idempotency keys should create separate payouts."""
        key_1 = str(uuid.uuid4())
        key_2 = str(uuid.uuid4())

        response_1, _, _ = create_payout(
            merchant_id=self.merchant.id,
            amount_paise=10000,
            bank_account_id=self.bank_account.id,
            idempotency_key=key_1,
        )

        response_2, _, _ = create_payout(
            merchant_id=self.merchant.id,
            amount_paise=10000,
            bank_account_id=self.bank_account.id,
            idempotency_key=key_2,
        )

        # Different payout IDs
        self.assertNotEqual(
            response_1["id"], response_2["id"],
            "Different keys should create different payouts"
        )

        # Two payouts
        self.assertEqual(Payout.objects.filter(merchant=self.merchant).count(), 2)

        # Balance: 100000 - 10000 - 10000 = 80000
        self.merchant.refresh_from_db()
        self.assertEqual(self.merchant.available_balance, 80000)
