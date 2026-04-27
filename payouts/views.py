from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import LedgerEntry, Merchant, Payout
from .serializers import (
    BalanceSerializer,
    LedgerEntrySerializer,
    MerchantSerializer,
    PayoutRequestSerializer,
    PayoutSerializer,
)
from .services import InsufficientBalance, create_payout


class MerchantListView(generics.ListAPIView):
    queryset = Merchant.objects.all().order_by("name")
    serializer_class = MerchantSerializer


class MerchantDetailView(generics.RetrieveAPIView):
    queryset = Merchant.objects.all()
    serializer_class = MerchantSerializer
    lookup_field = "pk"


class MerchantBalanceView(APIView):
    def get(self, request, pk):
        try:
            merchant = Merchant.objects.get(id=pk)
        except Merchant.DoesNotExist:
            return Response(
                {"error": "Merchant not found."}, status=status.HTTP_404_NOT_FOUND
            )

        data = {
            "available_balance": merchant.available_balance,
            "held_balance": merchant.held_balance,
        }
        return Response(BalanceSerializer(data).data)


class MerchantLedgerView(generics.ListAPIView):
    serializer_class = LedgerEntrySerializer

    def get_queryset(self):
        return LedgerEntry.objects.filter(
            merchant_id=self.kwargs["pk"]
        ).order_by("-created_at")


class MerchantBankAccountsView(APIView):
    def get(self, request, pk):
        try:
            merchant = Merchant.objects.get(id=pk)
        except Merchant.DoesNotExist:
            return Response(
                {"error": "Merchant not found."}, status=status.HTTP_404_NOT_FOUND
            )

        from .serializers import BankAccountSerializer

        accounts = merchant.bank_accounts.filter(is_active=True)
        return Response(BankAccountSerializer(accounts, many=True).data)


class PayoutCreateView(APIView):
    """
    POST /api/v1/payouts/
    Headers: Idempotency-Key, X-Merchant-Id
    Body: { amount_paise, bank_account_id }
    """

    def post(self, request):
        merchant_id = request.headers.get("X-Merchant-Id") or request.query_params.get(
            "merchant_id"
        )
        if not merchant_id:
            return Response(
                {"error": "X-Merchant-Id header or merchant_id query param is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            merchant = Merchant.objects.get(id=merchant_id)
        except Merchant.DoesNotExist:
            return Response(
                {"error": "Merchant not found."}, status=status.HTTP_404_NOT_FOUND
            )

        idempotency_key = request.headers.get("Idempotency-Key")
        if not idempotency_key:
            return Response(
                {"error": "Idempotency-Key header is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = PayoutRequestSerializer(
            data=request.data, context={"merchant": merchant}
        )
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            response_data, status_code, created = create_payout(
                merchant_id=merchant.id,
                amount_paise=serializer.validated_data["amount_paise"],
                bank_account_id=serializer.validated_data["bank_account_id"],
                idempotency_key=idempotency_key,
            )
        except InsufficientBalance as e:
            return Response(
                {"error": "insufficient_balance", "detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(response_data, status=status_code)


class PayoutListView(generics.ListAPIView):
    serializer_class = PayoutSerializer

    def get_queryset(self):
        merchant_id = self.request.query_params.get("merchant_id")
        if not merchant_id:
            return Payout.objects.none()

        qs = Payout.objects.filter(merchant_id=merchant_id).order_by("-created_at")

        payout_status = self.request.query_params.get("status")
        if payout_status:
            qs = qs.filter(status=payout_status)

        return qs


class PayoutDetailView(generics.RetrieveAPIView):
    queryset = Payout.objects.all()
    serializer_class = PayoutSerializer
    lookup_field = "pk"
