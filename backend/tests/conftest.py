"""Test fixtures. Requires a PostgreSQL server; set TEST_DATABASE_URL (a dedicated, disposable database).

make test            # runs inside Compose
TEST_DATABASE_URL=postgresql+psycopg://user:pass@127.0.0.1:5432/opennotebook_test uv run pytest
"""

from __future__ import annotations

import base64
import os
import uuid

import pytest

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://opennotebook:test@127.0.0.1:55432/opennotebook_test"
)
os.environ.update(
    {
        "APP_ENV": "test",
        "DATABASE_URL": TEST_DATABASE_URL,
        "APP_SECRET_KEY": "test-secret-key-" + "x" * 48,
        "APP_ENCRYPTION_KEY": base64.b64encode(b"k" * 32).decode(),
        "REDIS_URL": os.environ.get("TEST_REDIS_URL", "redis://127.0.0.1:56379/15"),
        "STORAGE_BACKEND": "filesystem",
        "FILESYSTEM_ROOT": "/tmp/opennotebook-test-blobs",  # noqa: S108
        "LOG_LEVEL": "WARNING",
    }
)

import httpx  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402


def _ensure_database() -> None:
    url = make_url(TEST_DATABASE_URL)
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": url.database}
        ).scalar()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    admin.dispose()


@pytest.fixture(scope="session", autouse=True)
def database() -> None:
    _ensure_database()
    from opennotebook.cli import cmd_migrate

    cmd_migrate(None)  # type: ignore[arg-type]


TABLES = (
    "phase_assignments, provider_models, providers, secrets, node_grants, nodes, refresh_tokens, "
    "group_members, groups, users, audit_log"
)


@pytest.fixture(autouse=True)
async def clean_db(database: None):  # type: ignore[no-untyped-def]
    from redis.asyncio import from_url

    from opennotebook.db import get_engine

    async with get_engine().begin() as conn:
        await conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
    redis = from_url(os.environ["REDIS_URL"])
    await redis.flushdb()  # test-only Redis database: clears login rate-limit counters
    await redis.aclose()
    yield


@pytest.fixture
async def session():  # type: ignore[no-untyped-def]
    from opennotebook.db import get_sessionmaker

    async with get_sessionmaker()() as s:
        yield s


@pytest.fixture
async def client():  # type: ignore[no-untyped-def]
    from opennotebook.main import app

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def make_user(session, email: str, password: str = "correct-horse-battery", admin: bool = False):  # type: ignore[no-untyped-def]
    from opennotebook.models import User
    from opennotebook.security import hash_password

    user = User(
        id=uuid.uuid4(),
        email=email,
        display_name=email.split("@")[0],
        password_hash=hash_password(password),
        is_admin=admin,
    )
    session.add(user)
    await session.commit()
    return user


async def login(
    client: httpx.AsyncClient, email: str, password: str = "correct-horse-battery"
) -> dict[str, str]:
    resp = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture
async def admin_headers(client, session):  # type: ignore[no-untyped-def]
    await make_user(session, "admin@example.com", admin=True)
    return await login(client, "admin@example.com")


@pytest.fixture
async def alice_headers(client, session):  # type: ignore[no-untyped-def]
    await make_user(session, "alice@example.com")
    return await login(client, "alice@example.com")
