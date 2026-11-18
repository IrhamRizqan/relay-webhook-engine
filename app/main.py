from contextlib import asynccontextmanager

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI

from app.api.v1 import endpoints, events, receiver
from app.core.config import settings

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.arq_pool = await create_pool(
        RedisSettings(host=settings.REDIS_HOST, port=settings.REDIS_PORT)
    )
    yield
    await app.state.arq_pool.close()

app = FastAPI(
    title=settings.PROJECT_NAME,
    version="1.0.0",
    description="Asynchronous webhook delivery engine with HMAC-SHA256 Signing, Rate Limiting, Exponential Backoff Retry and DLQ",
    lifespan=lifespan,
)

app.include_router(endpoints.router, prefix="/api/v1")
app.include_router(events.router, prefix="/api/v1")
app.include_router(receiver.router, prefix="/api/v1")

@app.get("/health", tags=["Health"])
async def health_check():
    return {"status": "healthy"}
