"""Точка входа: ``python -m app.main``."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramAPIError, TelegramUnauthorizedError

from app.config import ConfigError, Settings, load_settings
from app.db.connection import open_database
from app.handlers import start, tasks
from app.logging_setup import setup_logging
from app.repositories.task_repository import TaskRepository
from app.services.reminder_service import ReminderService
from app.services.task_service import TaskService

logger = logging.getLogger(__name__)


def build_dispatcher(task_service: TaskService) -> Dispatcher:
    """Dispatcher с роутерами; сервис доступен хендлерам по имени параметра ``task_service``."""
    dispatcher = Dispatcher(task_service=task_service)
    dispatcher.include_router(start.build_router())
    dispatcher.include_router(tasks.build_router())
    return dispatcher


async def run(settings: Settings) -> None:
    conn = await open_database(settings.db_path)
    bot = Bot(token=settings.bot_token)
    repository = TaskRepository(conn)
    task_service = TaskService(repository, settings.tz)
    reminder_service = ReminderService(repository, bot, settings.tz)
    dispatcher = build_dispatcher(task_service)

    reminder_service.start()
    try:
        logger.info("UniMate started (timezone=%s)", settings.timezone)
        await dispatcher.start_polling(bot)
    finally:
        await reminder_service.stop()
        await bot.session.close()
        await conn.close()
        logger.info("UniMate stopped")


def main() -> int:
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"Ошибка конфигурации: {exc}", file=sys.stderr)
        return 1

    setup_logging(settings.log_level, secrets=[settings.bot_token])
    try:
        with contextlib.suppress(KeyboardInterrupt):
            asyncio.run(run(settings))
    except TelegramUnauthorizedError:
        logger.error("Telegram отклонил токен. Проверьте BOT_TOKEN в .env.")
        return 1
    except TelegramAPIError as exc:
        logger.error("Ошибка Telegram API при запуске: %s", type(exc).__name__)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
