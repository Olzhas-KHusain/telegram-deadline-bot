"""Бизнес-логика задач: валидация ввода, создание, списки, завершение."""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from app.models import PAGE_SIZE, TITLE_MAX_LENGTH, Task, TaskPage
from app.repositories.task_repository import TaskRepository
from app.timeutils import (
    DISPLAY_FORMAT,
    ensure_aware,
    format_local,
    local_day_bounds_utc,
    utc_now,
)

DEADLINE_FORMAT_HINT = "ДД.ММ.ГГГГ ЧЧ:ММ"
_DEADLINE_RE = re.compile(r"\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}")


class TaskInputError(ValueError):
    """Некорректный ввод пользователя. Текст сообщения предназначен для показа пользователю."""


def validate_title(raw: str) -> str:
    """Вернуть название без пробелов по краям или поднять ``TaskInputError``."""
    title = raw.strip()
    if not title:
        raise TaskInputError("Название не может быть пустым.")
    if len(title) > TITLE_MAX_LENGTH:
        raise TaskInputError(
            f"Название слишком длинное ({len(title)} симв.). Максимум — {TITLE_MAX_LENGTH}."
        )
    return title


def parse_deadline(raw: str, tz: ZoneInfo, now: datetime) -> datetime:
    """Разобрать ``ДД.ММ.ГГГГ ЧЧ:ММ`` (местное время ``tz``) в aware-datetime UTC.

    Дедлайн должен быть строго позже ``now``.
    """
    text = raw.strip()
    example = _example_deadline(tz, now)
    format_error = TaskInputError(
        f"Не удалось распознать дедлайн. Используйте формат {DEADLINE_FORMAT_HINT}, "
        f"например {example}."
    )
    if not _DEADLINE_RE.fullmatch(text):
        raise format_error
    try:
        local = datetime.strptime(text, DISPLAY_FORMAT).replace(tzinfo=tz)
    except ValueError as exc:  # несуществующая дата, например 31.02.2026 или 24:00
        raise format_error from exc

    deadline = local.astimezone(UTC)
    if deadline <= ensure_aware(now):
        raise TaskInputError(
            "Дедлайн должен быть в будущем. "
            f"Сейчас {format_local(now, tz)} ({tz.key}), укажите более позднее время."
        )
    return deadline


def _example_deadline(tz: ZoneInfo, now: datetime) -> str:
    tomorrow = ensure_aware(now).astimezone(tz) + timedelta(days=1)
    return tomorrow.replace(hour=23, minute=59, second=0, microsecond=0).strftime(DISPLAY_FORMAT)


class TaskService:
    def __init__(
        self,
        repository: TaskRepository,
        tz: ZoneInfo,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._repo = repository
        self._tz = tz
        self._clock = clock

    @property
    def timezone_name(self) -> str:
        return self._tz.key

    def format_deadline(self, value: datetime) -> str:
        return format_local(value, self._tz)

    def example_deadline(self) -> str:
        """Пример корректного дедлайна (завтра 23:59 по местному времени)."""
        return _example_deadline(self._tz, self._clock())

    async def create_task(self, telegram_user_id: int, raw_title: str, raw_deadline: str) -> Task:
        title = validate_title(raw_title)
        now = self._clock()
        deadline = parse_deadline(raw_deadline, self._tz, now)
        return await self._repo.create(
            telegram_user_id=telegram_user_id,
            title=title,
            deadline_at=deadline,
            created_at=now,
        )

    async def get_active_page(
        self, telegram_user_id: int, page: int = 1, page_size: int = PAGE_SIZE
    ) -> TaskPage:
        total = await self._repo.count_active(telegram_user_id)
        page, total_pages = _clamp_page(page, total, page_size)
        tasks = await self._repo.list_active(
            telegram_user_id, limit=page_size, offset=(page - 1) * page_size
        )
        return TaskPage(
            tasks=tasks, page=page, total_pages=total_pages, total=total, page_size=page_size
        )

    async def get_today_page(
        self, telegram_user_id: int, page: int = 1, page_size: int = PAGE_SIZE
    ) -> TaskPage:
        start, end = local_day_bounds_utc(self._clock(), self._tz)
        tasks = await self._repo.list_active_between(telegram_user_id, start, end)
        total = len(tasks)
        page, total_pages = _clamp_page(page, total, page_size)
        offset = (page - 1) * page_size
        return TaskPage(
            tasks=tasks[offset : offset + page_size],
            page=page,
            total_pages=total_pages,
            total=total,
            page_size=page_size,
        )

    async def complete_task(self, telegram_user_id: int, task_id: int) -> Task | None:
        """Завершить активную задачу владельца.

        Возвращает завершённую задачу или ``None``, если задача чужая, не существует
        или уже выполнена (ответ намеренно нейтральный).
        """
        task = await self._repo.get_for_user(task_id, telegram_user_id)
        if task is None:
            return None
        if not await self._repo.mark_completed(task_id, telegram_user_id, self._clock()):
            return None
        return task


def _clamp_page(page: int, total: int, page_size: int) -> tuple[int, int]:
    total_pages = max(1, math.ceil(total / page_size))
    return min(max(page, 1), total_pages), total_pages
