"""Доменные структуры данных."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

TITLE_MAX_LENGTH = 200
PAGE_SIZE = 10
REMINDER_LEAD_TIME = timedelta(hours=1)


class TaskStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"


@dataclass(frozen=True, slots=True)
class Task:
    id: int
    telegram_user_id: int
    title: str
    deadline_at: datetime  # aware, UTC
    status: TaskStatus
    created_at: datetime  # aware, UTC
    completed_at: datetime | None = None
    reminder_sent_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class TaskPage:
    """Одна страница списка задач (нумерация страниц с 1)."""

    tasks: Sequence[Task]
    page: int
    total_pages: int
    total: int
    page_size: int = PAGE_SIZE

    @property
    def has_prev(self) -> bool:
        return self.page > 1

    @property
    def has_next(self) -> bool:
        return self.page < self.total_pages

    @property
    def first_number(self) -> int:
        """Сквозной номер первой задачи страницы (с 1)."""
        return (self.page - 1) * self.page_size + 1
