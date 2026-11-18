from app.models import webhook
from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.rate_limiter import enforce_rate_limit
from app.models.webhook import DeliveryStatus, WebhookEndpoint, WebhookEvent
from app.schemas.webhook import EventDetailResponse, EventPublishRequest

router = APIRouter(prefix="/events", tags=["Webhook Events"])

def get_arq_pool(request: Request)->ArqRedis:
    return request.app.state.arq_pool

async def get_authenthicated_endpoint(
    x_api_key:str = Header(..., description="API Key milik tenant"),
    db:AsyncSession = Depends(get_db),
)-> WebhookEndpoint:
        stmt= select(WebhookEndpoint).where(WebhookEndpoint.api_key == x_api_key)
        endpoint = (await db.execute(stmt)).scalar_one_or_none()

        if not endpoint:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="X-API-Key tidak valid!",
            )
        if not endpoint.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Endpoint webhook dalam status nonaktif!"
            )
        return endpoint

@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def publish_webhook_event(
    payload:EventPublishRequest,
    endpoint:WebhookEndpoint = Depends(get_authenthicated_endpoint),
    db:AsyncSession = Depends(get_db),
    arq_pool:ArqRedis = Depends(get_arq_pool),
):
    await enforce_rate_limit(redis=arq_pool, endpoint_id=endpoint.id, limit_per_minute=20)

    event = WebhookEvent(
        endpoint_id=endpoint.id,
        event_type=payload.event_type,
        payload=payload.payload,
        status=DeliveryStatus.PENDING,
        attempt_count=0,
    )
    db.add(event)
    await db.commit()
    await db.refresh(event)

    await arq_pool.enqueue_job("deliver_webhook_task", event.id)

    return{
        "status": "ACCEPTED",
        "event_id": event.id,
        "delivery_status": event.status,
        "message": "Event masuk antrean pengiriman latar belakang",
    }

@router.get("/{event_id}", response_model=EventDetailResponse)
async def get_event_delivery_status(
    event_id:int,
    endpoint:WebhookEndpoint = Depends(get_authenthicated_endpoint),
    db:AsyncSession = Depends(get_db),
):
    stmt = (
        select(WebhookEvent)
        .options(selectinload(WebhookEvent.attempts))
        .where(WebhookEvent.id == event_id, WebhookEvent.endpoint_id == endpoint.id)
    )
    event = (await db.execute(stmt)).scalar_one_or_none()

    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event tidak ditemukan!",
        )
    return event

@router.post("/{event_id}/replay", status_code=status.HTTP_202_ACCEPTED)
async def replay_dlq_event(
    event_id:int,
    endpoint:WebhookEndpoint = Depends(get_authenthicated_endpoint),
    db:AsyncSession = Depends(get_db),
    arq_pool:ArqRedis = Depends(get_arq_pool),
):
    stmt = select(WebhookEvent).where(
        WebhookEvent.id == event_id,
        WebhookEvent.endpoint_id == endpoint.id,
    )
    event = (await db.execute(stmt)).scalar_one_or_none()

    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event tidak ditemukan!"
        )
    if event.status == DeliveryStatus.DELIVERED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Event sudah berstatus DELIVERED, tidak perlu di replay!"
        )
    
    event.status = DeliveryStatus.PENDING
    event.attempt_count = 0
    event.next_retry_at = None
    await db.commit()

    await arq_pool.enqueue_job("deliver_webhook_task", event.id)
    return {
        "status": "REQUEUED",
        "event_id": event.id,
        "message": "Event dari DLQ dijadwalkan ulang untuk dikirim"
    }