"""异步任务池:Semaphore 限流 + 状态回调。"""
import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

JobFn = Callable[[int, str], Awaitable[Any]]


class TaskPool:
    def __init__(self, concurrency: int):
        self.concurrency = concurrency
        self._sem = asyncio.Semaphore(concurrency)

    async def submit_batch(self, emails: list[str], job: JobFn,
                           engine: Any = None) -> list[Any]:
        """对每个 email 执行 job(task_id, email);job 内部自行处理 engine。"""

        async def _run(task_id: int, email: str):
            async with self._sem:
                return await job(task_id, email)

        return await asyncio.gather(
            *[_run(i + 1, email) for i, email in enumerate(emails)]
        )
