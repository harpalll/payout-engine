# Payout Engine

Merchant payout processing system with ledger-based balance, concurrency control, idempotency, and background job processing.

## Live Demo

- **Dashboard:** https://payout-engine-dashboard.onrender.com
- **API:** https://payout-engine-api.onrender.com
- **Health Check:** https://payout-engine-api.onrender.com/health/

> First load may take ~30s if the service is waking up from sleep.

## Architecture

<!-- TODO: Add Excalidraw architecture diagram here -->

## Stack

| Layer | Tech |
|-------|------|
| Backend | Django 5.1, Django REST Framework |
| Frontend | React 19, Tailwind CSS v4, Vite |
| Database | PostgreSQL (Neon) |
| Queue | Celery + Redis (Upstash) |
| Deployment | Render (API + Worker + Static Site) |

## Local Setup

### Prerequisites

- Python 3.11+
- Node 18+
- PostgreSQL (or a Neon account)
- Redis (or an Upstash account)

### Backend

```bash
git clone https://github.com/harpalll/payout-engine.git
cd payout-engine

python -m venv venv
# Linux/Mac:
source venv/bin/activate
# Windows:
.\venv\Scripts\activate

pip install -r requirements.txt
cp .env.example .env
# Fill in DATABASE_URL and CELERY_BROKER_URL in .env

python manage.py migrate
python manage.py seed
python manage.py runserver
```

### Celery Worker

In a separate terminal:

```bash
# Linux/Mac:
celery -A config worker -l info --beat

# Windows:
celery -A config worker -l info --beat --pool=solo
```

### Frontend

In a separate terminal:

```bash
cd dashboard
npm install
npm run dev
# Open http://localhost:5173
```

### Docker (alternative)

```bash
docker compose up
```

## Tests

```bash
# Concurrency + idempotency tests (runs against real Postgres)
python manage.py test payouts.tests --keepdb -v 2

# Verify ledger integrity
python manage.py check_invariants
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/payouts/` | Create payout (requires `Idempotency-Key` and `X-Merchant-Id` headers) |
| `GET` | `/api/v1/payouts/list/?merchant_id=<uuid>` | List payouts for a merchant |
| `GET` | `/api/v1/payouts/<id>/` | Get payout details |
| `GET` | `/api/v1/merchants/` | List all merchants |
| `GET` | `/api/v1/merchants/<id>/balance/` | Get available and held balance |
| `GET` | `/api/v1/merchants/<id>/ledger/` | Paginated ledger entries |
| `GET` | `/api/v1/merchants/<id>/bank-accounts/` | List bank accounts |

### Example: Create a Payout

```bash
curl -X POST https://payout-engine-api.onrender.com/api/v1/payouts/ \
  -H "Content-Type: application/json" \
  -H "X-Merchant-Id: <merchant-uuid>" \
  -H "Idempotency-Key: $(uuidgen)" \
  -d '{"amount_paise": 50000, "bank_account_id": "<bank-account-uuid>"}'
```

## Project Structure

```
payout-engine/
├── config/                  # Django settings (base/local/production), Celery config
├── payouts/
│   ├── models.py            # Merchant, BankAccount, LedgerEntry, Payout, IdempotencyKey, PayoutAuditLog
│   ├── services.py          # Payout creation with locking + idempotency
│   ├── tasks.py             # Celery tasks: process_payout, retry_stuck_payouts
│   ├── views.py             # DRF API views
│   ├── serializers.py       # Request/response serialization
│   ├── tests/               # Concurrency and idempotency tests
│   └── management/commands/ # seed, check_invariants
├── dashboard/               # React + Tailwind frontend
├── docker-compose.yml
├── Dockerfile
├── render_start.sh          # Render API entry point
├── worker_start.sh          # Render worker entry point
└── build.sh                 # Render build script
```
