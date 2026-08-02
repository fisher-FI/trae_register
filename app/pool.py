"""异步任务池:Semaphore 限流 + 状态回调。"""
import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

JobFn = Callable[[int, str], Awaitable[Any]]


class TaskPool:
    def __init__(self, concurrency: int):
        self.concurrency = concurrency
        self._sem = asyncio.Semaphore(concurrency)

    async def submit_batch(self, tasks: list[tuple[int, str]], job: JobFn) -> list[Any]:
        """对每个 (task_id, email) 执行 job(task_id, email);task_id 为数据库任务 ID。"""

        async def _run(task_id: int, email: str):
            async with self._sem:
                return await job(task_id, email)

        return await asyncio.gather(*[_run(tid, email) for tid, email in tasks])
