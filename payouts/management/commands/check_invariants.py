from django.core.management.base import BaseCommand
from django.db.models import Sum
from django.db.models.functions import Coalesce

from payouts.models import LedgerEntry, Merchant


class Command(BaseCommand):
    help = "Verify ledger integrity: SUM(ledger entries) must equal derived balance for every merchant"

    def handle(self, *args, **options):
        merchants = Merchant.objects.all()
        errors = []

        for merchant in merchants:
            ledger_sum = LedgerEntry.objects.filter(merchant=merchant).aggregate(
                total=Coalesce(Sum("amount_paise"), 0)
            )["total"]

            derived_balance = merchant.available_balance

            print(f"Merchant: {merchant.name}, Ledger Sum: {ledger_sum}, Dervied Balance: {derived_balance}")

            if ledger_sum != derived_balance:
                errors.append(
                    f"MISMATCH: {merchant.name} (id={merchant.id}) "
                    f"ledger_sum={ledger_sum} != derived_balance={derived_balance}"
                )

            if ledger_sum < 0:
                errors.append(
                    f"NEGATIVE BALANCE: {merchant.name} (id={merchant.id}) "
                    f"balance={ledger_sum} paise"
                )

            self.stdout.write(
                f"  {merchant.name}: balance={ledger_sum} paise ... OK"
            )

        if errors:
            for err in errors:
                self.stderr.write(self.style.ERROR(err))
            raise SystemExit(1)

        self.stdout.write(
            self.style.SUCCESS(
                f"\nAll {merchants.count()} merchants pass integrity check."
            )
        )
