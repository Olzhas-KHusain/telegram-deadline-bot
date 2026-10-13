"""SQL-доступ к задачам. Все пользовательские запросы ограничены ``telegram_user_id``."""

from __future__ import annotations

from datetime import datetime, timedelta

import aiosqlite

from app.models import Task, TaskStatus
from app.timeutils import deserialize_dt, serialize_dt

_COLUMNS = (
    "id, telegram_user_id, title, deadline_at, status, created_at, completed_at, reminder_sent_at"
)


def _optional_dt(raw: str | None) -> datetime | None:
    return deserialize_dt(raw) if raw is not None else None


def _row_to_task(row: aiosqlite.Row) -> Task:
    return Task(
        id=row["id"],
        telegram_user_id=row["telegram_user_id"],
        title=row["title"],
        deadline_at=deserialize_dt(row["deadline_at"]),
        status=TaskStatus(row["status"]),
        created_at=deserialize_dt(row["created_at"]),
        completed_at=_optional_dt(row["completed_at"]),
        reminder_sent_at=_optional_dt(row["reminder_sent_at"]),
    )


class TaskRepository:
    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def _fetch_all(self, sql: str, params: tuple[object, ...]) -> list[Task]:
        async with self._conn.execute(sql, params) as cursor:
            rows = await cursor.fetchall()
        return [_row_to_task(row) for row in rows]

    async def create(
        self,
        *,
        telegram_user_id: int,
        title: str,
        deadline_at: datetime,
        created_at: datetime,
    ) -> Task:
        async with self._conn.execute(
            "INSERT INTO tasks (telegram_user_id, title, deadline_at, status, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                telegram_user_id,
                title,
                serialize_dt(deadline_at),
                TaskStatus.PENDING.value,
                serialize_dt(created_at),
            ),
        ) as cursor:
            task_id = cursor.lastrowid
        await self._conn.commit()
        if task_id is None:  # pragma: no cover - SQLite всегда возвращает rowid после INSERT
            raise RuntimeError("SQLite не вернул id созданной задачи")
        task = await self.get_for_user(task_id, telegram_user_id)
        if task is None:  # pragma: no cover
            raise RuntimeError("Созданная задача не найдена")
        return task

    async def get_for_user(self, task_id: int, telegram_user_id: int) -> Task | None:
        tasks = await self._fetch_all(
            f"SELECT {_COLUMNS} FROM tasks WHERE id = ? AND telegram_user_id = ?",
            (task_id, telegram_user_id),
        )
        return tasks[0] if tasks else None

    async def count_active(self, telegram_user_id: int) -> int:
        async with self._conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE telegram_user_id = ? AND status = ?",
            (telegram_user_id, TaskStatus.PENDING.value),
        ) as cursor:
            row = await cursor.fetchone()
        return int(row[0]) if row is not None else 0

    async def list_active(
        self, telegram_user_id: int, *, limit: int | None = None, offset: int = 0
    ) -> list[Task]:
        """Активные задачи пользователя по возрастанию дедлайна (``limit=None`` — все)."""
        return await self._fetch_all(
            f"SELECT {_COLUMNS} FROM tasks WHERE telegram_user_id = ? AND status = ? "
            "ORDER BY deadline_at ASC, id ASC LIMIT ? OFFSET ?",
            (
                telegram_user_id,
                TaskStatus.PENDING.value,
                -1 if limit is None else limit,  # в SQLite отрицательный LIMIT = без ограничения
                offset,
            ),
        )

    async def list_active_between(
        self, telegram_user_id: int, start: datetime, end: datetime
    ) -> list[Task]:
        """Активные задачи пользователя с дедлайном в интервале ``[start, end)``."""
        return await self._fetch_all(
            f"SELECT {_COLUMNS} FROM tasks WHERE telegram_user_id = ? AND status = ? "
            "AND deadline_at >= ? AND deadline_at < ? ORDER BY deadline_at ASC, id ASC",
            (telegram_user_id, TaskStatus.PENDING.value, serialize_dt(start), serialize_dt(end)),
        )

    async def mark_completed(
        self, task_id: int, telegram_user_id: int, completed_at: datetime
    ) -> bool:
        """Атомарно завершить активную задачу владельца. ``False`` — ничего не изменено."""
        async with self._conn.execute(
            "UPDATE tasks SET status = ?, completed_at = ? "
            "WHERE id = ? AND telegram_user_id = ? AND status = ?",
            (
                TaskStatus.COMPLETED.value,
                serialize_dt(completed_at),
                task_id,
                telegram_user_id,
                TaskStatus.PENDING.value,
            ),
        ) as cursor:
            changed = cursor.rowcount > 0
        await self._conn.commit()
        return changed

    async def list_due_reminders(self, now: datetime, lead_time: timedelta) -> list[Task]:
        """Задачи, которым пора отправить напоминание.

        pending, напоминание не отправлялось, дедлайн строго в будущем
        и ``deadline_at - lead_time <= now``.
        """
        return await self._fetch_all(
            f"SELECT {_COLUMNS} FROM tasks WHERE status = ? AND reminder_sent_at IS NULL "
            "AND deadline_at > ? AND deadline_at <= ? ORDER BY deadline_at ASC, id ASC",
            (TaskStatus.PENDING.value, serialize_dt(now), serialize_dt(now + lead_time)),
        )

    async def mark_reminder_sent(self, task_id: int, sent_at: datetime) -> bool:
        async with self._conn.execute(
            "UPDATE tasks SET reminder_sent_at = ? WHERE id = ? AND reminder_sent_at IS NULL",
            (serialize_dt(sent_at), task_id),
        ) as cursor:
            changed = cursor.rowcount > 0
        await self._conn.commit()
        return changed
