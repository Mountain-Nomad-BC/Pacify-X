#!/usr/bin/env python3
"""Benchmark a candidate model-route policy against matched incumbent fixtures.

This script is evidence-only.  It never edits routing policy, model state, or
learning state and cannot promote a candidate generation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.archive_io import reject_path_links
from runtime.json_io import bounded_json_text, load_json_object
from runtime.model_routing_observability import RouteOutcome, benchmark_route_outcomes, content_sha256

MAX_INPUT_BYTES = 16 * 1024 * 1024
MAX_OUTPUT_BYTES = 4 * 1024 * 1024


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _outcome(value: object) -> RouteOutcome:
    expected = {
        "fixture_id", "domain", "policy_sha256", "ranking", "primary_model_id",
        "challenger_model_id", "verified_success", "latency_ms", "remote_cost",
        "local_completion", "feature_ids",
    }
    if type(value) is not dict or set(value) != expected:
        raise ValueError("route benchmark outcome fields are incomplete or unsupported")
    if type(value["ranking"]) is not list or type(value["feature_ids"]) is not list:
        raise ValueError("route benchmark ranking/feature_ids must be JSON arrays")
    return RouteOutcome(
        fixture_id=value["fixture_id"], domain=value["domain"], policy_sha256=value["policy_sha256"],
        ranking=tuple(value["ranking"]), primary_model_id=value["primary_model_id"],
        challenger_model_id=value["challenger_model_id"], verified_success=value["verified_success"],
        latency_ms=value["latency_ms"], remote_cost=value["remote_cost"],
        local_completion=value["local_completion"], feature_ids=tuple(value["feature_ids"]),
    )


def benchmark_payload(root: Path, payload: dict[str, object]) -> dict[str, object]:
    expected = {"schema_version", "fixture_sha256", "domain_floors", "materiality", "incumbent", "candidate"}
    if set(payload) != expected or payload["schema_version"] != "px.model-route-benchmark-input/1.0":
        raise ValueError("unsupported model route benchmark input")
    if type(payload["incumbent"]) is not list or type(payload["candidate"]) is not list:
        raise ValueError("benchmark incumbent/candidate records must be arrays")
    benchmark_policy_path = root / "models" / "benchmark-policy.json"
    reject_path_links(benchmark_policy_path)
    policy = load_json_object(benchmark_policy_path, max_bytes=262_144)
    route_policy = policy.get("model_routing")
    if type(route_policy) is not dict:
        raise ValueError("benchmark policy does not contain model_routing controls")
    stability = route_policy.get("route_stability")
    if type(stability) is not dict:
        raise ValueError("benchmark route stability policy is missing")
    floors_policy = route_policy.get("domain_floors")
    if type(floors_policy) is not dict or floors_policy.get("required") is not True:
        raise ValueError("benchmark policy must require domain floors")
    if type(payload["domain_floors"]) is not dict or not payload["domain_floors"]:
        raise ValueError("benchmark input requires declared domain floors")
    complexity = route_policy.get("complexity_tax")
    if type(complexity) is not dict or complexity.get("materiality_source") != "registered_benchmark_manifest":
        raise ValueError("benchmark policy must bind complexity materiality to the fixture manifest")
    receipt = benchmark_route_outcomes(
        tuple(_outcome(row) for row in payload["incumbent"]),
        tuple(_outcome(row) for row in payload["candidate"]),
        fixture_sha256=payload["fixture_sha256"],
        domain_floors=payload["domain_floors"],
        materiality=payload["materiality"],
        max_js_bits=stability["max_jensen_shannon_bits_before_review"],
        min_top1_agreement=stability["minimum_top1_agreement_before_review"],
        min_top3_overlap=stability["minimum_top3_overlap_before_review"],
    )
    body = {
        "schema_version": "px.model-route-benchmark-envelope/1.0",
        "benchmark_policy_sha256": _sha256_file(benchmark_policy_path),
        "route_evidence": receipt,
        "authority_granted": False,
        "auto_promotion_allowed": False,
    }
    return {**body, "envelope_sha256": content_sha256(body)}


def _atomic_write(path: Path, text: str) -> None:
    reject_path_links(path)
    reject_path_links(path.parent)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    except Exception:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    reject_path_links(args.root)
    reject_path_links(args.input)
    reject_path_links(args.output)
    root = args.root.resolve()
    reject_path_links(root)
    payload = load_json_object(args.input, max_bytes=MAX_INPUT_BYTES)
    result = benchmark_payload(root, payload)
    text = bounded_json_text(result, max_bytes=MAX_OUTPUT_BYTES) + "\n"
    _atomic_write(args.output, text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
