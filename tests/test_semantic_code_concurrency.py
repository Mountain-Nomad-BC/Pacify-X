from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Lock
import time

from runtime.semantic_code_concurrency import ProjectLockPool, SingleFlight


def test_singleflight_executes_identical_work_once():
    flight: SingleFlight[int] = SingleFlight()
    guard = Lock()
    calls = 0

    def work() -> int:
        nonlocal calls
        with guard:
            calls += 1
        time.sleep(0.03)
        return 7

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(flight.call, "same", work) for _ in range(8)]
    assert [item.result() for item in futures] == [7] * 8
    assert calls == 1


def test_project_lock_pool_reuses_identity_lock():
    pool = ProjectLockPool()
    assert pool.get("p") is pool.get("p")
