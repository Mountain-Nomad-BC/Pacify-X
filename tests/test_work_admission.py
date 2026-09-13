from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
import time

import pytest

from runtime.work_admission import RuntimeWorkPlane, content_hash


def test_runtime_work_plane_coalesces_and_publishes_causal_delta(tmp_path: Path) -> None:
    plane = RuntimeWorkPlane(tmp_path)
    entered = Event()
    release = Event()
    executions = 0

    def producer():
        nonlocal executions
        executions += 1
        entered.set()
        release.wait(2)
        return {"value": 7}

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            plane.execute,
            "inventory",
            producer,
            reason="explicit refresh",
            input_fingerprint={"revision": 1},
            domains=("skills",),
            lane="heavy",
            timeout_seconds=3,
        )
        assert entered.wait(1)
        second = pool.submit(
            plane.execute,
            "inventory",
            producer,
            reason="second consumer",
            input_fingerprint={"revision": 1},
            domains=("skills",),
            lane="heavy",
            timeout_seconds=3,
        )
        time.sleep(0.1)
        release.set()
        one, two = first.result(), second.result()

    assert executions == 1
    assert {one["admission"]["decision"], two["admission"]["decision"]} == {
        "ran",
        "joined",
    }
    state = plane.snapshot()
    assert state["bus_revision"] == 1
    assert state["domain_revisions"] == {"skills": 1}
    assert state["counters"]["duplicate_executions_avoided"] == 1
    assert not state["active"]


def test_stable_idle_snapshot_is_read_only_and_cached_work_is_quiet(tmp_path: Path) -> None:
    plane = RuntimeWorkPlane(tmp_path)
    first = plane.execute(
        "sensor",
        lambda: {"cpu": 1},
        reason="visible runtime panel",
        input_fingerprint="hardware-v1",
        domains=("hardware",),
        cache_seconds=60,
    )
    state_path = tmp_path / ".engineering-bootstrap/runtime-core/state.json"
    before = state_path.read_bytes()
    second = plane.execute(
        "sensor",
        lambda: {"cpu": 2},
        reason="visible runtime panel",
        input_fingerprint="hardware-v1",
        domains=("hardware",),
        cache_seconds=60,
    )
    plane.snapshot()
    plane.snapshot()
    assert first["admission"]["decision"] == "ran"
    assert second["admission"]["decision"] == "cache_hit"
    assert state_path.read_bytes() == before


def test_corrupt_cache_is_rejected_and_rebuilt(tmp_path: Path) -> None:
    plane = RuntimeWorkPlane(tmp_path)
    operation = "sensor"
    key = __import__("hashlib").sha256(operation.encode("utf-8")).hexdigest()[:24]
    cache_path = tmp_path / ".engineering-bootstrap/runtime-core/cache" / f"{key}.json"
    cache_path.parent.mkdir(parents=True)
    cache_path.write_text("{not-json", encoding="utf-8")

    result = plane.execute(
        operation,
        lambda: {"cpu": 3},
        reason="visible runtime panel",
        input_fingerprint="hardware-v1",
        domains=("hardware",),
        cache_seconds=60,
    )

    assert result["admission"]["decision"] == "ran"
    assert result["result"] == {"cpu": 3}


def test_tampered_cache_result_and_invalid_creation_times_are_rebuilt(
    tmp_path: Path,
) -> None:
    plane = RuntimeWorkPlane(tmp_path)
    calls = 0

    def producer() -> dict[str, int]:
        nonlocal calls
        calls += 1
        return {"cpu": calls}

    first = plane.execute(
        "sensor",
        producer,
        reason="visible runtime panel",
        input_fingerprint="hardware-v1",
        domains=("hardware",),
        cache_seconds=60,
    )
    assert first["result"] == {"cpu": 1}
    key = __import__("hashlib").sha256(b"sensor").hexdigest()[:24]
    cache_path = tmp_path / ".engineering-bootstrap/runtime-core/cache" / f"{key}.json"
    cached = __import__("json").loads(cache_path.read_text(encoding="utf-8"))
    cached["result"] = {"cpu": 999}
    cache_path.write_text(__import__("json").dumps(cached), encoding="utf-8")
    second = plane.execute(
        "sensor",
        producer,
        reason="visible runtime panel",
        input_fingerprint="hardware-v1",
        domains=("hardware",),
        cache_seconds=60,
    )
    assert second["result"] == {"cpu": 2}
    assert second["admission"]["decision"] == "ran"

    for invalid in (True, "1", 0, -1, float("inf"), float("nan")):
        payload = {
            **cached,
            "created_epoch": invalid,
            "result": {"cpu": 2},
            "result_sha256": content_hash({"cpu": 2}),
        }
        cache_path.write_text(__import__("json").dumps(payload), encoding="utf-8")
        assert plane._read_cache(cache_path) is None


def test_owned_vscode_host_can_isolate_its_runtime_work_plane(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    isolated = tmp_path / "installed-host-runtime"
    monkeypatch.setattr(
        "runtime.work_admission.tempfile.gettempdir", lambda: str(tmp_path)
    )
    monkeypatch.setenv("PX_OWNED_VSCODE_HOST", "1")
    monkeypatch.setenv("PX_OWNED_RUNTIME_WORK_PLANE_ROOT", str(isolated))

    plane = RuntimeWorkPlane(tmp_path / "engine")
    result = plane.execute(
        "sensor",
        lambda: {"isolated": True},
        reason="parallel installed-host proof",
        input_fingerprint="owned-host",
        domains=("runtime",),
    )

    assert plane.plane == isolated.resolve()
    assert result["result"] == {"isolated": True}
    assert (isolated / "state.json").is_file()
    assert not (tmp_path / "engine/.engineering-bootstrap/runtime-core").exists()


def test_runtime_work_plane_override_rejects_unowned_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PX_OWNED_VSCODE_HOST", raising=False)
    monkeypatch.setenv("PX_OWNED_RUNTIME_WORK_PLANE_ROOT", str(tmp_path / "runtime"))

    with pytest.raises(ValueError, match="owned VS Code host"):
        RuntimeWorkPlane(tmp_path / "engine")
