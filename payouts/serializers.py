from rest_framework import serializers

from .models import BankAccount, LedgerEntry, Merchant, Payout


class MerchantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Merchant
        fields = ["id", "name", "email", "created_at"]
        read_only_fields = fields


class BankAccountSerializer(serializers.ModelSerializer):
    masked_account = serializers.SerializerMethodField()
    id = serializers.CharField(read_only=True)

    class Meta:
        model = BankAccount
        fields = ["id", "masked_account", "ifsc", "account_holder_name", "is_active"]
        read_only_fields = fields

    def get_masked_account(self, obj):
        """Show only last 4 digits: ****4321"""
        return f"****{obj.account_number[-4:]}"


class LedgerEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = LedgerEntry
        fields = [
            "id",
            "entry_type",
            "amount_paise",
            "payout",
            "description",
            "created_at",
        ]
        read_only_fields = fields


class PayoutSerializer(serializers.ModelSerializer):
    bank_account = BankAccountSerializer(read_only=True)
    # Render UUIDs as strings so response can be stored in JSONField
    id = serializers.CharField(read_only=True)
    merchant = serializers.CharField(source="merchant_id", read_only=True)

    class Meta:
        model = Payout
        fields = [
            "id",
            "merchant",
            "bank_account",
            "amount_paise",
            "status",
            "idempotency_key",
            "attempts",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class PayoutRequestSerializer(serializers.Serializer):
    """
    Input validation for POST /api/v1/payouts/
    Like a Zod schema — validates the request body before business logic runs.
    """

    amount_paise = serializers.IntegerField(min_value=1)
    bank_account_id = serializers.UUIDField()

    def validate_amount_paise(self, value):
        if value <= 0:
            raise serializers.ValidationError("Amount must be positive.")
        return value

    def validate_bank_account_id(self, value):
        merchant = self.context.get("merchant")
        if not merchant:
            raise serializers.ValidationError("Merchant context is required.")
        try:
            bank_account = BankAccount.objects.get(
                id=value, merchant=merchant, is_active=True
            )
        except BankAccount.DoesNotExist:
            raise serializers.ValidationError(
                "Bank account not found or does not belong to this merchant."
            )
        # Store for use in the view
        self._bank_account = bank_account
        return value


class BalanceSerializer(serializers.Serializer):
    available_balance = serializers.IntegerField()
    held_balance = serializers.IntegerField()
