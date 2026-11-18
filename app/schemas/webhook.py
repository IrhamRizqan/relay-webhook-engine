from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field, HttpUrl

from app.models.webhook import DeliveryStatus

class EndpointCreateRequest(BaseModel):
    tenant_name: str = Field(..., min_length=2, max_length=100, examples=["Toko Kopi Dago"])
    target_url: HttpUrl = Field(..., examples=["http://localhost:8000/api/v1/receiver/test"])

class EndpointCreateResponse(BaseModel):
    id:int
    tenant_name:str
    target_url:str
    api_key:str
    secret_key:str
    is_active:bool

    model_config = {"from_attributes": True}

class EventPublishRequest(BaseModel):
    event_type:str = Field(..., min_length=3, max_length=100, examples=["payment.settled"])
    payload:dict[str, Any] = Field(
        ...,
        examples=[{"invoice_number": "INV-2026-001", "amount": 45000, "method": "QRIS"}],
    )

class AttemptLogResponse(BaseModel):
    id:int
    attempt_number:int
    http_status:int | None
    response_body:str | None
    error_message:str | None
    duration_ms:int
    attempted_at: datetime

    model_config = {"from_attributes": True}

class EventDetailResponse(BaseModel):
    id:int
    endpoint_id:int
    event_type:str
    payload:dict[str, Any]
    status:DeliveryStatus
    attempt_count:int
    next_retry_at:datetime | None
    created_at:datetime
    attempts:list[AttemptLogResponse] = []

    model_config = {"from_attributes": True}