"""Inline-клавиатура списка задач и callback-data."""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.models import TaskPage

VIEW_ACTIVE = "a"
VIEW_TODAY = "t"
_BUTTON_TITLE_LIMIT = 25


class PageCB(CallbackData, prefix="pg"):
    view: str
    page: int


class DoneCB(CallbackData, prefix="done"):
    task_id: int
    view: str
    page: int


def shorten(text: str, limit: int = _BUTTON_TITLE_LIMIT) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def task_list_keyboard(page: TaskPage, view: str) -> InlineKeyboardMarkup:
    """Кнопка «Выполнено» под каждой задачей страницы + навигация «Назад»/«Далее»."""
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text=f"✅ Выполнено: {number}. {shorten(task.title)}",
                callback_data=DoneCB(task_id=task.id, view=view, page=page.page).pack(),
            )
        ]
        for number, task in enumerate(page.tasks, start=page.first_number)
    ]
    navigation: list[InlineKeyboardButton] = []
    if page.has_prev:
        navigation.append(
            InlineKeyboardButton(
                text="◀ Назад", callback_data=PageCB(view=view, page=page.page - 1).pack()
            )
        )
    if page.has_next:
        navigation.append(
            InlineKeyboardButton(
                text="Далее ▶", callback_data=PageCB(view=view, page=page.page + 1).pack()
            )
        )
    if navigation:
        rows.append(navigation)
    return InlineKeyboardMarkup(inline_keyboard=rows)
