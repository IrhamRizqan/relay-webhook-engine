from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import pytest
from arq import create_pool
from arq.connections import RedisSettings

from app.core.config import settings
from app.core.security import sign_webhook_payload
from app.workers.delivery_worker import deliver_webhook_task


@pytest.mark.asyncio
async def test_successful_webhook_delivery_and_hmac(client):
    # 1. Daftarkan endpoint baru
    reg_res = await client.post(
        "/api/v1/endpoints",
        json={
            "tenant_name": "Kopi Dago",
            "target_url": "https://client.example.com/webhook",
        },
    )
    assert reg_res.status_code == 201
    ep_data = reg_res.json()
    api_key = ep_data["api_key"]
    secret_key = ep_data["secret_key"]

    # 2. Kirim event ke API
    payload_data = {"invoice": "INV-1001", "amount": 50000}
    pub_res = await client.post(
        "/api/v1/events",
        headers={"X-API-Key": api_key},
        json={"event_type": "payment.settled", "payload": payload_data},
    )
    assert pub_res.status_code == 202
    event_id = pub_res.json()["event_id"]

    # 3. Mock HTTP POST ke server luar agar mengembalikan 200 OK & tangkap header-nya
    captured_headers = {}

    async def fake_post(url, json, headers):
        captured_headers.update(headers)
        return httpx.Response(200, text='{"ok": true}')

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value.post = fake_post

    redis_pool = await create_pool(
        RedisSettings(host=settings.REDIS_HOST, port=settings.REDIS_PORT)
    )
    try:
        with patch("app.workers.delivery_worker.httpx.AsyncClient", return_value=mock_client):
            result_msg = await deliver_webhook_task({"redis": redis_pool}, event_id)
            assert "DELIVERED" in result_msg
    finally:
        await redis_pool.aclose()

    # 4. Verifikasi signature HMAC yang dikirim worker cocok dengan secret_key
    sig_header = captured_headers["X-Webhook-Signature"]
    timestamp = int(sig_header.split(",")[0].split("=")[1])
    expected_sig = sign_webhook_payload(secret_key, timestamp, payload_data)
    assert sig_header == expected_sig

    # 5. Cek detail status & log attempt lewat endpoint GET
    detail_res = await client.get(
        f"/api/v1/events/{event_id}",
        headers={"X-API-Key": api_key},
    )
    assert detail_res.status_code == 200
    detail = detail_res.json()
    assert detail["status"] == "DELIVERED"
    assert detail["attempt_count"] == 1
    assert len(detail["attempts"]) == 1


@pytest.mark.asyncio
async def test_retry_backoff_to_dlq_and_manual_replay(client):
    reg_res = await client.post(
        "/api/v1/endpoints",
        json={
            "tenant_name": "Downstream Flaky Store",
            "target_url": "https://flaky.example.com/webhook",
        },
    )
    api_key = reg_res.json()["api_key"]

    pub_res = await client.post(
        "/api/v1/events",
        headers={"X-API-Key": api_key},
        json={"event_type": "order.created", "payload": {"order_id": 99}},
    )
    event_id = pub_res.json()["event_id"]

    # Simulasikan server tujuan selalu membalas 500 Internal Server Error
    async def failing_post(url, json, headers):
        return httpx.Response(500, text="Internal Server Error")

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value.post = failing_post
    mock_redis = MagicMock()
    mock_redis.enqueue_job = AsyncMock()

    with patch("app.workers.delivery_worker.httpx.AsyncClient", return_value=mock_client):
        # Jalankan worker sebanyak MAX_RETRY_ATTEMPTS (4 kali)
        for _ in range(settings.MAX_RETRY_ATTEMPTS):
            await deliver_webhook_task({"redis": mock_redis}, event_id)

    # Pastikan status sekarang menjadi FAILED_DLQ setelah 4x gagal
    detail_res = await client.get(
        f"/api/v1/events/{event_id}",
        headers={"X-API-Key": api_key},
    )
    detail = detail_res.json()
    assert detail["status"] == "FAILED_DLQ"
    assert detail["attempt_count"] == 4
    assert len(detail["attempts"]) == 4

    # Uji endpoint replay DLQ
    replay_res = await client.post(
        f"/api/v1/events/{event_id}/replay",
        headers={"X-API-Key": api_key},
    )
    assert replay_res.status_code == 202
    assert replay_res.json()["status"] == "REQUEUED"


@pytest.mark.asyncio
async def test_rate_limiting_enforced(client):
    reg_res = await client.post(
        "/api/v1/endpoints",
        json={
            "tenant_name": "High Traffic Tenant",
            "target_url": "https://fast.example.com/webhook",
        },
    )
    api_key = reg_res.json()["api_key"]

    # 20 request pertama harus diterima (202)
    for i in range(20):
        res = await client.post(
            "/api/v1/events",
            headers={"X-API-Key": api_key},
            json={"event_type": "ping", "payload": {"seq": i}},
        )
        assert res.status_code == 202

    # Request ke-21 dalam menit yang sama harus ditolak dengan 429 Too Many Requests
    blocked_res = await client.post(
        "/api/v1/events",
        headers={"X-API-Key": api_key},
        json={"event_type": "ping", "payload": {"seq": 21}},
    )
    assert blocked_res.status_code == 429


@pytest.mark.asyncio
async def test_invalid_api_key_rejected(client):
    res = await client.post(
        "/api/v1/events",
        headers={"X-API-Key": "rk_live_invalid_key"},
        json={"event_type": "payment.settled", "payload": {"amount": 1000}},
    )
    assert res.status_code == 401