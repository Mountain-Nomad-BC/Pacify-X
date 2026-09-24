#!/usr/bin/env python3
"""Validate local-model benchmark evidence and emit a certification candidate.

The script is deliberately non-mutating: it never edits runtime-profiles.json.
A passing output is evidence that a separately reviewed profile update may be
admitted; it is not self-promotion by the model or benchmark harness.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import sys
from typing import Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.model_profile import ModelRuntimeProfile, load_runtime_profiles, runtime_profile_from_mapping

MAX_JSON_BYTES = 4 * 1024 * 1024


def _load_object(path: Path) -> dict[str, object]:
    raw = path.read_bytes()
    if len(raw) > MAX_JSON_BYTES:
        raise ValueError(f"JSON evidence exceeds {MAX_JSON_BYTES} bytes: {path}")
    payload = json.loads(raw)
    if type(payload) is not dict:
        raise ValueError(f"JSON evidence must be an object: {path}")
    return payload


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


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


def _number(value: object, field: str, *, minimum: float = 0.0) -> float:
    if type(value) not in (int, float) or type(value) is bool or not math.isfinite(value) or value < minimum:
        raise ValueError(f"{field} must be a finite number >= {minimum}")
    return float(value)


def _integer(value: object, field: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{field} must be a nonnegative integer")
    return value


def _gates(payload: Mapping[str, object]) -> dict[str, object]:
    required = {
        "profile_id", "min_structured_output_validity", "max_p95_latency_ms",
        "max_peak_rss_bytes", "max_peak_vram_bytes", "max_cold_load_ms", "max_warm_load_ms",
        "require_quality_passed", "require_cancellation_recovery", "require_fallback",
    }
    if type(payload) is not dict or set(payload) != required:
        raise ValueError("certification gate fields are incomplete or unsupported")
    profile_id = payload["profile_id"]
    if type(profile_id) is not str or not profile_id.strip() or len(profile_id.encode("utf-8")) > 256:
        raise ValueError("certification gate profile_id is invalid")
    for name in ("require_quality_passed", "require_cancellation_recovery", "require_fallback"):
        if type(payload[name]) is not bool:
            raise ValueError(f"{name} must be boolean")
    _number(payload["min_structured_output_validity"], "min_structured_output_validity")
    if float(payload["min_structured_output_validity"]) > 1:
        raise ValueError("min_structured_output_validity must be <= 1")
    for name in ("max_p95_latency_ms", "max_cold_load_ms", "max_warm_load_ms"):
        _number(payload[name], name)
    for name in ("max_peak_rss_bytes", "max_peak_vram_bytes"):
        _integer(payload[name], name)
    return dict(payload)


def _supplement(receipt: Mapping[str, object]) -> dict[str, object]:
    evidence = receipt.get("quality_evidence")
    if type(evidence) is not dict:
        raise ValueError("benchmark receipt lacks quality/resource supplement evidence")
    required = {
        "fixture_revision", "quality_passed", "structured_output_validity", "peak_rss_bytes",
        "peak_vram_bytes", "cold_load_ms", "warm_load_ms", "cancellation_recovery_passed",
        "fallback_passed",
    }
    missing = sorted(required - set(evidence))
    if missing:
        raise ValueError(f"benchmark supplement is incomplete: {missing}")
    if type(evidence["fixture_revision"]) is not str or not str(evidence["fixture_revision"]).strip():
        raise ValueError("fixture_revision must be nonempty text")
    for name in ("quality_passed", "cancellation_recovery_passed", "fallback_passed"):
        if type(evidence[name]) is not bool:
            raise ValueError(f"{name} must be boolean")
    _number(evidence["structured_output_validity"], "structured_output_validity")
    if float(evidence["structured_output_validity"]) > 1:
        raise ValueError("structured_output_validity must be <= 1")
    for name in ("peak_rss_bytes", "peak_vram_bytes"):
        _integer(evidence[name], name)
    for name in ("cold_load_ms", "warm_load_ms"):
        _number(evidence[name], name)
    return dict(evidence)


def _certified_profile(profile: ModelRuntimeProfile, receipt: Mapping[str, object]) -> dict[str, object]:
    effective = receipt.get("effective_profile")
    if type(effective) is not dict:
        raise ValueError("benchmark receipt lacks effective_profile")
    measured = runtime_profile_from_mapping(effective)
    if measured.profile_id != profile.profile_id or measured.model_id != profile.model_id:
        raise ValueError("effective profile identity does not match the declared profile")
    allowed_measurement_changes = {"threads", "threads_batch", "gpu_layers"}
    declared = profile.identity_payload()
    measured_payload = measured.identity_payload()
    for field, declared_value in declared.items():
        if field in allowed_measurement_changes:
            continue
        if measured_payload[field] != declared_value:
            raise ValueError(f"benchmark receipt changed non-placement profile field: {field}")
    candidate = dict(measured_payload)
    candidate["state"] = "certified"
    candidate["benchmark_required"] = False
    frozen = runtime_profile_from_mapping(candidate)
    return asdict(frozen)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--gates", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve(strict=True)
    receipt_path = Path(args.receipt).resolve(strict=True)
    gate_path = Path(args.gates).resolve(strict=True)
    receipt = _load_object(receipt_path)
    gates = _gates(_load_object(gate_path))
    if receipt.get("schema_version") != "px.local-model-benchmark/1.0":
        raise ValueError("unsupported local-model benchmark receipt schema")
    if receipt.get("promotion_attempted") is not False or receipt.get("auto_download") is not False:
        raise ValueError("benchmark receipt violates the no-promotion/no-download contract")

    profiles = {item.profile_id: item for item in load_runtime_profiles(root)}
    profile_id = receipt.get("profile_id")
    if type(profile_id) is not str or profile_id not in profiles:
        raise ValueError("benchmark receipt references an unknown runtime profile")
    profile = profiles[profile_id]
    if gates["profile_id"] != profile.profile_id:
        raise ValueError("certification gates target a different profile")
    if receipt.get("declared_profile_sha256") != profile.profile_sha256 or receipt.get("profile_sha256") != profile.profile_sha256:
        raise ValueError("benchmark receipt profile digest does not match the current declaration")
    if receipt.get("model_id") != profile.model_id or receipt.get("lane") != profile.lane:
        raise ValueError("benchmark receipt model/lane identity does not match the current profile")

    model_path = Path(str(receipt.get("model_path", ""))).resolve(strict=True)
    runtime_path = Path(str(receipt.get("runtime_path", ""))).resolve(strict=True)
    if _sha_file(model_path) != receipt.get("model_sha256"):
        raise ValueError("benchmarked model artifact changed after measurement")
    if _sha_file(runtime_path) != receipt.get("runtime_sha256"):
        raise ValueError("benchmarked runtime executable changed after measurement")

    performance = receipt.get("performance")
    if type(performance) is not dict:
        raise ValueError("benchmark receipt lacks performance evidence")
    p95 = _number(performance.get("p95_wall_ms"), "p95_wall_ms")
    evidence = _supplement(receipt)

    checks = {
        "quality_passed": (not gates["require_quality_passed"]) or evidence["quality_passed"] is True,
        "structured_output_validity": float(evidence["structured_output_validity"]) >= float(gates["min_structured_output_validity"]),
        "p95_latency_ms": p95 <= float(gates["max_p95_latency_ms"]),
        "peak_rss_bytes": int(evidence["peak_rss_bytes"]) <= int(gates["max_peak_rss_bytes"]),
        "peak_vram_bytes": int(evidence["peak_vram_bytes"]) <= int(gates["max_peak_vram_bytes"]),
        "cold_load_ms": float(evidence["cold_load_ms"]) <= float(gates["max_cold_load_ms"]),
        "warm_load_ms": float(evidence["warm_load_ms"]) <= float(gates["max_warm_load_ms"]),
        "cancellation_recovery": (not gates["require_cancellation_recovery"]) or evidence["cancellation_recovery_passed"] is True,
        "fallback": (not gates["require_fallback"]) or evidence["fallback_passed"] is True,
    }
    passed = all(checks.values())
    certified_profile = _certified_profile(profile, receipt) if passed else None
    output_payload = {
        "schema_version": "px.local-model-profile-certification/1.0",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "profile_id": profile.profile_id,
        "model_id": profile.model_id,
        "model_sha256": receipt["model_sha256"],
        "runtime_sha256": receipt["runtime_sha256"],
        "benchmark_receipt_sha256": _sha_file(receipt_path),
        "gate_document_sha256": _sha_file(gate_path),
        "fixture_revision": evidence["fixture_revision"],
        "checks": checks,
        "passed": passed,
        "certified_profile_candidate": certified_profile,
        "mutated_runtime_profiles": False,
        "promotion_performed": False,
    }
    output = Path(args.output)
    _write_json_atomic(output, output_payload)
    print(json.dumps({"output": str(output), "profile_id": profile.profile_id, "passed": passed}, indent=2))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
