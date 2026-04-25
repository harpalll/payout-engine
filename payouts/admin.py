from django.contrib import admin

from .models import BankAccount, IdempotencyKey, LedgerEntry, Merchant, Payout


@admin.register(Merchant)
class MerchantAdmin(admin.ModelAdmin):
    list_display = ("name", "email", "available_balance", "created_at")
    search_fields = ("name", "email")
    readonly_fields = ("id", "created_at")


@admin.register(BankAccount)
class BankAccountAdmin(admin.ModelAdmin):
    list_display = ("account_holder_name", "merchant", "account_number", "ifsc", "is_active")
    list_filter = ("is_active",)
    search_fields = ("account_holder_name", "account_number")
    readonly_fields = ("id", "created_at")


@admin.register(LedgerEntry)
class LedgerEntryAdmin(admin.ModelAdmin):
    list_display = ("merchant", "entry_type", "amount_paise", "payout", "created_at")
    list_filter = ("entry_type",)
    search_fields = ("merchant__name",)
    readonly_fields = ("id", "created_at")


@admin.register(Payout)
class PayoutAdmin(admin.ModelAdmin):
    list_display = ("id", "merchant", "amount_paise", "status", "attempts", "created_at")
    list_filter = ("status",)
    search_fields = ("merchant__name",)
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(IdempotencyKey)
class IdempotencyKeyAdmin(admin.ModelAdmin):
    list_display = ("merchant", "key", "status_code", "created_at", "expires_at")
    search_fields = ("merchant__name", "key")
    readonly_fields = ("id", "created_at")
