"""Database engine, session factory and custom column types."""

from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy import cast
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import UserDefinedType

from opennotebook.config import get_settings


class Ltree(UserDefinedType):
    """PostgreSQL `ltree` column, exchanged as a dotted string."""

    cache_ok = True

    def get_col_spec(self, **kw: object) -> str:
        return "LTREE"

    def bind_expression(self, bindvalue):  # type: ignore[no-untyped-def]
        return cast(bindvalue, self)

    def bind_processor(self, dialect):  # type: ignore[no-untyped-def]
        return lambda value: value

    def result_processor(self, dialect, coltype):  # type: ignore[no-untyped-def]
        return lambda value: value


class Base(DeclarativeBase):
    pass


@lru_cache
def get_engine() -> AsyncEngine:
    settings = get_settings()
    return create_async_engine(settings.database_url, pool_pre_ping=True, pool_size=10, max_overflow=10)


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as session:
        yield session
