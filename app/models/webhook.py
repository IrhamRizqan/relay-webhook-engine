from time import timezone
from sqlalchemy import False_
import enum
from datetime import datetime
from sqlalchemy import (Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, func)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

class DeliveryStatus(str, enum.Enum):
    PENDING = "PENDING"
    RETRYING = "RETRYING"
    DELIVERED = "DELIVERED"
    FAILED_DLQ = "FAILED_DLQ"

class WebhookEndpoint(Base):
    __tablename__ = "webhook_endpoints"

    id:Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tenant_name:Mapped[str] = mapped_column(String(100), nullable=False)
    target_url:Mapped[str] = mapped_column(String(500), nullable=False)
    secret_key:Mapped[str] = mapped_column(String(128), nullable=False)
    api_key:Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    is_active:Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at:Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    events:Mapped[list["WebhookEvent"]] = relationship(back_populates="endpoint")

class WebhookEvent(Base):
    __tablename__ = "webhook_events"

    id:Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    endpoint_id:Mapped[int] = mapped_column(
        ForeignKey("webhook_endpoints.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type:Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    payload:Mapped[dict] = mapped_column(JSONB, nullable=False)
    status:Mapped[DeliveryStatus] = mapped_column(
        Enum(DeliveryStatus), default=DeliveryStatus.PENDING, nullable=False, index=True
    )
    attempt_count:Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_retry_at:Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at:Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    endpoint:Mapped["WebhookEndpoint"] = relationship(back_populates="events")
    attempts:Mapped[list["DeliveryAttempt"]] = relationship(
        back_populates="event", cascade="all, delete-orphan"
    )

class DeliveryAttempt(Base):
    __tablename__ = "delivery_attempts"

    id:Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    event_id:Mapped[int] = mapped_column(
        ForeignKey("webhook_events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    attempt_number:Mapped[int] = mapped_column(Integer, nullable=False)
    http_status:Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_body:Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message:Mapped[str | None] = mapped_column(String(500), nullable=True)
    duration_ms:Mapped[int] = mapped_column(Integer, nullable=False)
    attempted_at:Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    event:Mapped["WebhookEvent"] = relationship(back_populates="attempts")

