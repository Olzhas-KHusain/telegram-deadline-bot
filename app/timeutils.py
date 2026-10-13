"""Единые правила работы со временем: aware-datetime в приложении, UTC ISO-8601 в БД."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta, tzinfo

DISPLAY_FORMAT = "%d.%m.%Y %H:%M"


def utc_now() -> datetime:
    return datetime.now(UTC)


def ensure_aware(value: datetime) -> datetime:
    """Запретить naive datetime."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Naive datetime не допускается: используйте timezone-aware значение.")
    return value


def to_utc(value: datetime) -> datetime:
    return ensure_aware(value).astimezone(UTC)


def serialize_dt(value: datetime) -> str:
    """Datetime -> строка UTC фиксированной ширины.

    Фиксированная ширина (всегда с микросекундами и +00:00) гарантирует, что сравнение
    строк в SQL совпадает с хронологическим порядком.
    """
    return to_utc(value).isoformat(timespec="microseconds")


def deserialize_dt(raw: str) -> datetime:
    return to_utc(datetime.fromisoformat(raw))


def format_local(value: datetime, tz: tzinfo) -> str:
    return to_utc(value).astimezone(tz).strftime(DISPLAY_FORMAT)


def local_day_bounds_utc(now: datetime, tz: tzinfo) -> tuple[datetime, datetime]:
    """Границы текущего локального дня как UTC-интервал ``[start, next_start)``."""
    local_date = to_utc(now).astimezone(tz).date()
    start = datetime.combine(local_date, time.min, tzinfo=tz)
    next_start = datetime.combine(local_date + timedelta(days=1), time.min, tzinfo=tz)
    return start.astimezone(UTC), next_start.astimezone(UTC)
