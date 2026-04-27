const API = '/api/v1';

export async function fetchMerchants() {
  const res = await fetch(`${API}/merchants/`);
  return res.json();
}

export async function fetchBalance(merchantId) {
  const res = await fetch(`${API}/merchants/${merchantId}/balance/`);
  return res.json();
}

export async function fetchBankAccounts(merchantId) {
  const res = await fetch(`${API}/merchants/${merchantId}/bank-accounts/`);
  return res.json();
}

export async function fetchPayouts(merchantId) {
  const res = await fetch(`${API}/payouts/list/?merchant_id=${merchantId}`);
  return res.json();
}

export async function fetchLedger(merchantId) {
  const res = await fetch(`${API}/merchants/${merchantId}/ledger/`);
  return res.json();
}

export async function createPayout({ merchantId, amountPaise, bankAccountId, idempotencyKey }) {
  const res = await fetch(`${API}/payouts/`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Merchant-Id': merchantId,
      'Idempotency-Key': idempotencyKey,
    },
    body: JSON.stringify({
      amount_paise: amountPaise,
      bank_account_id: bankAccountId,
    }),
  });
  const data = await res.json();
  return { data, ok: res.ok, status: res.status };
}
