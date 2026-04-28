# EXPLAINER.md

## 1. The Ledger

Balance is never stored. It's always computed from the ledger:

```python
# payouts/models.py — Merchant.available_balance
@property
def available_balance(self):
    result = self.ledger_entries.aggregate(
        balance=Coalesce(Sum("amount_paise"), 0)
    )
    return result["balance"]
```

This translates to `SELECT COALESCE(SUM(amount_paise), 0) FROM ledger_entries WHERE merchant_id = ?`.

Every money movement is an immutable append to the ledger:

- **Credit** (positive): customer payment received
- **Debit** (negative): funds held for a payout
- **Reversal** (positive): funds returned when a payout fails

The balance is always `SUM(all entries)`. There's no mutable balance column that can drift out of sync. If the ledger is correct, the balance is correct. I verify this invariant with `python manage.py check_invariants`, which compares the aggregate SUM against the derived balance for every merchant.

Why not a `balance` column on Merchant? Because then every write needs to update two things (ledger + balance), and if one succeeds without the other, money appears or disappears. A single source of truth is simpler to reason about and harder to break.

## 2. The Lock

```python
# payouts/services.py — inside create_payout()
with transaction.atomic():
    merchant = Merchant.objects.select_for_update().get(id=merchant_id)

    available = LedgerEntry.objects.filter(merchant=merchant).aggregate(
        balance=Coalesce(Sum("amount_paise"), 0)
    )["balance"]

    if available < amount_paise:
        raise InsufficientBalance(...)

    payout = Payout.objects.create(...)
    LedgerEntry.objects.create(amount_paise=-amount_paise, ...)
```

`select_for_update()` issues `SELECT ... FOR UPDATE` which acquires a PostgreSQL row-level exclusive lock on the merchant row. Any other transaction that tries to `SELECT FOR UPDATE` on the same merchant blocks until this transaction commits or rolls back.

This turns a TOCTOU race into a serial queue. Two concurrent 60-rupee requests against a 100-rupee balance:

1. Thread A locks the merchant, reads balance = 100, passes the check, creates the debit
2. Thread B tries to lock the same merchant — **blocks at the database level**
3. Thread A commits. Balance is now 40.
4. Thread B acquires the lock, reads balance = 40, fails the check, raises InsufficientBalance

The locking is not in Python. It's in PostgreSQL. Even if you ran two separate Django processes, the lock still works because it's a database primitive, not an in-memory lock.

The test in `payouts/tests/test_concurrency.py` proves this — two threads submit simultaneous payouts, exactly one succeeds.

## 3. The Idempotency

```python
# payouts/services.py — _check_idempotency_key()
with transaction.atomic():
    record = (
        IdempotencyKey.objects
        .select_for_update()
        .get(
            merchant_id=merchant_id,
            key=key,
            expires_at__gt=timezone.now(),
        )
    )
    if record.response_body is not None:
        return record
    record.delete()
    return None
```

The `IdempotencyKey` model has a `UniqueConstraint` on `(merchant, key)`. Keys are merchant-scoped and expire after 24 hours.

**Normal duplicate:** Client retries with the same key. The record exists with a stored response. We return it. No second payout created.

**In-flight race:** Two requests arrive simultaneously with the same key. First request creates the IdempotencyKey row inside `create_payout`'s transaction. Second request hits `_check_idempotency_key`, which does `select_for_update` on the same row — it **blocks** until the first transaction commits. By the time it reads, the response is stored. Returns the cached response.

The idempotency check runs _before_ acquiring the merchant lock. This way, duplicate requests don't hold the expensive merchant-level lock — they short-circuit early on the cheaper idempotency key lookup.

## 4. The State Machine

```python
# payouts/models.py — Payout
ALLOWED_TRANSITIONS = {
    "pending": {"processing"},
    "processing": {"completed", "failed"},
    "completed": set(),   # terminal
    "failed": set(),      # terminal
}

def transition_to(self, new_status):
    allowed = self.ALLOWED_TRANSITIONS.get(self.status, set())
    if new_status not in allowed:
        raise ValueError(
            f"Illegal state transition: {self.status} -> {new_status}"
        )
    old_status = self.status
    self.status = new_status
    self.save(update_fields=["status", "updated_at"])

    PayoutAuditLog.objects.create(
        payout=self,
        from_status=old_status,
        to_status=new_status,
    )
```

`failed -> completed` is blocked because `ALLOWED_TRANSITIONS["failed"]` is an empty set. `completed -> pending` is blocked the same way. The check is a dict lookup + set membership test. Every transition is recorded in `PayoutAuditLog` for debugging.

When a payout fails, the state transition and the fund reversal happen in the same `transaction.atomic()`:

```python
# payouts/tasks.py — _fail_payout()
with transaction.atomic():
    payout = Payout.objects.select_for_update().get(id=payout_id)
    payout.transition_to(Payout.Status.FAILED)
    LedgerEntry.objects.create(
        amount_paise=payout.amount_paise,  # positive — returns funds
        entry_type=LedgerEntry.EntryType.REVERSAL,
        ...
    )
```

If the reversal entry fails to create, the status change rolls back too. Money can't disappear.

## 5. The AI Audit

### Bug 1: Idempotency key with null response body

AI wrote `_check_idempotency_key` to return the record whenever it existed, without checking if the response was actually stored:

```python
# What AI gave me (broken):
def _check_idempotency_key(merchant_id, key):
    try:
        record = IdempotencyKey.objects.select_for_update().get(
            merchant_id=merchant_id, key=key, expires_at__gt=timezone.now()
        )
        return record  # BUG: response_body might be None
    except IdempotencyKey.DoesNotExist:
        return None
```

If the first request crashes after creating the IdempotencyKey row but before storing the response (e.g., a database timeout during payout creation), the record exists with `response_body=None`. Every subsequent request with that key would return `None` as the response body — a silent 500 in production. The merchant would never be able to use that idempotency key again, and they'd have no idea why.

```python
# What I replaced it with:
if record.response_body is not None:
    return record
record.delete()  # stale record from a failed first attempt
return None       # re-process as if key was never seen
```

### Bug 2: DRF SessionAuthentication enforcing CSRF on a stateless API

AI set up DRF with default authentication classes, which includes `SessionAuthentication`. This silently works in development (Django's browsable API uses sessions) but breaks when any external client calls POST endpoints — the browser sends a preflight CORS request, and Django rejects it with "CSRF token missing."

This API is stateless — merchant identity comes from the `X-Merchant-Id` header, not from sessions. There are no login cookies. CSRF protection is meaningless here and actively harmful.

```python
# What AI gave me (default — includes SessionAuthentication):
REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
}

# What I set it to:
REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": [],
}
```

I caught this when the React dashboard couldn't create payouts in production. The GET endpoints worked fine (no CSRF check on safe methods), but POST failed. The fix was to explicitly tell DRF "this API has no session-based auth" so it stops enforcing CSRF. In a production system, you'd replace this with token-based auth (JWT or API keys).
