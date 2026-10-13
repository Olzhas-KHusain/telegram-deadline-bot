"""Подключение к SQLite и идемпотентная инициализация схемы."""

from __future__ import annotations

from pathlib import Path

import aiosqlite

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


async def init_db(conn: aiosqlite.Connection) -> None:
    """Создать таблицу и индексы, если их ещё нет. Существующие данные не затрагиваются."""
    await conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    await conn.commit()


async def open_database(db_path: str) -> aiosqlite.Connection:
    """Открыть соединение (создав каталог при необходимости) и инициализировать схему."""
    if db_path != ":memory:":
        Path(db_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
    conn = await aiosqlite.connect(db_path)
    try:
        conn.row_factory = aiosqlite.Row
        await init_db(conn)
    except BaseException:
        await conn.close()
        raise
    return conn
