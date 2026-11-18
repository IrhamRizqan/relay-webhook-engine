# Relay Webhook Engine

Asynchronous, fault-tolerant webhook delivery and retry engine built with **FastAPI**, **PostgreSQL 16**, **SQLAlchemy 2.0**, **Alembic**, and **Redis (ARQ)**.

This service decouples event ingestion from outbound HTTP delivery, ensuring reliable event notifications with cryptographic payload signing, exponential backoff retries, rate limiting, and Dead Letter Queue (DLQ) recovery.

---

## Architecture & Core Mechanisms

### 1. Non-Blocking Event Ingestion (`202 Accepted`)
- Incoming events are authenticated via `X-API-Key`, validated, and persisted in PostgreSQL (`JSONB`) with status `PENDING`.
- A background job ID is immediately enqueued into Redis via **ARQ**, returning an HTTP `202 Accepted` response without blocking the caller on downstream network latency.

### 2. Cryptographic Payload Signing (HMAC-SHA256)
- Every outbound request includes an `X-Webhook-Signature` header formatted as `t={unix_timestamp},v1={hex_digest}`.
- Signatures are computed over `{timestamp}.{canonical_json_payload}` using the tenant's unique `secret_key` (`whsec_...`) to prevent payload tampering and replay attacks.

### 3. Exponential Backoff & Dead Letter Queue (DLQ)
- Outbound HTTP requests enforce a strict `5.0s` timeout via `httpx.AsyncClient` and record every attempt (HTTP status, response snippet, error details, and `duration_ms`) in `delivery_attempts`.
- Failed deliveries (`HTTP 4xx/5xx` or timeouts) automatically transition to `RETRYING` and re-enqueue with exponential delays:
  - Attempt 1 failure -> retry after **5s**
  - Attempt 2 failure -> retry after **10s**
  - Attempt 3 failure -> retry after **20s**
- Events exceeding `MAX_RETRY_ATTEMPTS` (`4`) transition to `FAILED_DLQ` and can be manually re-queued via `POST /api/v1/events/{event_id}/replay`.

### 4. Redis Fixed-Window Rate Limiting
- Enforces per-endpoint ingestion quotas (`20 events/minute`) using atomic Redis `INCR` and `EXPIRE` operations, returning `429 Too Many Requests` when limits are exceeded.

---

## Tech Stack

- **Language & Framework:** Python 3.11, FastAPI, Uvicorn
- **Database & Migrations:** PostgreSQL 16 (`asyncpg`), SQLAlchemy 2.0 Async, Alembic
- **Queue & Rate Limiter:** Redis 7, ARQ (Async Redis Queue)
- **HTTP Client & Testing:** HTTPX, Pytest, Pytest-Asyncio

---

## Project Structure

```text
relay-webhook-engine/
├── alembic/                   # Versioned async database migrations
├── app/
│   ├── api/v1/
│   │   ├── endpoints.py       # Tenant webhook endpoint registration
│   │   ├── events.py          # Rate-limited event ingestion, status inspection, DLQ replay
│   │   └── receiver.py        # Local HMAC verification & failure simulation endpoints
│   ├── core/
│   │   ├── config.py          # Environment & application settings
│   │   ├── database.py        # Async SQLAlchemy engine & session factory
│   │   ├── rate_limiter.py    # Redis atomic counter rate limiter
│   │   └── security.py        # API key generation & HMAC-SHA256 signing
│   ├── models/
│   │   └── webhook.py        # WebhookEndpoint, WebhookEvent, DeliveryAttempt models
│   ├── schemas/
│   │   └── webhook.py         # Pydantic request/response contracts
│   ├── workers/
│   │   └── delivery_worker.py # ARQ background worker & backoff scheduler
│   └── main.py                # FastAPI application & Redis pool lifespan
├── tests/
│   ├── conftest.py            # Async test fixtures & state isolation
│   └── test_webhook_flow.py  # End-to-end integration tests
├── docker-compose.yml
└── requirements.txt
```

---

## API Reference

| Method | Endpoint | Auth | Description |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/endpoints` | None | Register a target URL and generate `api_key` + `secret_key` |
| `POST` | `/api/v1/events` | `X-API-Key` | Publish an event into the async delivery queue (`202 Accepted`) |
| `GET` | `/api/v1/events/{event_id}` | `X-API-Key` | Inspect event status and full `delivery_attempts` audit log |
| `POST` | `/api/v1/events/{event_id}/replay` | `X-API-Key` | Re-queue a failed (`FAILED_DLQ`) event for redelivery |
| `POST` | `/api/v1/receiver/test` | `X-Webhook-Signature` | Built-in receiver simulator verifying HMAC-SHA256 signatures |
| `POST` | `/api/v1/receiver/flaky` | None | Built-in receiver simulator returning `500` to test retries/DLQ |
| `GET` | `/health` | None | Service health check |

---

## Local Setup & Execution

### 1. Start PostgreSQL & Redis
```bash
docker compose up -d
```

### 2. Install Dependencies & Run Migrations
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

alembic upgrade head
```

### 3. Start Worker & API Server
Run each process in a separate terminal with `.venv` activated:

```bash
# Terminal 1: Background Delivery Worker
arq app.workers.delivery_worker.WorkerSettings

# Terminal 2: FastAPI Server
uvicorn app.main:app --reload
```

Interactive OpenAPI documentation is available at `http://127.0.0.1:8000/docs`.

---

## Integration Tests

Stop any running background worker process before executing the test suite to prevent lock contention during table cleanup:

```bash
pytest -v
```

Covers:
- End-to-end async delivery and HMAC-SHA256 signature verification
- Exponential backoff retry progression into `FAILED_DLQ` and manual `/replay` recovery
- Redis fixed-window rate limit enforcement (`429 Too Many Requests`)
- API key authentication rejection (`401 Unauthorized`)