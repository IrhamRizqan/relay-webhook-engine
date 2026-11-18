import time
from datetime import datetime, timedelta, timezone

import httpx
from arq.connections import RedisSettings
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.security import sign_webhook_payload
from app.models.webhook import DeliveryAttempt, DeliveryStatus, WebhookEvent

def calculate_backoff_seconds(attempt_number:int)->int:
    return 5 * (2**(attempt_number-1))

async def deliver_webhook_task(ctx:dict, event_id:int)->str:
    async with AsyncSessionLocal() as db:
        stmt=(
            select(WebhookEvent)
            .options(selectinload(WebhookEvent.endpoint))
            .where(WebhookEvent.id == event_id)
        )
        event = (await db.execute(stmt)).scalar_one_or_none()

        if not event:
            return f"Event {event_id} tidak ditemukan!"
        
        if event.status == DeliveryStatus.DELIVERED:
            return f"Event {event_id} sudah terkirim sebelumnya!"
        
        endpoint = event.endpoint
        if not endpoint or not endpoint.is_active:
            event.status = DeliveryStatus.FAILED_DLQ
            await db.commit()
            return f"Endpoint untuk {event_id} nonaktif, dipindah ke DLQ (Dead Letter Queue)"
        
        current_attempt = event.attempt_count + 1
        timestamp = int(time.time())
        signature_header = sign_webhook_payload(
            secret_key=endpoint.secret_key,
            timestamp=timestamp,
            payload=event.payload,
        )

        headers={
            "Content-Type":"application/json",
            "User-Agent":"RelayWebhookEngine/1.0",
            "X-Webhook-Event":event.event_type,
            "X-Webhook-Delivery-ID":str(event.id),
            "X-Webhook-Signature":signature_header,
        }

        start_perf = time.perf_counter()
        http_status:int | None = None
        response_text:str | None = None
        error_msg:str | None = None
        is_success = False

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(
                    endpoint.target_url,
                    json = event.payload,
                    headers=headers,
                )
                http_status = response.status_code
                response_text = response.text[:1000]
                is_success = 200 <= response.status_code < 300
        except httpx.TimeoutException:
            error_msg = "Request timeout (> 5s)"
        except httpx.RequestError as exc:
            error_msg = f"Koneksi gagal: {str(exc)[:300]}"
        
        duration_ms = int((time.perf_counter() - start_perf) * 1000)

        attempt_log = DeliveryAttempt(
            event_id=event.id,
            attempt_number=current_attempt,
            http_status=http_status,
            response_body=response_text,
            error_message=error_msg,
            duration_ms=duration_ms,
        )
        db.add(attempt_log)

        event.attempt_count = current_attempt

        if is_success:
            event.status = DeliveryStatus.DELIVERED
            event.next_retry_at = None
            await db.commit()
            return f"Event {event.id} DELIVERED pada percobaan ke-{current_attempt}"
        
        if current_attempt < settings.MAX_RETRY_ATTEMPTS:
            delay_seconds = calculate_backoff_seconds(current_attempt)
            event.status = DeliveryStatus.RETRYING
            event.next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)
            await db.commit()

            redis_pool = ctx["redis"]
            await redis_pool.enqueue_job(
                "deliver_webhook_task",
                event.id,
                _defer_by=delay_seconds,
            )
            return f"Event {event.id} gagal (attempt {current_attempt}), retry dalam {delay_seconds}"
        else:
            event.status = DeliveryStatus.FAILED_DLQ
            event.next_retry_at = None
            await db.commit()
            return f"Event {event.id} mencapai batas maksimal ({current_attempt}x), dipindah ke FAILED_DLQ"

class WorkerSettings:
    functions = [deliver_webhook_task]
    redis_settings = RedisSettings(host=settings.REDIS_HOST, port=settings.REDIS_PORT)
    max_jobs = 10
