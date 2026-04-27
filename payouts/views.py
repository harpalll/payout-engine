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
    """GET /api/v1/merchants/"""

    queryset = Merchant.objects.all().order_by("name")
    serializer_class = MerchantSerializer


class MerchantDetailView(generics.RetrieveAPIView):
    """GET /api/v1/merchants/<id>/"""

    queryset = Merchant.objects.all()
    serializer_class = MerchantSerializer
    lookup_field = "pk"


class MerchantBalanceView(APIView):
    """
    GET /api/v1/merchants/<id>/balance/

    Returns available and held balance, both computed from ledger.
    """

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
        serializer = BalanceSerializer(data)
        return Response(serializer.data)


class MerchantLedgerView(generics.ListAPIView):
    """
    GET /api/v1/merchants/<id>/ledger/

    Paginated list of ledger entries for a merchant.
    Most recent first.
    """

    serializer_class = LedgerEntrySerializer

    def get_queryset(self):
        return LedgerEntry.objects.filter(
            merchant_id=self.kwargs["pk"]
        ).order_by("-created_at")


class MerchantBankAccountsView(APIView):
    """
    GET /api/v1/merchants/<id>/bank-accounts/

    List active bank accounts for a merchant.
    """

    def get(self, request, pk):
        try:
            merchant = Merchant.objects.get(id=pk)
        except Merchant.DoesNotExist:
            return Response(
                {"error": "Merchant not found."}, status=status.HTTP_404_NOT_FOUND
            )

        from .serializers import BankAccountSerializer

        accounts = merchant.bank_accounts.filter(is_active=True)
        serializer = BankAccountSerializer(accounts, many=True)
        return Response(serializer.data)


class PayoutCreateView(APIView):
    """
    POST /api/v1/payouts/

    Headers:
        Idempotency-Key: <uuid>  (required, merchant-scoped)

    Body:
        { "amount_paise": 50000, "bank_account_id": "<uuid>" }

    Creates a payout in pending state. Holds funds via debit ledger entry.
    Returns the same response if called twice with the same idempotency key.
    """

    def post(self, request):
        # Extract merchant ID from request.
        # In production, this would come from auth. For this challenge,
        # we accept it as a query param or header.
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

        # Extract idempotency key
        idempotency_key = request.headers.get("Idempotency-Key")
        if not idempotency_key:
            return Response(
                {"error": "Idempotency-Key header is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Validate request body
        serializer = PayoutRequestSerializer(
            data=request.data, context={"merchant": merchant}
        )
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        # Delegate to service layer
        try:
            response_data, status_code, created = create_payout(
                merchant_id=merchant.id,
                amount_paise=serializer.validated_data["amount_paise"],
                bank_account_id=serializer.validated_data["bank_account_id"],
                idempotency_key=idempotency_key,
            )
        except InsufficientBalance as e:
            return Response(
                {
                    "error": "insufficient_balance",
                    "detail": str(e),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(response_data, status=status_code)


class PayoutListView(generics.ListAPIView):
    """
    GET /api/v1/payouts/

    Query params:
        merchant_id: required
        status: optional filter (pending, processing, completed, failed)

    Returns paginated list of payouts.
    """

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
    """GET /api/v1/payouts/<id>/"""

    queryset = Payout.objects.all()
    serializer_class = PayoutSerializer
    lookup_field = "pk"
