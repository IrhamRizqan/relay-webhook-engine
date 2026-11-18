from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import generate_api_key, generate_signing_secret
from app.models.webhook import WebhookEndpoint
from app.schemas.webhook import EndpointCreateRequest, EndpointCreateResponse

router = APIRouter(prefix="/endpoints", tags=["Webhook Endpoints"])

@router.post("", response_model=EndpointCreateResponse, status_code=status.HTTP_201_CREATED)
async def register_webhook_endpoint(
    payload: EndpointCreateRequest,
    db:AsyncSession = Depends(get_db),
):
    endpoint = WebhookEndpoint(
        tenant_name=payload.tenant_name,
        target_url=str(payload.target_url),
        api_key=generate_api_key(),
        secret_key=generate_signing_secret(),
        is_active=True,
    )
    db.add(endpoint)
    await db.commit()
    await db.refresh(endpoint)
    return endpoint