"""Repeatable live-size benchmark for the operational ledger custody path."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import shutil
import tempfile
import threading
import time
from typing import Callable

from runtime import operational_gap_ledger as ledger
from runtime.file_lock import FileLock, FileLockTimeout


BUDGETS = {
    "append_p95_seconds": 8.0,
    "read_head_p95_seconds": 0.5,
    "read_snapshot_p95_seconds": 5.0,
    "decode_verify_seconds": 20.0,
    "peak_rss_bytes": 768 * 1024 * 1024,
    "projection_rewrite_bytes_per_append": 1024 * 1024,
    "recovery_seconds": 20.0,
    "lock_rejection_seconds": 1.0,
    "rebuild_seconds": 30.0,
}


def _percentile(samples: list[float], percentile: float) -> float:
    values = sorted(samples)
    rank = max(0, min(len(values) - 1, int((len(values) - 1) * percentile + 0.999999)))
    return values[rank]


def _summary(samples: list[float]) -> dict[str, object]:
    return {
        "raw_seconds": samples,
        "p50_seconds": _percentile(samples, 0.50),
        "p95_seconds": _percentile(samples, 0.95),
        "p99_seconds": _percentile(samples, 0.99),
    }


def _timed(function: Callable[[], object]) -> tuple[float, object]:
    started = time.perf_counter()
    result = function()
    return time.perf_counter() - started, result


def _peak_rss_during(function: Callable[[], object]) -> tuple[float, int, object]:
    try:
        import psutil
    except ImportError:
        elapsed, result = _timed(function)
        return elapsed, 0, result
    process = psutil.Process()
    stop = threading.Event()
    samples: list[int] = []

    def sample() -> None:
        while not stop.wait(0.01):
            samples.append(process.memory_info().rss)

    worker = threading.Thread(target=sample, daemon=True)
    worker.start()
    try:
        elapsed, result = _timed(function)
    finally:
        stop.set()
        worker.join(timeout=1)
    samples.append(process.memory_info().rss)
    return elapsed, max(samples), result


def _copy_live_registry(source: Path, destination: Path) -> None:
    target = destination / "registry"
    target.mkdir(parents=True)
    for name in (
        "operational_gap_ledger.jsonl",
        "operational_gap_ledger.snapshot.json",
        "operational_gap_ledger.head.json",
    ):
        shutil.copy2(source / "registry" / name, target / name)


def _annotation(root: Path, gap_id: str, ordinal: int) -> None:
    ledger.append_event(
        root,
        "card_annotated",
        {
            "gap_id": gap_id,
            "note": f"Disposable live-size benchmark sample {ordinal}.",
            "evidence": [
                {
                    "reference": "benchmark:disposable-live-size",
                    "claim": "Disposable append latency sample; never retained as feature evidence.",
                }
            ],
            "patch": {},
        },
        actor="ledger-benchmark",
    )


def benchmark_ledger(root: Path, *, append_samples: int = 3) -> dict[str, object]:
    """Benchmark a single disposable live-size copy and retain raw measurements."""
    root = root.resolve(strict=True)
    if append_samples < 3 or append_samples > 20:
        raise ValueError("append_samples must be between 3 and 20")
    source_head = ledger.read_head(root)
    with tempfile.TemporaryDirectory(prefix="px-ledger-benchmark-") as directory:
        benchmark_root = Path(directory)
        _copy_live_registry(root, benchmark_root)
        source_sizes = {
            "ledger_bytes": (benchmark_root / ledger.LEDGER_RELATIVE).stat().st_size,
            "snapshot_bytes": (benchmark_root / ledger.SNAPSHOT_RELATIVE).stat().st_size,
            "head_bytes": (benchmark_root / ledger.HEAD_RELATIVE).stat().st_size,
        }
        print("ledger benchmark: cold decode/verify", flush=True)
        ledger._LEDGER_DIGEST_CACHE.clear()
        decode_seconds, peak_rss, validation = _peak_rss_during(
            lambda: ledger.validate(benchmark_root)
        )
        if not validation.get("valid"):
            raise RuntimeError("disposable live ledger did not validate")

        print("ledger benchmark: bounded reads", flush=True)
        head_samples = [_timed(lambda: ledger.read_head(benchmark_root))[0] for _ in range(5)]
        snapshot_samples = [_timed(lambda: ledger.read_snapshot(benchmark_root))[0] for _ in range(3)]
        current = ledger.read_snapshot(benchmark_root)
        gap_id = "PX-OS-1067" if "PX-OS-1067" in current["cards"] else sorted(current["cards"])[0]

        print("ledger benchmark: delta append samples", flush=True)
        snapshot_path = benchmark_root / ledger.SNAPSHOT_RELATIVE
        snapshot_before = snapshot_path.read_bytes()
        append_times: list[float] = []
        ledger_before = (benchmark_root / ledger.LEDGER_RELATIVE).stat().st_size
        for ordinal in range(append_samples):
            elapsed, _ = _timed(lambda ordinal=ordinal: _annotation(benchmark_root, gap_id, ordinal))
            append_times.append(elapsed)
        ledger_after = (benchmark_root / ledger.LEDGER_RELATIVE).stat().st_size
        snapshot_after = snapshot_path.read_bytes()
        delta_files = list((benchmark_root / ledger.DELTA_DIRECTORY_RELATIVE).glob("*.jsonl"))
        latest_delta_bytes = max((item.stat().st_size for item in delta_files), default=0)
        head_after_bytes = (benchmark_root / ledger.HEAD_RELATIVE).stat().st_size
        projection_rewrite_bytes = 0 if snapshot_before == snapshot_after else len(snapshot_after)

        print("ledger benchmark: lock and concurrent writers", flush=True)
        lock_path = benchmark_root / ledger.LOCK_RELATIVE
        lock_started = time.perf_counter()
        lock_rejected = False
        with FileLock(lock_path, timeout_seconds=1.0):
            try:
                with FileLock(lock_path, timeout_seconds=0.05):
                    pass
            except (FileLockTimeout, OSError):
                lock_rejected = True
        lock_seconds = time.perf_counter() - lock_started
        before_concurrent = len(ledger.read_events(benchmark_root))
        concurrent_started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda ordinal: _annotation(benchmark_root, gap_id, 100 + ordinal), range(4)))
        concurrent_seconds = time.perf_counter() - concurrent_started
        concurrent_events = ledger.read_events(benchmark_root)
        concurrent_ok = (
            len(concurrent_events) == before_concurrent + 4
            and [item["sequence"] for item in concurrent_events] == list(range(1, len(concurrent_events) + 1))
        )

        print("ledger benchmark: torn-tail recovery", flush=True)
        ledger_path = benchmark_root / ledger.LEDGER_RELATIVE
        with ledger_path.open("r+b") as handle:
            handle.seek(-1, os.SEEK_END)
            if handle.read(1) != b"\n":
                raise RuntimeError("benchmark ledger did not end in a record delimiter")
            handle.truncate(handle.tell() - 1)
        recovery_seconds, _ = _timed(lambda: _annotation(benchmark_root, gap_id, 999))
        recovered = ledger.validate(benchmark_root)

        print("ledger benchmark: full projection rebuild", flush=True)
        rebuild_seconds, rebuilt = _timed(lambda: ledger.write_snapshot(benchmark_root))
        rebuilt_ok = rebuilt["event_count"] == len(ledger.read_events(benchmark_root))

        metrics = {
            "append": _summary(append_times),
            "read_head": _summary(head_samples),
            "read_snapshot": _summary(snapshot_samples),
            "decode_verify_seconds": decode_seconds,
            "peak_rss_bytes": peak_rss,
            "projection_rewrite_bytes_per_append": projection_rewrite_bytes,
            "append_ledger_bytes_total": ledger_after - ledger_before,
            "latest_delta_projection_bytes": latest_delta_bytes,
            "head_publication_bytes": head_after_bytes,
            "verified_read_bytes": source_sizes["ledger_bytes"],
            "lock_rejection_seconds": lock_seconds,
            "lock_rejected": lock_rejected,
            "concurrent_writer_seconds": concurrent_seconds,
            "concurrent_writers": 4,
            "concurrent_chain_valid": concurrent_ok,
            "recovery_seconds": recovery_seconds,
            "recovery_valid": bool(recovered.get("valid")),
            "rebuild_seconds": rebuild_seconds,
            "rebuild_valid": rebuilt_ok,
        }
        budget_results = {
            "append_p95_seconds": metrics["append"]["p95_seconds"] <= BUDGETS["append_p95_seconds"],
            "read_head_p95_seconds": metrics["read_head"]["p95_seconds"] <= BUDGETS["read_head_p95_seconds"],
            "read_snapshot_p95_seconds": metrics["read_snapshot"]["p95_seconds"] <= BUDGETS["read_snapshot_p95_seconds"],
            "decode_verify_seconds": decode_seconds <= BUDGETS["decode_verify_seconds"],
            "peak_rss_bytes": peak_rss == 0 or peak_rss <= BUDGETS["peak_rss_bytes"],
            "projection_rewrite_bytes_per_append": projection_rewrite_bytes <= BUDGETS["projection_rewrite_bytes_per_append"],
            "recovery_seconds": recovery_seconds <= BUDGETS["recovery_seconds"] and bool(recovered.get("valid")),
            "lock_rejection_seconds": lock_seconds <= BUDGETS["lock_rejection_seconds"] and lock_rejected,
            "concurrent_writers": concurrent_ok,
            "rebuild_seconds": rebuild_seconds <= BUDGETS["rebuild_seconds"] and rebuilt_ok,
        }
        body = {
            "schema_version": "px.operational-gap-ledger-benchmark/1.0",
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "environment": {
                "platform": platform.platform(),
                "python": platform.python_version(),
                "processor": platform.processor(),
                "cpu_count": os.cpu_count(),
            },
            "source_identity": {
                "ledger_id": source_head.get("ledger_id"),
                "event_count": source_head.get("event_count"),
                "head_event_sha256": source_head.get("head_event_sha256"),
                "ledger_sha256": source_head.get("ledger_fingerprint", {}).get("sha256"),
                **source_sizes,
            },
            "method": {
                "live_size_disposable_copy": True,
                "warm_samples_disclosed": True,
                "failed_samples_dropped": False,
                "append_sample_count": append_samples,
                "certification_attribution": "testing-governance:operational-gap-ledger",
            },
            "budgets": BUDGETS,
            "metrics": metrics,
            "budget_results": budget_results,
            "valid": all(budget_results.values()),
            "custody_guarantees_changed": False,
        }
        return body


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    parser.add_argument("--append-samples", type=int, default=3)
    args = parser.parse_args()
    report = benchmark_ledger(args.root, append_samples=args.append_samples)
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        output = args.output if args.output.is_absolute() else args.root / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
