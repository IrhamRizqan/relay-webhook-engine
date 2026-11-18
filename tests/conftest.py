from collections.abc import AsyncGenerator
import pytest_asyncio
from arq import create_pool
from arq.connections import RedisSettings
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.core.config import settings
from app.core.database import engine
from app.main import app


@pytest_asyncio.fixture(autouse=True)
async def clean_state():
    # Lepas koneksi pool dari event loop sebelumnya agar tidak bentrok di Windows
    await engine.dispose()

    async with engine.begin() as conn:
        await conn.execute(
            text("TRUNCATE TABLE delivery_attempts, webhook_events, webhook_endpoints RESTART IDENTITY CASCADE;")
        )

    redis_pool = await create_pool(
        RedisSettings(host=settings.REDIS_HOST, port=settings.REDIS_PORT)
    )
    await redis_pool.flushdb()
    await redis_pool.aclose()

    yield

    await engine.dispose()


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    arq_pool = await create_pool(
        RedisSettings(host=settings.REDIS_HOST, port=settings.REDIS_PORT)
    )
    app.state.arq_pool = arq_pool

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac

    await arq_pool.aclose()