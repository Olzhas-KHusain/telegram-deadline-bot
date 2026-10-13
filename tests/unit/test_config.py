import pytest

from app import config
from app.config import ConfigError, load_settings
from app.main import main

VALID_TOKEN = "123456789:test-token-value"


def test_missing_token_raises_clear_error() -> None:
    with pytest.raises(ConfigError, match="BOT_TOKEN"):
        load_settings({})


def test_blank_token_raises() -> None:
    with pytest.raises(ConfigError, match="BOT_TOKEN"):
        load_settings({"BOT_TOKEN": "   "})


def test_malformed_token_error_does_not_leak_token() -> None:
    secret = "not a valid token"
    with pytest.raises(ConfigError) as exc_info:
        load_settings({"BOT_TOKEN": secret})
    assert secret not in str(exc_info.value)


def test_defaults() -> None:
    settings = load_settings({"BOT_TOKEN": VALID_TOKEN})
    assert settings.bot_token == VALID_TOKEN
    assert settings.db_path == "data/unimate.sqlite3"
    assert settings.timezone == "Asia/Almaty"
    assert settings.log_level == "INFO"
    assert settings.tz.key == "Asia/Almaty"


def test_custom_values() -> None:
    settings = load_settings(
        {"BOT_TOKEN": VALID_TOKEN, "DB_PATH": "x/y.db", "TIMEZONE": "UTC", "LOG_LEVEL": "debug"}
    )
    assert (settings.db_path, settings.timezone, settings.log_level) == ("x/y.db", "UTC", "DEBUG")


def test_unknown_timezone_and_log_level() -> None:
    with pytest.raises(ConfigError, match="TIMEZONE"):
        load_settings({"BOT_TOKEN": VALID_TOKEN, "TIMEZONE": "Mars/Olympus"})
    with pytest.raises(ConfigError, match="LOG_LEVEL"):
        load_settings({"BOT_TOKEN": VALID_TOKEN, "LOG_LEVEL": "LOUD"})


def test_settings_repr_hides_token() -> None:
    assert VALID_TOKEN not in repr(load_settings({"BOT_TOKEN": VALID_TOKEN}))


def test_main_exits_with_message_without_token(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(config, "load_dotenv", lambda *args, **kwargs: False)  # не читать .env
    monkeypatch.delenv("BOT_TOKEN", raising=False)
    assert main() == 1
    assert "BOT_TOKEN" in capsys.readouterr().err
