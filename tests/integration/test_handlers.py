"""Сквозные тесты Telegram-хендлеров: настоящий Dispatcher + подменённая HTTP-сессия бота."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any

import pytest
import pytest_asyncio
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.methods import AnswerCallbackQuery, EditMessageText, SendMessage, TelegramMethod
from aiogram.types import Chat, Message

from app.main import build_dispatcher
from app.repositories.task_repository import TaskRepository
from app.services.task_service import TaskService

AIGERIM = 1001
NURSULTAN = 2002


class MockedSession(BaseSession):
    """Вместо HTTP запоминает вызванные методы Bot API."""

    def __init__(self) -> None:
        super().__init__()
        self.requests: list[TelegramMethod[Any]] = []

    async def close(self) -> None:
        return None

    async def make_request(self, bot: Bot, method: TelegramMethod[Any], timeout: Any = None) -> Any:
        self.requests.append(method)
        if isinstance(method, (SendMessage, EditMessageText)):
            return Message(
                message_id=len(self.requests),
                date=datetime.now(UTC),
                chat=Chat(id=1, type="private"),
                text=method.text,
            )
        return True

    async def stream_content(self, *args: Any, **kwargs: Any) -> AsyncGenerator[bytes, None]:
        yield b""


class Harness:
    def __init__(self, dp: Dispatcher, bot: Bot, session: MockedSession) -> None:
        self.dp, self.bot, self.session = dp, bot, session
        self._update_id = 0

    def _next_id(self) -> int:
        self._update_id += 1
        return self._update_id

    @staticmethod
    def _user(user_id: int) -> dict[str, Any]:
        return {"id": user_id, "is_bot": False, "first_name": "Student"}

    async def say(self, user_id: int, text: str, chat_type: str = "private") -> None:
        message: dict[str, Any] = {
            "message_id": self._next_id(),
            "date": 1_700_000_000,
            "chat": {"id": user_id if chat_type == "private" else -user_id, "type": chat_type},
            "from": self._user(user_id),
            "text": text,
        }
        if text.startswith("/"):
            command = text.split()[0]
            message["entities"] = [{"type": "bot_command", "offset": 0, "length": len(command)}]
        await self.dp.feed_raw_update(
            self.bot, {"update_id": self._next_id(), "message": message}
        )

    async def send_sticker_like(self, user_id: int) -> None:
        """Нетекстовое сообщение (фото без подписи)."""
        message = {
            "message_id": self._next_id(),
            "date": 1_700_000_000,
            "chat": {"id": user_id, "type": "private"},
            "from": self._user(user_id),
            "photo": [{"file_id": "x", "file_unique_id": "y", "width": 1, "height": 1}],
        }
        await self.dp.feed_raw_update(
            self.bot, {"update_id": self._next_id(), "message": message}
        )

    async def press(self, user_id: int, data: str) -> None:
        callback = {
            "id": str(self._next_id()),
            "from": self._user(user_id),
            "chat_instance": "ci",
            "data": data,
            "message": {
                "message_id": 1,
                "date": 1_700_000_000,
                "chat": {"id": user_id, "type": "private"},
                "text": "list",
            },
        }
        await self.dp.feed_raw_update(
            self.bot, {"update_id": self._next_id(), "callback_query": callback}
        )

    # --- чтение того, что бот «отправил» ---
    def sent(self) -> list[SendMessage]:
        return [r for r in self.session.requests if isinstance(r, SendMessage)]

    def last_text(self) -> str:
        return self.sent()[-1].text

    def edits(self) -> list[EditMessageText]:
        return [r for r in self.session.requests if isinstance(r, EditMessageText)]

    def answers(self) -> list[AnswerCallbackQuery]:
        return [r for r in self.session.requests if isinstance(r, AnswerCallbackQuery)]

    @staticmethod
    def buttons(message: SendMessage | EditMessageText, prefix: str = "") -> list[Any]:
        """Inline-кнопки сообщения, callback_data которых начинается с ``prefix``."""
        markup = message.reply_markup
        assert markup is not None
        return [
            b
            for row in markup.inline_keyboard
            for b in row
            if b.callback_data and b.callback_data.startswith(prefix)
        ]

    def done_buttons(self, message: SendMessage | EditMessageText) -> list[str]:
        return [b.callback_data for b in self.buttons(message, "done:")]


@pytest_asyncio.fixture
async def bot_env(service: TaskService) -> Harness:
    session = MockedSession()
    bot = Bot(token="42:TEST", session=session)
    return Harness(build_dispatcher(service), bot, session)


@pytest.fixture
def h(bot_env: Harness) -> Harness:
    return bot_env


async def create_via_chat(h: Harness, user: int, title: str, deadline: str) -> None:
    await h.say(user, "/add")
    await h.say(user, title)
    await h.say(user, deadline)


# --------------------------------------------------------------------------- Issue 1: /start


async def test_start_replies_in_russian_with_main_menu(h: Harness) -> None:
    await h.say(AIGERIM, "/start")
    assert "UniMate" in h.last_text() and "дедлайн" in h.last_text()
    keyboard = h.sent()[-1].reply_markup.keyboard  # type: ignore[union-attr]
    labels = {button.text for row in keyboard for button in row}
    assert labels == {"Добавить задачу", "Мои задачи", "На сегодня"}


async def test_help_describes_commands_and_format(h: Harness) -> None:
    await h.say(AIGERIM, "/help")
    for fragment in ("/add", "/tasks", "/today", "/cancel", "ДД.ММ.ГГГГ ЧЧ:ММ", "21.10.2026 23:59"):
        assert fragment in h.last_text()


# ------------------------------------------------------------------ Issue 3: создание задачи


@pytest.mark.parametrize("trigger", ["/add", "Добавить задачу"])
async def test_command_and_button_start_the_same_flow(h: Harness, trigger: str) -> None:
    await h.say(AIGERIM, trigger)
    assert "название" in h.last_text().lower()


async def test_full_flow_saves_one_task_and_confirms(
    h: Harness, repo: TaskRepository
) -> None:
    await create_via_chat(h, AIGERIM, "  Курсовая по БД  ", "25.10.2026 23:59")

    tasks = await repo.list_active(AIGERIM)
    assert len(tasks) == 1 and tasks[0].title == "Курсовая по БД"
    assert tasks[0].deadline_at == datetime(2026, 10, 25, 18, 59, tzinfo=UTC)
    confirmation = h.last_text()
    assert "Курсовая по БД" in confirmation
    assert "25.10.2026 23:59" in confirmation and "Asia/Almaty" in confirmation
    assert "за час" in confirmation


@pytest.mark.parametrize("bad_title", ["   ", "а" * 201])
async def test_bad_title_is_rejected_and_asked_again(
    h: Harness, repo: TaskRepository, bad_title: str
) -> None:
    await h.say(AIGERIM, "/add")
    await h.say(AIGERIM, bad_title)
    assert "название" in h.last_text().lower() and "/cancel" in h.last_text()
    await h.say(AIGERIM, "Нормальное")
    assert "дедлайн" in h.last_text().lower()
    assert await repo.list_active(AIGERIM) == []


@pytest.mark.parametrize("bad_deadline", ["завтра", "31.02.2027 10:00", "19.10.2026 10:00"])
async def test_bad_deadline_can_be_retyped_without_retyping_title(
    h: Harness, repo: TaskRepository, bad_deadline: str
) -> None:
    await h.say(AIGERIM, "/add")
    await h.say(AIGERIM, "Эссе")
    await h.say(AIGERIM, bad_deadline)
    assert "ещё раз" in h.last_text()
    assert await repo.list_active(AIGERIM) == []

    await h.say(AIGERIM, "22.10.2026 18:00")  # название вводить заново не нужно
    tasks = await repo.list_active(AIGERIM)
    assert [t.title for t in tasks] == ["Эссе"]


@pytest.mark.parametrize("step", ["title", "deadline"])
async def test_cancel_at_any_step_saves_nothing(
    h: Harness, repo: TaskRepository, step: str
) -> None:
    await h.say(AIGERIM, "/add")
    if step == "deadline":
        await h.say(AIGERIM, "Эссе")
    await h.say(AIGERIM, "/cancel")
    assert "отменено" in h.last_text()

    await h.say(AIGERIM, "22.10.2026 18:00")  # состояние очищено: это просто текст вне мастера
    assert await repo.list_active(AIGERIM) == []
    await h.say(AIGERIM, "/cancel")
    assert "нечего отменять" in h.last_text()


async def test_menu_button_during_wizard_is_not_taken_as_title(
    h: Harness, repo: TaskRepository
) -> None:
    await h.say(AIGERIM, "/add")
    await h.say(AIGERIM, "Мои задачи")
    assert "нет активных задач" in h.last_text()
    await h.say(AIGERIM, "22.10.2026 18:00")  # мастер прерван
    assert await repo.list_active(AIGERIM) == []


async def test_unknown_command_and_non_text_inside_wizard_get_a_hint(
    h: Harness, repo: TaskRepository
) -> None:
    await h.say(AIGERIM, "/add")
    await h.say(AIGERIM, "/unknown")
    assert "/cancel" in h.last_text()
    await h.send_sticker_like(AIGERIM)
    assert "текстом" in h.last_text()
    await h.say(AIGERIM, "Название")
    assert "дедлайн" in h.last_text().lower()
    assert await repo.list_active(AIGERIM) == []


async def test_wizard_state_is_per_user(h: Harness, repo: TaskRepository) -> None:
    await h.say(AIGERIM, "/add")
    await h.say(NURSULTAN, "просто текст")  # у Нурсултана мастер не запущен
    await h.say(AIGERIM, "Задача Айгерим")
    await h.say(AIGERIM, "22.10.2026 18:00")
    assert [t.title for t in await repo.list_active(AIGERIM)] == ["Задача Айгерим"]
    assert await repo.list_active(NURSULTAN) == []


async def test_group_chats_do_not_create_tasks(h: Harness, repo: TaskRepository) -> None:
    await h.say(AIGERIM, "/add", chat_type="group")
    assert "личном чате" in h.last_text()
    await h.say(AIGERIM, "Название", chat_type="group")
    await h.say(AIGERIM, "22.10.2026 18:00", chat_type="group")
    assert await repo.list_active(AIGERIM) == []
    assert len(h.sent()) == 1  # на обычные сообщения в группе бот не отвечает


# ------------------------------------------------------------------ Issue 4: списки и «Выполнено»


@pytest.mark.parametrize("trigger", ["/tasks", "Мои задачи"])
async def test_empty_tasks_state(h: Harness, trigger: str) -> None:
    await h.say(AIGERIM, trigger)
    assert "нет активных задач" in h.last_text() and "Добавить задачу" in h.last_text()


@pytest.mark.parametrize("trigger", ["/today", "На сегодня"])
async def test_empty_today_state(h: Harness, trigger: str) -> None:
    await h.say(AIGERIM, trigger)
    assert "На сегодня активных дедлайнов нет" in h.last_text()


async def test_tasks_list_is_sorted_and_shows_local_deadline_and_done_buttons(h: Harness) -> None:
    await create_via_chat(h, AIGERIM, "Позже", "26.10.2026 10:00")
    await create_via_chat(h, AIGERIM, "Раньше", "24.10.2026 09:30")
    await h.say(AIGERIM, "/tasks")

    text = h.last_text()
    assert text.index("Раньше") < text.index("Позже")
    assert "24.10.2026 09:30" in text and "26.10.2026 10:00" in text
    assert len(h.done_buttons(h.sent()[-1])) == 2
    assert all("Выполнено" in b.text for b in h.buttons(h.sent()[-1]))


async def test_pagination_buttons_navigate_between_pages(h: Harness) -> None:
    for i in range(12):
        await create_via_chat(h, AIGERIM, f"Задача {i:02d}", f"{i + 1:02d}.11.2026 10:00")
    await h.say(AIGERIM, "/tasks")
    first = h.sent()[-1]
    assert len(h.done_buttons(first)) == 10 and "страница 1 из 2" in first.text
    nav = h.buttons(first, "pg:")
    assert [b.text for b in nav] == ["Далее ▶"]

    await h.press(AIGERIM, nav[0].callback_data)
    second = h.edits()[-1]
    assert "страница 2 из 2" in second.text and len(h.done_buttons(second)) == 2
    assert "Задача 10" in second.text and "Задача 00" not in second.text
    assert [b.text for b in h.buttons(second, "pg:")] == ["◀ Назад"]


async def test_today_shows_only_todays_active_tasks(h: Harness) -> None:
    await create_via_chat(h, AIGERIM, "Сегодня вечером", "20.10.2026 21:00")
    await create_via_chat(h, AIGERIM, "Завтра", "21.10.2026 09:00")
    await h.say(AIGERIM, "/today")
    assert "Сегодня вечером" in h.last_text() and "Завтра" not in h.last_text()


async def test_done_button_completes_task_and_refreshes_list(
    h: Harness, repo: TaskRepository
) -> None:
    await create_via_chat(h, AIGERIM, "Первая", "24.10.2026 10:00")
    await create_via_chat(h, AIGERIM, "Вторая", "25.10.2026 10:00")
    await h.say(AIGERIM, "/tasks")
    first_button = h.done_buttons(h.sent()[-1])[0]

    await h.press(AIGERIM, first_button)

    assert [t.title for t in await repo.list_active(AIGERIM)] == ["Вторая"]
    refreshed = h.edits()[-1]
    assert "Вторая" in refreshed.text and "Первая" not in refreshed.text
    assert "Выполнено" in (h.answers()[-1].text or "")

    await h.press(AIGERIM, first_button)  # повторное нажатие безопасно
    assert "уже выполнена или недоступна" in (h.answers()[-1].text or "")
    assert len(await repo.list_active(AIGERIM)) == 1


async def test_done_on_last_task_shows_empty_state(h: Harness) -> None:
    await create_via_chat(h, AIGERIM, "Единственная", "24.10.2026 10:00")
    await h.say(AIGERIM, "/tasks")
    await h.press(AIGERIM, h.done_buttons(h.sent()[-1])[0])
    assert "нет активных задач" in h.edits()[-1].text
    assert h.edits()[-1].reply_markup is None


async def test_user_cannot_complete_foreign_task_via_forged_callback(
    h: Harness, repo: TaskRepository
) -> None:
    await create_via_chat(h, AIGERIM, "Чужая", "24.10.2026 10:00")
    await h.say(AIGERIM, "/tasks")
    forged = h.done_buttons(h.sent()[-1])[0]

    await h.press(NURSULTAN, forged)  # Нурсултан подставляет callback Айгерим

    tasks = await repo.list_active(AIGERIM)
    assert [t.title for t in tasks] == ["Чужая"]
    assert "недоступна" in (h.answers()[-1].text or "")
    # и чужой список он тоже не увидит
    await h.say(NURSULTAN, "/tasks")
    assert "Чужая" not in h.last_text()


async def test_done_for_missing_task_is_neutral(h: Harness) -> None:
    await h.press(AIGERIM, "done:9999:a:1")
    assert "недоступна" in (h.answers()[-1].text or "")
