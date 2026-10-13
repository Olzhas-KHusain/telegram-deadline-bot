"""Общие константы и вспомогательные классы для тестов."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

ALMATY = ZoneInfo("Asia/Almaty")

# 20.10.2026 12:00 по Алматы (UTC+5) = 07:00 UTC
NOW = datetime(2026, 10, 20, 7, 0, tzinfo=UTC)


class FakeClock:
    """Управляемые часы."""

    def __init__(self, now: datetime = NOW) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now
