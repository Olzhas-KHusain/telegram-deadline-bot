"""Общие фикстуры. Тесты не обращаются ни к реальному Telegram API, ни к сети."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from zoneinfo import ZoneInfo

import aiosqlite
import pytest
import pytest_asyncio

from app.db.connection import open_database
from app.repositories.task_repository import TaskRepository
from app.services.task_service import TaskService
from tests.helpers import ALMATY, FakeClock


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def tz() -> ZoneInfo:
    return ALMATY


@pytest_asyncio.fixture
async def db(tmp_path: Path) -> AsyncIterator[aiosqlite.Connection]:
    """Временная файловая SQLite БД."""
    conn = await open_database(str(tmp_path / "test.sqlite3"))
    try:
        yield conn
    finally:
        await conn.close()


@pytest.fixture
def repo(db: aiosqlite.Connection) -> TaskRepository:
    return TaskRepository(db)


@pytest.fixture
def service(repo: TaskRepository, clock: FakeClock) -> TaskService:
    return TaskService(repo, ALMATY, clock)
