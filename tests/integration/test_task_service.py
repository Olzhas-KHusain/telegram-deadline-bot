from datetime import timedelta

import pytest

from app.models import TaskStatus
from app.repositories.task_repository import TaskRepository
from app.services.task_service import TaskInputError, TaskService
from tests.helpers import NOW, FakeClock

ALICE = 1001
BOLAT = 2002


async def create(service: TaskService, user: int, title: str, deadline: str):
    return await service.create_task(user, title, deadline)


class TestCreate:
    async def test_creates_exactly_one_task_for_current_user(
        self, service: TaskService, repo: TaskRepository
    ) -> None:
        task = await create(service, ALICE, "  Сдать лабу  ", "21.10.2026 23:59")
        assert task.title == "Сдать лабу"
        assert task.telegram_user_id == ALICE
        assert task.status is TaskStatus.PENDING
        assert service.format_deadline(task.deadline_at) == "21.10.2026 23:59"
        assert len(await repo.list_active(ALICE)) == 1
        assert await repo.list_active(BOLAT) == []

    @pytest.mark.parametrize(
        ("title", "deadline"),
        [
            ("", "21.10.2026 23:59"),
            ("а" * 201, "21.10.2026 23:59"),
            ("ok", "завтра"),
            ("ok", "19.10.2026 10:00"),
        ],
    )
    async def test_invalid_input_is_rejected_and_not_saved(
        self, service: TaskService, repo: TaskRepository, title: str, deadline: str
    ) -> None:
        with pytest.raises(TaskInputError):
            await create(service, ALICE, title, deadline)
        assert await repo.list_active(ALICE) == []

    async def test_deadline_must_be_in_future_at_save_time(
        self, service: TaskService, clock: FakeClock
    ) -> None:
        await create(service, ALICE, "ok", "20.10.2026 12:30")
        clock.now = NOW + timedelta(hours=1)  # 13:00 локального времени — 12:30 уже в прошлом
        with pytest.raises(TaskInputError, match="в будущем"):
            await create(service, ALICE, "ok", "20.10.2026 12:30")


class TestActivePages:
    async def test_pagination_10_per_page_and_sorting(self, service: TaskService) -> None:
        # 25 задач, созданных в обратном порядке дедлайнов (01.11 .. 25.11)
        for day in range(25, 0, -1):
            await create(service, ALICE, f"task {day}", f"{day:02d}.11.2026 10:00")

        first = await service.get_active_page(ALICE, 1)
        second = await service.get_active_page(ALICE, 2)
        third = await service.get_active_page(ALICE, 3)

        assert (first.total, first.total_pages) == (25, 3)
        assert [len(p.tasks) for p in (first, second, third)] == [10, 10, 5]
        titles = [t.title for p in (first, second, third) for t in p.tasks]
        assert titles == [f"task {d}" for d in range(1, 26)]
        assert (first.has_prev, first.has_next) == (False, True)
        assert (second.has_prev, second.has_next) == (True, True)
        assert (third.has_prev, third.has_next) == (True, False)
        assert (first.first_number, second.first_number, third.first_number) == (1, 11, 21)

    async def test_page_is_clamped(self, service: TaskService) -> None:
        await create(service, ALICE, "one", "21.10.2026 10:00")
        assert (await service.get_active_page(ALICE, 99)).page == 1
        assert (await service.get_active_page(ALICE, -5)).page == 1

    async def test_exactly_ten_tasks_is_single_page(self, service: TaskService) -> None:
        for i in range(10):
            await create(service, ALICE, f"t{i}", f"{21 + i}.10.2026 10:00")
        page = await service.get_active_page(ALICE, 1)
        assert (len(page.tasks), page.total_pages, page.has_next) == (10, 1, False)

    async def test_empty(self, service: TaskService) -> None:
        page = await service.get_active_page(ALICE, 1)
        assert (page.total, page.tasks, page.total_pages) == (0, [], 1)

    async def test_users_see_only_their_tasks(self, service: TaskService) -> None:
        await create(service, ALICE, "alice", "21.10.2026 10:00")
        await create(service, BOLAT, "bolat", "21.10.2026 10:00")
        assert [t.title for t in (await service.get_active_page(ALICE)).tasks] == ["alice"]
        assert [t.title for t in (await service.get_active_page(BOLAT)).tasks] == ["bolat"]


class TestToday:
    # «сейчас» — 20.10.2026 12:00 Алматы; сегодня = [20.10 00:00, 21.10 00:00)
    async def test_local_day_boundaries(self, service: TaskService, clock: FakeClock) -> None:
        # Создаём задачи, «перематывая» часы назад, чтобы пройти проверку «в будущем».
        clock.now = NOW - timedelta(days=2)
        await create(service, ALICE, "вчера 23:59", "19.10.2026 23:59")
        await create(service, ALICE, "сегодня 00:00", "20.10.2026 00:00")
        await create(service, ALICE, "сегодня 23:59", "20.10.2026 23:59")
        await create(service, ALICE, "завтра 00:00", "21.10.2026 00:00")
        await create(service, BOLAT, "чужая", "20.10.2026 10:00")
        clock.now = NOW

        today = await service.get_today_page(ALICE)
        assert [t.title for t in today.tasks] == ["сегодня 00:00", "сегодня 23:59"]
        assert today.total == 2

    async def test_completed_tasks_are_excluded(self, service: TaskService) -> None:
        task = await create(service, ALICE, "сегодня", "20.10.2026 23:00")
        await service.complete_task(ALICE, task.id)
        assert (await service.get_today_page(ALICE)).total == 0

    async def test_day_rolls_over_with_clock(self, service: TaskService, clock: FakeClock) -> None:
        await create(service, ALICE, "завтра утром", "21.10.2026 09:00")
        assert (await service.get_today_page(ALICE)).total == 0
        clock.now = NOW + timedelta(hours=13)  # 21.10 01:00 Алматы
        assert (await service.get_today_page(ALICE)).total == 1

    async def test_today_is_paginated(self, service: TaskService) -> None:
        for minute in range(12):
            await create(service, ALICE, f"t{minute}", f"20.10.2026 15:{minute:02d}")
        page = await service.get_today_page(ALICE, 2)
        assert [t.title for t in page.tasks] == ["t10", "t11"]
        assert page.total_pages == 2


class TestComplete:
    async def test_complete_once_then_safe_repeat(
        self, service: TaskService, repo: TaskRepository
    ) -> None:
        task = await create(service, ALICE, "моя", "21.10.2026 10:00")
        done = await service.complete_task(ALICE, task.id)
        assert done is not None and done.id == task.id
        assert await service.complete_task(ALICE, task.id) is None  # повторное нажатие
        assert await repo.list_active(ALICE) == []

    async def test_foreign_and_missing_tasks_are_untouched(
        self, service: TaskService, repo: TaskRepository
    ) -> None:
        task = await create(service, ALICE, "моя", "21.10.2026 10:00")
        assert await service.complete_task(BOLAT, task.id) is None
        assert await service.complete_task(ALICE, 424242) is None
        stored = await repo.get_for_user(task.id, ALICE)
        assert stored is not None and stored.status is TaskStatus.PENDING
        assert stored.completed_at is None
