from datetime import datetime, timedelta
from pathlib import Path

import aiosqlite

from app.db.connection import init_db, open_database
from app.models import TaskStatus
from app.repositories.task_repository import TaskRepository
from tests.helpers import ALMATY, NOW

ALICE = 1001
BOLAT = 2002
HOUR = timedelta(hours=1)


async def add(repo: TaskRepository, user: int, title: str, deadline: datetime):
    return await repo.create(
        telegram_user_id=user, title=title, deadline_at=deadline, created_at=NOW
    )


async def test_create_returns_task_with_utc_deadline(repo: TaskRepository) -> None:
    deadline = datetime(2026, 10, 25, 23, 59, tzinfo=ALMATY)
    task = await add(repo, ALICE, "Отчёт", deadline)

    assert task.id > 0
    assert task.status is TaskStatus.PENDING
    assert task.deadline_at == deadline
    assert task.deadline_at.utcoffset() == timedelta(0)
    assert task.completed_at is None and task.reminder_sent_at is None


async def test_db_stores_utc_iso_string(repo: TaskRepository, db: aiosqlite.Connection) -> None:
    await add(repo, ALICE, "Отчёт", datetime(2026, 10, 25, 23, 59, tzinfo=ALMATY))
    async with db.execute("SELECT deadline_at FROM tasks") as cursor:
        row = await cursor.fetchone()
    assert row is not None and row[0] == "2026-10-25T18:59:00.000000+00:00"


async def test_list_active_is_sorted_filtered_and_isolated(repo: TaskRepository) -> None:
    late = await add(repo, ALICE, "поздно", NOW + 3 * HOUR)
    early = await add(repo, ALICE, "рано", NOW + HOUR)
    done = await add(repo, ALICE, "готово", NOW + 2 * HOUR)
    await add(repo, BOLAT, "чужая", NOW + HOUR)
    await repo.mark_completed(done.id, ALICE, NOW)

    assert [t.id for t in await repo.list_active(ALICE)] == [early.id, late.id]
    assert [t.title for t in await repo.list_active(BOLAT)] == ["чужая"]
    assert await repo.count_active(ALICE) == 2


async def test_list_active_limit_offset(repo: TaskRepository) -> None:
    for i in range(5):
        await add(repo, ALICE, f"t{i}", NOW + (i + 1) * HOUR)
    page = await repo.list_active(ALICE, limit=2, offset=2)
    assert [t.title for t in page] == ["t2", "t3"]


async def test_list_active_between_is_half_open(repo: TaskRepository) -> None:
    start, end = NOW, NOW + 24 * HOUR
    at_start = await add(repo, ALICE, "start", start)
    inside = await add(repo, ALICE, "inside", start + HOUR)
    await add(repo, ALICE, "at_end", end)  # исключается
    await add(repo, ALICE, "before", start - timedelta(seconds=1))
    await add(repo, BOLAT, "other_user", start + HOUR)

    found = await repo.list_active_between(ALICE, start, end)
    assert [t.id for t in found] == [at_start.id, inside.id]


async def test_get_for_user_checks_owner(repo: TaskRepository) -> None:
    task = await add(repo, ALICE, "моя", NOW + HOUR)
    assert (await repo.get_for_user(task.id, ALICE)) == task
    assert await repo.get_for_user(task.id, BOLAT) is None
    assert await repo.get_for_user(9999, ALICE) is None


async def test_mark_completed_sets_status_and_timestamp_once(repo: TaskRepository) -> None:
    task = await add(repo, ALICE, "моя", NOW + HOUR)
    finished_at = NOW + timedelta(minutes=5)

    assert await repo.mark_completed(task.id, ALICE, finished_at) is True
    stored = await repo.get_for_user(task.id, ALICE)
    assert stored is not None
    assert stored.status is TaskStatus.COMPLETED and stored.completed_at == finished_at
    assert await repo.mark_completed(task.id, ALICE, NOW + HOUR) is False  # повтор безопасен
    again = await repo.get_for_user(task.id, ALICE)
    assert again is not None and again.completed_at == finished_at


async def test_cannot_complete_foreign_task(repo: TaskRepository) -> None:
    task = await add(repo, ALICE, "моя", NOW + HOUR)
    assert await repo.mark_completed(task.id, BOLAT, NOW) is False
    stored = await repo.get_for_user(task.id, ALICE)
    assert stored is not None and stored.status is TaskStatus.PENDING


async def test_init_is_idempotent_and_data_survives_reopen(tmp_path: Path) -> None:
    path = str(tmp_path / "persist.sqlite3")
    conn = await open_database(path)
    task = await add(TaskRepository(conn), ALICE, "сохранится", NOW + HOUR)
    await init_db(conn)  # повторная инициализация
    await conn.close()

    conn = await open_database(path)  # «перезапуск процесса»
    try:
        stored = await TaskRepository(conn).get_for_user(task.id, ALICE)
        async with conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_tasks_%'"
        ) as cursor:
            indexes = {row[0] for row in await cursor.fetchall()}
    finally:
        await conn.close()
    assert stored == task
    assert "idx_tasks_user_status_deadline" in indexes


async def test_user_input_is_never_interpolated_into_sql(repo: TaskRepository) -> None:
    nasty = "x'); DROP TABLE tasks; --"
    task = await add(repo, ALICE, nasty, NOW + HOUR)
    assert (await repo.get_for_user(task.id, ALICE)).title == nasty  # type: ignore[union-attr]
    assert len(await repo.list_active(ALICE)) == 1


class TestDueReminders:
    async def test_selection_rules(self, repo: TaskRepository) -> None:
        now = NOW
        due_soon = await add(repo, ALICE, "через 30 мин", now + timedelta(minutes=30))
        due_edge = await add(repo, ALICE, "ровно через час", now + HOUR)
        await add(repo, ALICE, "через 61 мин", now + timedelta(minutes=61))
        await add(repo, ALICE, "уже прошёл", now - timedelta(minutes=1))
        await add(repo, ALICE, "ровно сейчас", now)  # дедлайн строго позже now
        completed = await add(repo, ALICE, "выполнена", now + timedelta(minutes=20))
        await repo.mark_completed(completed.id, ALICE, now)
        sent = await add(repo, ALICE, "уже напомнили", now + timedelta(minutes=10))
        await repo.mark_reminder_sent(sent.id, now)

        due = await repo.list_due_reminders(now, HOUR)
        assert [t.id for t in due] == [due_soon.id, due_edge.id]

    async def test_mark_reminder_sent_only_once(self, repo: TaskRepository) -> None:
        task = await add(repo, ALICE, "t", NOW + timedelta(minutes=10))
        assert await repo.mark_reminder_sent(task.id, NOW) is True
        assert await repo.mark_reminder_sent(task.id, NOW + HOUR) is False
        stored = await repo.get_for_user(task.id, ALICE)
        assert stored is not None and stored.reminder_sent_at == NOW

    async def test_across_all_users(self, repo: TaskRepository) -> None:
        await add(repo, ALICE, "a", NOW + timedelta(minutes=10))
        await add(repo, BOLAT, "b", NOW + timedelta(minutes=20))
        assert {t.telegram_user_id for t in await repo.list_due_reminders(NOW, HOUR)} == {
            ALICE,
            BOLAT,
        }


