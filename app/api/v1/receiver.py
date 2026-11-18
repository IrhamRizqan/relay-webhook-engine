from sys import prefix
import hashlib
import hmac
import json

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.webhook import WebhookEndpoint

router = APIRouter(prefix="/receiver", tags=["Receiver Simulator"])

@router.post("/test")
async def simulated_healthy_receiver(
    request:Request,
    x_webhook_signature:str = Header(...),
    x_webhook_delivery_id:str = Header(...),
    db:AsyncSession = Depends(get_db),
):
    raw_body = await request.body()
    payload = json.loads(raw_body)

    try:
        parts = dict(item.split("=", 1) for item in x_webhook_signature.split(","))
        timestamp = parts["t"]
        received_sig = parts["v1"]
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Format header X-Webhook-Signature tidak valid!"
        )
    
    stmt = select(WebhookEndpoint).where(
        WebhookEndpoint.target_url.like("%/receiver/test%")
    )
    endpoints = (await db.execute(stmt)).scalars().all()

    canonical_body = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    signed_content = f"{timestamp}.{canonical_body}".encode("utf-8")

    verified = False
    for ep in endpoints:
        expected_sig = hmac.new(
            ep.secret_key.encode("utf-8"),
            signed_content,
            hashlib.sha256,
        ).hexdigest()
        if hmac.compare_digest(expected_sig, received_sig):
            verified = True
            break
    
    if not verified:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Signature HMAC tidak cocok, payload ditolak!"
        )
    
    return {
        "received": True,
        "delivery_id": x_webhook_delivery_id,
        "verified_hmac": True,
    }

@router.post("/flaky", status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
async def simulated_failing_receiver():
    return {"error": "Simulated downstream server outage"}