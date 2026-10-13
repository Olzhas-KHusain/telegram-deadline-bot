from datetime import UTC, datetime, timedelta

import pytest

from app.services.task_service import TaskInputError, parse_deadline, validate_title
from app.timeutils import (
    deserialize_dt,
    ensure_aware,
    local_day_bounds_utc,
    serialize_dt,
)
from tests.helpers import ALMATY, NOW


class TestTitle:
    def test_trims_whitespace(self) -> None:
        assert validate_title("  Лабораторная 3  ") == "Лабораторная 3"

    @pytest.mark.parametrize("raw", ["", "   ", "\n\t "])
    def test_empty_rejected(self, raw: str) -> None:
        with pytest.raises(TaskInputError):
            validate_title(raw)

    def test_length_boundaries(self) -> None:
        assert validate_title("а" * 200) == "а" * 200
        assert validate_title(" " + "а" * 200 + " ") == "а" * 200  # длина считается после trim
        with pytest.raises(TaskInputError):
            validate_title("а" * 201)


class TestDeadline:
    def test_valid_is_interpreted_in_almaty_and_returned_in_utc(self) -> None:
        deadline = parse_deadline("20.10.2026 23:59", ALMATY, NOW)
        assert deadline == datetime(2026, 10, 20, 18, 59, tzinfo=UTC)  # UTC+5
        assert deadline.utcoffset() == timedelta(0)

    def test_surrounding_whitespace_is_allowed(self) -> None:
        assert parse_deadline("  21.10.2026 09:00 ", ALMATY, NOW) == datetime(
            2026, 10, 21, 4, 0, tzinfo=UTC
        )

    @pytest.mark.parametrize(
        "raw",
        [
            "",
            "завтра",
            "20.10.2026",
            "2026-10-21 10:00",
            "21.10.26 10:00",
            "1.11.2026 9:00",  # строгий формат: ровно ДД.ММ.ГГГГ ЧЧ:ММ
            "21.10.2026  10:00",
            "31.02.2027 10:00",  # несуществующая дата
            "21.10.2026 24:00",
            "21.10.2026 10:60",
        ],
    )
    def test_invalid_format_rejected_with_hint(self, raw: str) -> None:
        with pytest.raises(TaskInputError, match=r"ДД\.ММ\.ГГГГ ЧЧ:ММ"):
            parse_deadline(raw, ALMATY, NOW)

    def test_past_deadline_rejected(self) -> None:
        with pytest.raises(TaskInputError, match="в будущем"):
            parse_deadline("19.10.2026 10:00", ALMATY, NOW)

    def test_deadline_equal_to_now_rejected_but_one_minute_later_accepted(self) -> None:
        with pytest.raises(TaskInputError, match="в будущем"):
            parse_deadline("20.10.2026 12:00", ALMATY, NOW)  # ровно сейчас
        assert parse_deadline("20.10.2026 12:01", ALMATY, NOW) > NOW


class TestTimeUtils:
    def test_naive_datetime_rejected(self) -> None:
        with pytest.raises(ValueError):
            ensure_aware(datetime(2026, 1, 1, 12, 0))
        with pytest.raises(ValueError):
            serialize_dt(datetime(2026, 1, 1, 12, 0))

    def test_serialization_roundtrip_is_utc_and_fixed_width(self) -> None:
        local = datetime(2026, 10, 20, 23, 59, tzinfo=ALMATY)
        raw = serialize_dt(local)
        assert raw == "2026-10-20T18:59:00.000000+00:00"
        assert deserialize_dt(raw) == local
        assert len(serialize_dt(NOW)) == len(raw)  # лексикографический порядок = хронологический

    def test_local_day_bounds(self) -> None:
        start, end = local_day_bounds_utc(NOW, ALMATY)
        assert start == datetime(2026, 10, 19, 19, 0, tzinfo=UTC)  # 20.10 00:00 Алматы
        assert end == datetime(2026, 10, 20, 19, 0, tzinfo=UTC)  # 21.10 00:00 Алматы

    def test_local_day_uses_local_date_not_utc_date(self) -> None:
        # 21.10 02:00 в Алматы — это ещё 20.10 по UTC
        now = datetime(2026, 10, 20, 21, 0, tzinfo=UTC)
        start, end = local_day_bounds_utc(now, ALMATY)
        assert start == datetime(2026, 10, 20, 19, 0, tzinfo=UTC)
        assert end == datetime(2026, 10, 21, 19, 0, tzinfo=UTC)
