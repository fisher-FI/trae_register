import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app.pool import TaskPool


@pytest.mark.asyncio
async def test_pool_limits_concurrency():
    running = 0
    max_running = 0

    async def fake_job(task_id, email):
        nonlocal running, max_running
        running += 1
        max_running = max(max_running, running)
        await asyncio.sleep(0.05)
        running -= 1

    pool = TaskPool(concurrency=3)
    await pool.submit_batch(
        tasks=[(i + 1, f"u{i}@b.com") for i in range(9)],
        job=fake_job,
    )
    assert max_running <= 3


@pytest.mark.asyncio
async def test_pool_tracks_results():
    async def fake_job(task_id, email):
        return "ok"

    pool = TaskPool(concurrency=2)
    results = await pool.submit_batch(
        tasks=[(1, "a@b.com"), (2, "c@d.com")],
        job=fake_job,
    )
    assert len(results) == 2
    assert all(r == "ok" for r in results)
