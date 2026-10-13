"""Главная клавиатура и тексты её кнопок."""

from __future__ import annotations

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

BTN_ADD = "Добавить задачу"
BTN_TASKS = "Мои задачи"
BTN_TODAY = "На сегодня"


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_ADD)],
            [KeyboardButton(text=BTN_TASKS), KeyboardButton(text=BTN_TODAY)],
        ],
        resize_keyboard=True,
    )
