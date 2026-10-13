"""Создание задач (FSM), списки задач, «на сегодня» и действие «Выполнено»."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from app.keyboards.main_menu import BTN_ADD, BTN_TASKS, BTN_TODAY, main_menu_keyboard
from app.keyboards.task_list import (
    VIEW_ACTIVE,
    VIEW_TODAY,
    DoneCB,
    PageCB,
    shorten,
    task_list_keyboard,
)
from app.services.task_service import (
    DEADLINE_FORMAT_HINT,
    TaskInputError,
    TaskService,
    validate_title,
)

EMPTY_ACTIVE_TEXT = (
    "У вас пока нет активных задач. "
    "Нажмите «Добавить задачу» или отправьте /add, чтобы создать первую."
)
EMPTY_TODAY_TEXT = "На сегодня активных дедлайнов нет."


class AddTask(StatesGroup):
    waiting_for_title = State()
    waiting_for_deadline = State()


# --------------------------------------------------------------------------- создание задачи


def _ask_deadline_text(task_service: TaskService) -> str:
    return (
        f"Введите дедлайн в формате {DEADLINE_FORMAT_HINT} "
        f"(время {task_service.timezone_name}), например {task_service.example_deadline()}.\n"
        "Для отмены отправьте /cancel."
    )


async def start_add(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(AddTask.waiting_for_title)
    await message.answer("Введите название задачи (до 200 символов). Для отмены отправьте /cancel.")


async def cancel(message: Message, state: FSMContext) -> None:
    if await state.get_state() is None:
        await message.answer("Сейчас нечего отменять.", reply_markup=main_menu_keyboard())
        return
    await state.clear()
    await message.answer(
        "Создание задачи отменено. Ничего не сохранено.", reply_markup=main_menu_keyboard()
    )


async def process_title(message: Message, state: FSMContext, task_service: TaskService) -> None:
    try:
        title = validate_title(message.text or "")
    except TaskInputError as exc:
        await message.answer(f"{exc}\nВведите название ещё раз или отправьте /cancel.")
        return
    await state.update_data(title=title)
    await state.set_state(AddTask.waiting_for_deadline)
    await message.answer(f"Название: «{title}»\n\n{_ask_deadline_text(task_service)}")


async def process_deadline(message: Message, state: FSMContext, task_service: TaskService) -> None:
    user = message.from_user
    if user is None:
        return
    title = (await state.get_data()).get("title")
    if not isinstance(title, str) or not title:  # защита от неполного/устаревшего состояния
        await state.set_state(AddTask.waiting_for_title)
        await message.answer("Не нашёл название задачи. Начнём заново: введите название.")
        return
    try:
        task = await task_service.create_task(user.id, title, message.text or "")
    except TaskInputError as exc:
        await message.answer(f"{exc}\nВведите дедлайн ещё раз или отправьте /cancel.")
        return
    await state.clear()
    await message.answer(
        "✅ Задача сохранена.\n\n"
        f"«{task.title}»\n"
        f"📅 Дедлайн: {task_service.format_deadline(task.deadline_at)} "
        f"({task_service.timezone_name})\n"
        "⏰ Напоминание придёт за час до дедлайна.",
        reply_markup=main_menu_keyboard(),
    )


async def unexpected_input(message: Message, state: FSMContext) -> None:
    """Нетекстовое сообщение или неизвестная команда посреди мастера."""
    if await state.get_state() == AddTask.waiting_for_title.state:
        hint = "Отправьте название задачи текстом (до 200 символов)"
    else:
        hint = f"Отправьте дедлайн текстом в формате {DEADLINE_FORMAT_HINT}"
    await message.answer(f"{hint} или /cancel для отмены.")


# ------------------------------------------------------------------------------------ списки


async def render_view(
    task_service: TaskService, user_id: int, view: str, page: int
) -> tuple[str, InlineKeyboardMarkup | None]:
    """Текст и клавиатура списка. Пустой список — без клавиатуры."""
    if view == VIEW_TODAY:
        result = await task_service.get_today_page(user_id, page)
        header, empty_text = "📅 Задачи на сегодня", EMPTY_TODAY_TEXT
    else:
        view = VIEW_ACTIVE
        result = await task_service.get_active_page(user_id, page)
        header, empty_text = "📋 Активные задачи", EMPTY_ACTIVE_TEXT

    if result.total == 0:
        return empty_text, None

    title_line = f"{header}: {result.total}"
    if result.total_pages > 1:
        title_line += f" (страница {result.page} из {result.total_pages})"
    lines = [title_line, ""]
    for number, task in enumerate(result.tasks, start=result.first_number):
        lines.append(f"{number}. {task.title}")
        lines.append(f"    📅 {task_service.format_deadline(task.deadline_at)}")
    return "\n".join(lines), task_list_keyboard(result, view)


async def _send_view(message: Message, task_service: TaskService, view: str) -> None:
    user = message.from_user
    if user is None:
        return
    text, markup = await render_view(task_service, user.id, view, 1)
    await message.answer(text, reply_markup=markup)


async def show_tasks(message: Message, state: FSMContext, task_service: TaskService) -> None:
    await state.clear()
    await _send_view(message, task_service, VIEW_ACTIVE)


async def show_today(message: Message, state: FSMContext, task_service: TaskService) -> None:
    await state.clear()
    await _send_view(message, task_service, VIEW_TODAY)


async def _refresh_view(
    callback: CallbackQuery, task_service: TaskService, view: str, page: int
) -> None:
    message = callback.message
    if not isinstance(message, Message):
        return
    text, markup = await render_view(task_service, callback.from_user.id, view, page)
    try:
        await message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc):
            raise


async def on_page(
    callback: CallbackQuery, callback_data: PageCB, task_service: TaskService
) -> None:
    await callback.answer()
    await _refresh_view(callback, task_service, callback_data.view, callback_data.page)


async def on_done(
    callback: CallbackQuery, callback_data: DoneCB, task_service: TaskService
) -> None:
    # Владелец берётся только из callback.from_user.id; callback_data ему не доверяем.
    task = await task_service.complete_task(callback.from_user.id, callback_data.task_id)
    if task is None:
        await callback.answer("Задача уже выполнена или недоступна.")
    else:
        await callback.answer(f"✅ Выполнено: {shorten(task.title, 150)}")
    await _refresh_view(callback, task_service, callback_data.view, callback_data.page)


# ----------------------------------------------------------------------------------- роутер


def build_router() -> Router:
    router = Router(name="tasks")
    # FR-1: только личные чаты.
    router.message.filter(F.chat.type == ChatType.PRIVATE)
    router.callback_query.filter(F.message.chat.type == ChatType.PRIVATE)

    # Команды и кнопки меню срабатывают в любом состоянии и прерывают мастер.
    router.message.register(start_add, Command("add"))
    router.message.register(start_add, F.text == BTN_ADD)
    router.message.register(cancel, Command("cancel"))
    router.message.register(show_tasks, Command("tasks"))
    router.message.register(show_tasks, F.text == BTN_TASKS)
    router.message.register(show_today, Command("today"))
    router.message.register(show_today, F.text == BTN_TODAY)

    router.callback_query.register(on_page, PageCB.filter())
    router.callback_query.register(on_done, DoneCB.filter())

    # Шаги мастера: обычный текст (не команда).
    router.message.register(
        process_title, AddTask.waiting_for_title, F.text, ~F.text.startswith("/")
    )
    router.message.register(
        process_deadline, AddTask.waiting_for_deadline, F.text, ~F.text.startswith("/")
    )
    router.message.register(
        unexpected_input, StateFilter(AddTask.waiting_for_title, AddTask.waiting_for_deadline)
    )
    return router
