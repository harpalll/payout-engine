from django.urls import path

from . import views

urlpatterns = [
    # Merchant endpoints
    path(
        "merchants/",
        views.MerchantListView.as_view(),
        name="merchant-list",
    ),
    path(
        "merchants/<uuid:pk>/",
        views.MerchantDetailView.as_view(),
        name="merchant-detail",
    ),
    path(
        "merchants/<uuid:pk>/balance/",
        views.MerchantBalanceView.as_view(),
        name="merchant-balance",
    ),
    path(
        "merchants/<uuid:pk>/ledger/",
        views.MerchantLedgerView.as_view(),
        name="merchant-ledger",
    ),
    path(
        "merchants/<uuid:pk>/bank-accounts/",
        views.MerchantBankAccountsView.as_view(),
        name="merchant-bank-accounts",
    ),
    # Payout endpoints
    path(
        "payouts/",
        views.PayoutCreateView.as_view(),
        name="payout-create",
    ),
    path(
        "payouts/list/",
        views.PayoutListView.as_view(),
        name="payout-list",
    ),
    path(
        "payouts/<uuid:pk>/",
        views.PayoutDetailView.as_view(),
        name="payout-detail",
    ),
]
