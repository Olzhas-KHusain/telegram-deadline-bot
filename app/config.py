"""Чтение и валидация конфигурации из переменных окружения."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiogram.utils.token import TokenValidationError, validate_token
from dotenv import load_dotenv

DEFAULT_DB_PATH = "data/unimate.sqlite3"
DEFAULT_TIMEZONE = "Asia/Almaty"
DEFAULT_LOG_LEVEL = "INFO"
_LOG_LEVELS = frozenset({"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"})


class ConfigError(RuntimeError):
    """Ошибка конфигурации. Сообщение безопасно показывать пользователю (без секретов)."""


@dataclass(frozen=True, slots=True)
class Settings:
    bot_token: str
    db_path: str = DEFAULT_DB_PATH
    timezone: str = DEFAULT_TIMEZONE
    log_level: str = DEFAULT_LOG_LEVEL

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    def __repr__(self) -> str:  # токен не должен попадать в логи/трейсбеки
        return (
            f"Settings(bot_token='***', db_path={self.db_path!r}, "
            f"timezone={self.timezone!r}, log_level={self.log_level!r})"
        )


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Собрать настройки.

    Если ``env`` не передан, читается локальный ``.env`` (если есть) и ``os.environ``.
    """
    if env is None:
        load_dotenv()
        env = os.environ

    token = env.get("BOT_TOKEN", "").strip()
    if not token:
        raise ConfigError(
            "Не задан BOT_TOKEN. Скопируйте .env.example в .env и укажите токен от @BotFather."
        )
    try:
        validate_token(token)
    except TokenValidationError as exc:
        raise ConfigError(
            "BOT_TOKEN имеет неверный формат. Проверьте токен от @BotFather."
        ) from exc

    db_path = env.get("DB_PATH", "").strip() or DEFAULT_DB_PATH

    timezone = env.get("TIMEZONE", "").strip() or DEFAULT_TIMEZONE
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ConfigError(f"Неизвестная временная зона TIMEZONE={timezone!r}.") from exc

    log_level = (env.get("LOG_LEVEL", "").strip() or DEFAULT_LOG_LEVEL).upper()
    if log_level not in _LOG_LEVELS:
        raise ConfigError(
            f"Недопустимый LOG_LEVEL={log_level!r}. Допустимо: {', '.join(sorted(_LOG_LEVELS))}."
        )

    return Settings(bot_token=token, db_path=db_path, timezone=timezone, log_level=log_level)

