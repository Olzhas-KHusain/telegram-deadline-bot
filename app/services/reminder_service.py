"""Фоновая отправка напоминаний за час до дедлайна."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from datetime import datetime
from typing import Protocol
from zoneinfo import ZoneInfo

from aiogram.exceptions import TelegramAPIError

from app.models import REMINDER_LEAD_TIME, Task
from app.repositories.task_repository import TaskRepository
from app.timeutils import format_local, utc_now

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = 30.0


class MessageSender(Protocol):
    """Часть интерфейса ``aiogram.Bot``, нужная worker'у (удобно подменять в тестах)."""

    async def send_message(self, chat_id: int, text: str) -> object: ...


def build_reminder_text(task: Task, tz: ZoneInfo) -> str:
    return (
        "⏰ Скоро дедлайн!\n\n"
        f"«{task.title}»\n"
        f"📅 Дедлайн: {format_local(task.deadline_at, tz)} ({tz.key})\n\n"
        "Проверьте задание и успейте сдать вовремя."
    )


class ReminderService:
    def __init__(
        self,
        repository: TaskRepository,
        sender: MessageSender,
        tz: ZoneInfo,
        clock: Callable[[], datetime] = utc_now,
        interval: float = CHECK_INTERVAL_SECONDS,
    ) -> None:
        self._repo = repository
        self._sender = sender
        self._tz = tz
        self._clock = clock
        self._interval = interval
        self._task: asyncio.Task[None] | None = None

    async def run_once(self) -> int:
        """Один проход: отправить все созревшие напоминания. Возвращает число отправленных."""
        due = await self._repo.list_due_reminders(self._clock(), REMINDER_LEAD_TIME)
        sent = 0
        for task in due:
            try:
                await self._sender.send_message(
                    task.telegram_user_id, build_reminder_text(task, self._tz)
                )
            except TelegramAPIError as exc:
                # Не помечаем как отправленное: повторим на следующем цикле до дедлайна.
                logger.warning(
                    "Не удалось отправить напоминание task_id=%s: %s", task.id, type(exc).__name__
                )
                continue
            await self._repo.mark_reminder_sent(task.id, self._clock())
            sent += 1
        return sent

    async def run_forever(self) -> None:
        logger.info("Reminder worker started (interval=%ss)", self._interval)
        try:
            while True:
                try:
                    await self.run_once()
                except Exception:  # граница устойчивости: сбой цикла не должен убить worker
                    logger.exception("Сбой цикла напоминаний; повтор через %ss", self._interval)
                await asyncio.sleep(self._interval)
        finally:
            logger.info("Reminder worker stopped")

    def start(self) -> asyncio.Task[None]:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self.run_forever(), name="reminder-worker")
        return self._task

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
