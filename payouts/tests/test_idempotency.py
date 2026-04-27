"""
Idempotency: same key returns same response, no duplicate payout.
Different keys create separate payouts.
"""

import uuid

from django.test import TransactionTestCase

from payouts.models import BankAccount, LedgerEntry, Merchant, Payout
from payouts.services import create_payout


class IdempotencyTest(TransactionTestCase):

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
            amount_paise=100000,
            description="Test seed credit",
        )

    def test_duplicate_request_returns_same_response(self):
        key = str(uuid.uuid4())

        response_1, status_1, created_1 = create_payout(
            merchant_id=self.merchant.id,
            amount_paise=25000,
            bank_account_id=self.bank_account.id,
            idempotency_key=key,
        )

        response_2, status_2, created_2 = create_payout(
            merchant_id=self.merchant.id,
            amount_paise=25000,
            bank_account_id=self.bank_account.id,
            idempotency_key=key,
        )

        self.assertEqual(response_1["id"], response_2["id"])
        self.assertEqual(status_1, status_2)
        self.assertTrue(created_1)
        self.assertFalse(created_2)
        self.assertEqual(Payout.objects.filter(merchant=self.merchant).count(), 1)
        self.assertEqual(
            LedgerEntry.objects.filter(
                merchant=self.merchant, entry_type=LedgerEntry.EntryType.DEBIT
            ).count(),
            1,
        )
        self.merchant.refresh_from_db()
        self.assertEqual(self.merchant.available_balance, 75000)

    def test_different_keys_create_separate_payouts(self):
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

        self.assertNotEqual(response_1["id"], response_2["id"])
        self.assertEqual(Payout.objects.filter(merchant=self.merchant).count(), 2)
        self.merchant.refresh_from_db()
        self.assertEqual(self.merchant.available_balance, 80000)
