from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from payouts.models import BankAccount, IdempotencyKey, LedgerEntry, Merchant, Payout


class Command(BaseCommand):
    help = "Seed database with test merchants, bank accounts, and credit history"

    def handle(self, *args, **options):
        self.stdout.write("Seeding database...")

        # Clear existing data (order matters due to foreign keys)
        IdempotencyKey.objects.all().delete()
        LedgerEntry.objects.all().delete()
        Payout.objects.all().delete()
        BankAccount.objects.all().delete()
        Merchant.objects.all().delete()

        now = timezone.now()

        # Merchant 1: Active agency with healthy balance
        m1 = Merchant.objects.create(
            name="Pixel Studio Agency",
            email="billing@pixelstudio.in",
        )
        b1 = BankAccount.objects.create(
            merchant=m1,
            account_number="50100089432156",
            ifsc="HDFC0001234",
            account_holder_name="Pixel Studio Pvt Ltd",
        )
        # Simulate customer payments over past 2 weeks
        credits_m1 = [
            (500_00, "Invoice #1001 - Website redesign", 14),
            (250_00, "Invoice #1002 - Logo design", 10),
            (1000_00, "Invoice #1003 - App development milestone 1", 7),
            (350_00, "Invoice #1004 - SEO audit", 3),
            (750_00, "Invoice #1005 - Brand kit", 1),
        ]
        for amount, desc, days_ago in credits_m1:
            LedgerEntry.objects.create(
                merchant=m1,
                entry_type=LedgerEntry.EntryType.CREDIT,
                amount_paise=amount,
                description=desc,
                created_at=now - timedelta(days=days_ago),
            )
        self.stdout.write(
            f"  Created merchant '{m1.name}' with balance {m1.available_balance} paise"
        )

        # Merchant 2: Freelancer with moderate balance
        m2 = Merchant.objects.create(
            name="Arjun Mehta Consulting",
            email="arjun@mehtaconsulting.com",
        )
        b2 = BankAccount.objects.create(
            merchant=m2,
            account_number="91020034567890",
            ifsc="ICIC0005678",
            account_holder_name="Arjun Mehta",
        )
        credits_m2 = [
            (200_00, "Invoice #2001 - Tax consultation", 12),
            (150_00, "Invoice #2002 - Compliance review", 8),
            (300_00, "Invoice #2003 - Annual audit", 4),
        ]
        for amount, desc, days_ago in credits_m2:
            LedgerEntry.objects.create(
                merchant=m2,
                entry_type=LedgerEntry.EntryType.CREDIT,
                amount_paise=amount,
                description=desc,
                created_at=now - timedelta(days=days_ago),
            )
        self.stdout.write(
            f"  Created merchant '{m2.name}' with balance {m2.available_balance} paise"
        )

        # Merchant 3: Creator with small balance
        m3 = Merchant.objects.create(
            name="Neha Designs",
            email="neha@nehadesigns.co",
        )
        b3 = BankAccount.objects.create(
            merchant=m3,
            account_number="30405060708090",
            ifsc="SBIN0009012",
            account_holder_name="Neha Sharma",
        )
        credits_m3 = [
            (100_00, "Invoice #3001 - Instagram template pack", 5),
            (75_00, "Invoice #3002 - Story highlight covers", 2),
        ]
        for amount, desc, days_ago in credits_m3:
            LedgerEntry.objects.create(
                merchant=m3,
                entry_type=LedgerEntry.EntryType.CREDIT,
                amount_paise=amount,
                description=desc,
                created_at=now - timedelta(days=days_ago),
            )
        self.stdout.write(
            f"  Created merchant '{m3.name}' with balance {m3.available_balance} paise"
        )

        self.stdout.write(self.style.SUCCESS("\nSeeding complete!"))
        self.stdout.write(f"  Merchants: {Merchant.objects.count()}")
        self.stdout.write(f"  Bank accounts: {BankAccount.objects.count()}")
        self.stdout.write(f"  Ledger entries: {LedgerEntry.objects.count()}")
