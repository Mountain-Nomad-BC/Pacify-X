#!/usr/bin/env python3
"""Bounded local-model/profile benchmark receipt generator.

This script never downloads models, promotes profiles, starts background services,
or edits PX policy.  It benchmarks one already-present GGUF against one declared
runtime profile and writes evidence for later certification.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import os
import statistics
import subprocess
import sys
import tempfile
import time
from typing import Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.hardware_routing import hardware_report
from runtime.model_profile import load_runtime_profiles

MAX_CAPTURE_BYTES = 8 * 1024 * 1024


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _bounded_file(value: str, *, executable: bool = False, suffix: str | None = None) -> Path:
    path = Path(value).expanduser().resolve(strict=True)
    if not path.is_file():
        raise ValueError(f"benchmark input is not an admitted regular file: {path}")
    if suffix is not None and path.suffix.casefold() != suffix.casefold():
        raise ValueError(f"benchmark input must end in {suffix}: {path}")
    if executable and path.stat().st_size <= 0:
        raise ValueError("benchmark executable is empty")
    return path


def _write_json_atomic(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _bench_supports_threads_batch(bench: Path) -> bool:
    """True only when the exact llama-bench binary still exposes -tb.

    The batch-thread flag was removed in newer llama.cpp releases; probing the binary
    keeps one benchmark owner working across pinned builds without assuming a version.
    """
    try:
        result = subprocess.run(
            [str(bench), "--help"], capture_output=True, timeout=30, shell=False
        )
    except (OSError, subprocess.SubprocessError):
        return False
    text = (result.stdout + result.stderr).decode("utf-8", errors="replace")
    return "-tb" in text


def _run_bounded(command: list[str], *, timeout_seconds: float) -> tuple[int, bytes, bytes, float]:
    started = time.perf_counter()
    with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
        process = subprocess.Popen(command, stdout=stdout_file, stderr=stderr_file, shell=False)
        deadline = time.monotonic() + timeout_seconds
        try:
            while process.poll() is None:
                if time.monotonic() >= deadline:
                    process.kill()
                    process.wait(timeout=5)
                    raise subprocess.TimeoutExpired(command, timeout_seconds)
                if os.fstat(stdout_file.fileno()).st_size > MAX_CAPTURE_BYTES or os.fstat(stderr_file.fileno()).st_size > MAX_CAPTURE_BYTES:
                    process.kill()
                    process.wait(timeout=5)
                    raise RuntimeError("llama-bench output exceeded the bounded capture contract")
                time.sleep(0.02)
            if os.fstat(stdout_file.fileno()).st_size > MAX_CAPTURE_BYTES or os.fstat(stderr_file.fileno()).st_size > MAX_CAPTURE_BYTES:
                raise RuntimeError("llama-bench output exceeded the bounded capture contract")
            stdout_file.seek(0)
            stderr_file.seek(0)
            stdout = stdout_file.read(MAX_CAPTURE_BYTES + 1)
            stderr = stderr_file.read(MAX_CAPTURE_BYTES + 1)
            return int(process.returncode), stdout, stderr, (time.perf_counter() - started) * 1000.0
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(fraction * len(ordered)) - 1))
    return ordered[index]


def _extract_throughput(payload: object) -> tuple[float, ...]:
    rows: list[Mapping[str, object]] = []
    if type(payload) is list:
        rows = [item for item in payload if type(item) is dict]
    elif type(payload) is dict:
        candidate = payload.get("results")
        if type(candidate) is list:
            rows = [item for item in candidate if type(item) is dict]
        else:
            rows = [payload]
    values: list[float] = []
    for row in rows:
        value = row.get("avg_ts")
        if type(value) in (int, float) and type(value) is not bool and math.isfinite(value) and value >= 0:
            values.append(float(value))
    return tuple(values)


def _load_supplement(path: Path | None) -> dict[str, object]:
    if path is None:
        return {}
    raw = path.read_bytes()
    if len(raw) > 1_048_576:
        raise ValueError("supplement evidence exceeds 1 MiB")
    payload = json.loads(raw)
    if type(payload) is not dict:
        raise ValueError("supplement evidence must be a JSON object")
    allowed = {
        "fixture_revision", "quality_passed", "structured_output_validity", "peak_rss_bytes",
        "peak_vram_bytes", "cold_load_ms", "warm_load_ms", "cancellation_recovery_passed",
        "fallback_passed", "notes",
    }
    if set(payload) - allowed:
        raise ValueError("supplement evidence contains unsupported fields")
    for name in ("quality_passed", "cancellation_recovery_passed", "fallback_passed"):
        if name in payload and type(payload[name]) is not bool:
            raise ValueError(f"supplement {name} must be boolean")
    if "fixture_revision" in payload and (type(payload["fixture_revision"]) is not str or not payload["fixture_revision"].strip() or len(payload["fixture_revision"].encode("utf-8")) > 256):
        raise ValueError("supplement fixture_revision must be bounded nonempty text")
    if "structured_output_validity" in payload:
        value = payload["structured_output_validity"]
        if type(value) not in (int, float) or type(value) is bool or not math.isfinite(value) or not 0 <= float(value) <= 1:
            raise ValueError("supplement structured_output_validity must be in [0, 1]")
    for name in ("peak_rss_bytes", "peak_vram_bytes"):
        if name in payload and (type(payload[name]) is not int or not 0 <= payload[name] <= 2**63 - 1):
            raise ValueError(f"supplement {name} must be a bounded nonnegative integer")
    for name in ("cold_load_ms", "warm_load_ms"):
        if name in payload:
            value = payload[name]
            if type(value) not in (int, float) or type(value) is bool or not math.isfinite(value) or value < 0:
                raise ValueError(f"supplement {name} must be a finite nonnegative number")
    if "notes" in payload and (type(payload["notes"]) is not str or len(payload["notes"].encode("utf-8")) > 4096):
        raise ValueError("supplement notes must be bounded text")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--profile", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--llama-bench", required=True)
    parser.add_argument("--threads", type=int)
    parser.add_argument("--threads-batch", type=int)
    parser.add_argument("--gpu-layers", type=int)
    parser.add_argument("--prompt-tokens", type=int, default=128)
    parser.add_argument("--generate-tokens", type=int, default=64)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--timeout-seconds", type=float, default=300.0)
    parser.add_argument("--supplement-json")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve(strict=True)
    profiles = {item.profile_id: item for item in load_runtime_profiles(root)}
    if args.profile not in profiles:
        raise SystemExit(f"unknown runtime profile: {args.profile}")
    profile = profiles[args.profile]
    model = _bounded_file(args.model, suffix=".gguf")
    bench = _bounded_file(args.llama_bench, executable=True)
    if not 1 <= args.prompt_tokens <= profile.context_tokens:
        raise ValueError("prompt token count exceeds the declared profile context")
    if not 1 <= args.generate_tokens <= profile.max_output_tokens:
        raise ValueError("generation token count exceeds the declared profile output bound")
    if not 1 <= args.repeats <= 20:
        raise ValueError("benchmark repeats must be in [1, 20]")
    if not 1 <= args.timeout_seconds <= 3600:
        raise ValueError("benchmark timeout must be in [1, 3600]")

    threads = profile.threads if args.threads is None else args.threads
    threads_batch = profile.threads_batch if args.threads_batch is None else args.threads_batch
    gpu_layers = profile.gpu_layers if args.gpu_layers is None else args.gpu_layers
    if threads is None or threads_batch is None or gpu_layers is None:
        raise ValueError("candidate profile has unfrozen placement; provide --threads, --threads-batch, and --gpu-layers")
    if not 1 <= threads <= 1024 or not 1 <= threads_batch <= 1024 or not 0 <= gpu_layers <= 100_000:
        raise ValueError("effective benchmark placement is outside bounded limits")
    if profile.lane == "control" and gpu_layers != 0:
        raise ValueError("control-lane benchmarks must remain CPU-only")

    model_before = _sha_file(model)
    bench_before = _sha_file(bench)
    command = [
        str(bench), "-m", str(model), "-ngl", str(gpu_layers), "-t", str(threads),
    ]
    # Older llama.cpp releases expose a separate batch-thread count (-tb); newer builds
    # removed it. Probe the exact binary instead of assuming one release's flags.
    if _bench_supports_threads_batch(bench):
        command += ["-tb", str(threads_batch)]
    command += ["-p", str(args.prompt_tokens), "-n", str(args.generate_tokens), "-r", "1", "-o", "json"]
    durations: list[float] = []
    throughput: list[float] = []
    raw_runs: list[dict[str, object]] = []
    for run_index in range(args.repeats):
        returncode, stdout, stderr, duration_ms = _run_bounded(command, timeout_seconds=float(args.timeout_seconds))
        if returncode != 0:
            stderr_text = stderr.decode("utf-8", errors="replace").strip()
            detail = stderr_text.splitlines()[-1] if stderr_text else f"exit {returncode}"
            raise RuntimeError(f"llama-bench failed: {detail}")
        try:
            payload = json.loads(stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RuntimeError("llama-bench did not return valid UTF-8 JSON") from error
        values = _extract_throughput(payload)
        if not values:
            raise RuntimeError("llama-bench result did not contain bounded avg_ts throughput evidence")
        durations.append(duration_ms)
        throughput.extend(values)
        raw_runs.append({"run": run_index + 1, "duration_ms": round(duration_ms, 6), "avg_ts": list(values)})

    if _sha_file(model) != model_before or _sha_file(bench) != bench_before:
        raise RuntimeError("model or llama-bench executable changed during benchmark")

    supplement = _load_supplement(Path(args.supplement_json).resolve(strict=True) if args.supplement_json else None)
    hardware = hardware_report(probe_external=True, probe_libraries=False, timeout_seconds=min(2.0, args.timeout_seconds))
    effective_profile = {**asdict(profile), "threads": threads, "threads_batch": threads_batch, "gpu_layers": gpu_layers}
    effective_profile.pop("profile_sha256", None)
    receipt = {
        "schema_version": "px.local-model-benchmark/1.0",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "profile_id": profile.profile_id,
        "model_id": profile.model_id,
        "lane": profile.lane,
        "model_path": str(model),
        "model_sha256": model_before,
        "runtime_path": str(bench),
        "runtime_sha256": bench_before,
        "declared_profile_sha256": profile.profile_sha256,
        "profile_sha256": profile.profile_sha256,
        "effective_profile": effective_profile,
        "machine_fingerprint": hardware["hardware_fingerprint"],
        "hardware": hardware["hardware"],
        "prompt_tokens": args.prompt_tokens,
        "generate_tokens": args.generate_tokens,
        "runs": raw_runs,
        "performance": {
            "p50_wall_ms": statistics.median(durations),
            "p95_wall_ms": _percentile(durations, 0.95),
            "mean_tokens_per_second": statistics.mean(throughput),
            "min_tokens_per_second": min(throughput),
        },
        "quality_evidence": supplement,
        "fixture_revision": supplement.get("fixture_revision"),
        "quality_passed": supplement.get("quality_passed"),
        "structured_output_validity": supplement.get("structured_output_validity"),
        "p50_latency_ms": statistics.median(durations),
        "p95_latency_ms": _percentile(durations, 0.95),
        "peak_rss_bytes": supplement.get("peak_rss_bytes"),
        "peak_vram_bytes": supplement.get("peak_vram_bytes"),
        "cold_load_ms": supplement.get("cold_load_ms"),
        "warm_load_ms": supplement.get("warm_load_ms"),
        "cancellation_recovery_passed": supplement.get("cancellation_recovery_passed"),
        "fallback_passed": supplement.get("fallback_passed"),
        "promotion_attempted": False,
        "auto_download": False
    }
    output = Path(args.output)
    _write_json_atomic(output, receipt)
    print(json.dumps({"output": str(output), "profile_id": profile.profile_id, "model_sha256": model_before, "p95_wall_ms": receipt["performance"]["p95_wall_ms"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
