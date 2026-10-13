"""Команды /start и /help, а также ответ на команды в групповых чатах."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.keyboards.main_menu import main_menu_keyboard
from app.services.task_service import DEADLINE_FORMAT_HINT, TaskService

PRIVATE_CHAT = F.chat.type == ChatType.PRIVATE

WELCOME_TEXT = (
    "Привет! Я UniMate — помогаю студентам SDU не забывать учебные дедлайны.\n\n"
    "Добавьте задачу с названием и дедлайном, а за час до срока я пришлю напоминание.\n\n"
    "Выберите действие на клавиатуре ниже или отправьте /help."
)

GROUP_NOTICE = (
    "UniMate работает только в личном чате. "
    "Напишите мне напрямую, чтобы управлять задачами."
)

BOT_COMMANDS = ("start", "help", "add", "tasks", "today", "cancel")


async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(WELCOME_TEXT, reply_markup=main_menu_keyboard())


async def cmd_help(message: Message, task_service: TaskService) -> None:
    await message.answer(
        "Команды:\n"
        "/add — добавить задачу\n"
        "/tasks — активные задачи\n"
        "/today — задачи на сегодня\n"
        "/cancel — отменить создание задачи\n"
        "/help — эта справка\n\n"
        f"Дедлайн вводится в формате {DEADLINE_FORMAT_HINT} "
        f"(время {task_service.timezone_name}), например {task_service.example_deadline()}.\n"
        "Напоминание приходит за час до дедлайна.",
        reply_markup=main_menu_keyboard(),
    )


async def group_notice(message: Message) -> None:
    await message.answer(GROUP_NOTICE)


def build_router() -> Router:
    router = Router(name="start")
    router.message.register(cmd_start, Command("start"), PRIVATE_CHAT)
    router.message.register(cmd_help, Command("help"), PRIVATE_CHAT)
    router.message.register(group_notice, Command(*BOT_COMMANDS), ~PRIVATE_CHAT)
    return router
