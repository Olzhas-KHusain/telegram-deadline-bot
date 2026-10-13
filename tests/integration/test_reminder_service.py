import asyncio
from datetime import datetime, timedelta

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendMessage

from app.repositories.task_repository import TaskRepository
from app.services.reminder_service import ReminderService, build_reminder_text
from tests.helpers import ALMATY, NOW, FakeClock

ALICE = 1001
BOLAT = 2002
HOUR = timedelta(hours=1)


class FakeSender:
    def __init__(self, fail_for: set[int] | None = None) -> None:
        self.sent: list[tuple[int, str]] = []
        self.fail_for = fail_for or set()

    async def send_message(self, chat_id: int, text: str) -> None:
        if chat_id in self.fail_for:
            raise TelegramBadRequest(
                method=SendMessage(chat_id=chat_id, text=text), message="chat not found"
            )
        self.sent.append((chat_id, text))


async def add(repo: TaskRepository, user: int, title: str, deadline: datetime):
    return await repo.create(
        telegram_user_id=user, title=title, deadline_at=deadline, created_at=NOW
    )


def make_worker(repo: TaskRepository, sender: FakeSender, clock: FakeClock) -> ReminderService:
    return ReminderService(repo, sender, ALMATY, clock, interval=0.01)


async def test_not_sent_before_reminder_time(repo: TaskRepository, clock: FakeClock) -> None:
    await add(repo, ALICE, "рано", NOW + HOUR + timedelta(minutes=1))
    sender = FakeSender()
    assert await make_worker(repo, sender, clock).run_once() == 0
    assert sender.sent == []


async def test_sent_when_reminder_time_arrives_and_only_once(
    repo: TaskRepository, clock: FakeClock
) -> None:
    task = await add(repo, ALICE, "Лабораторная", NOW + HOUR + timedelta(minutes=2))
    sender = FakeSender()
    worker = make_worker(repo, sender, clock)

    assert await worker.run_once() == 0
    clock.now = NOW + timedelta(minutes=2)  # ровно deadline - 1 час
    assert await worker.run_once() == 1
    assert await worker.run_once() == 0  # повторная проверка
    clock.now = NOW + timedelta(minutes=40)
    assert await worker.run_once() == 0

    assert len(sender.sent) == 1
    chat_id, text = sender.sent[0]
    assert chat_id == ALICE
    assert "Лабораторная" in text and "20.10.2026 13:02" in text and "Asia/Almaty" in text
    stored = await repo.get_for_user(task.id, ALICE)
    assert stored is not None and stored.reminder_sent_at == NOW + timedelta(minutes=2)


async def test_task_created_less_than_hour_before_deadline_is_sent_on_next_cycle(
    repo: TaskRepository, clock: FakeClock
) -> None:
    await add(repo, ALICE, "срочно", NOW + timedelta(minutes=10))
    sender = FakeSender()
    assert await make_worker(repo, sender, clock).run_once() == 1


async def test_completed_and_overdue_tasks_are_skipped(
    repo: TaskRepository, clock: FakeClock
) -> None:
    completed = await add(repo, ALICE, "выполнена", NOW + timedelta(minutes=30))
    await repo.mark_completed(completed.id, ALICE, NOW)
    await add(repo, ALICE, "просрочена", NOW - timedelta(minutes=5))
    await add(repo, ALICE, "ровно сейчас", NOW)
    sender = FakeSender()
    assert await make_worker(repo, sender, clock).run_once() == 0
    assert sender.sent == []


async def test_restart_picks_up_missed_reminders_but_not_sent_or_overdue(
    repo: TaskRepository, clock: FakeClock
) -> None:
    await add(repo, ALICE, "напомнили до остановки", NOW + timedelta(minutes=50))
    first = make_worker(repo, FakeSender(), clock)
    assert await first.run_once() == 1

    # Бот был остановлен; пока он не работал, наступило время ещё двух напоминаний.
    await add(repo, ALICE, "пропущено, дедлайн впереди", NOW + timedelta(minutes=45))
    await add(repo, BOLAT, "дедлайн уже прошёл", NOW - timedelta(minutes=1))

    sender = FakeSender()
    restarted = make_worker(repo, sender, clock)  # «новый процесс» с той же БД
    assert await restarted.run_once() == 1
    assert [chat for chat, _ in sender.sent] == [ALICE]
    assert "пропущено" in sender.sent[0][1]
    assert await restarted.run_once() == 0


async def test_telegram_error_does_not_stop_others_and_is_not_marked_sent(
    repo: TaskRepository, clock: FakeClock, caplog: pytest.LogCaptureFixture
) -> None:
    broken = await add(repo, ALICE, "не доставится", NOW + timedelta(minutes=10))
    await add(repo, BOLAT, "доставится", NOW + timedelta(minutes=20))
    sender = FakeSender(fail_for={ALICE})
    worker = make_worker(repo, sender, clock)

    assert await worker.run_once() == 1
    assert [chat for chat, _ in sender.sent] == [BOLAT]
    stored = await repo.get_for_user(broken.id, ALICE)
    assert stored is not None and stored.reminder_sent_at is None
    assert "не доставится" not in caplog.text  # в лог не попадает содержимое задачи

    sender.fail_for.clear()  # Telegram снова доступен: повтор до дедлайна
    assert await worker.run_once() == 1
    assert [chat for chat, _ in sender.sent] == [BOLAT, ALICE]


async def test_worker_loop_survives_cycle_failure_and_stops_cleanly(
    repo: TaskRepository, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    await add(repo, ALICE, "task", NOW + timedelta(minutes=10))
    sender = FakeSender()
    worker = make_worker(repo, sender, clock)

    real = repo.list_due_reminders
    calls = 0

    async def flaky(now: datetime, lead: timedelta):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("temporary db failure")
        return await real(now, lead)

    monkeypatch.setattr(repo, "list_due_reminders", flaky)

    task = worker.start()
    for _ in range(200):
        if sender.sent:
            break
        await asyncio.sleep(0.01)
    assert len(sender.sent) == 1 and calls >= 2 and not task.done()

    await worker.stop()
    assert task.done()
    await worker.stop()  # повторная остановка безопасна


def test_reminder_text_contains_title_local_deadline_and_call_to_action() -> None:
    from app.models import Task, TaskStatus

    task = Task(1, ALICE, "Эссе", NOW + HOUR, TaskStatus.PENDING, NOW)
    text = build_reminder_text(task, ALMATY)
    assert "Эссе" in text and "20.10.2026 13:00" in text and "Проверьте" in text
