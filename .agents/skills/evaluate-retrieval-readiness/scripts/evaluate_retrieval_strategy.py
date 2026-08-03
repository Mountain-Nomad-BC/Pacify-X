"""Gate a retrieval candidate against exact-reference quality and resource limits."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def evaluate(payload: dict[str, Any]) -> dict[str, Any]:
    cases = payload.get("cases")
    thresholds = payload.get("thresholds")
    metrics = payload.get("metrics")
    state = payload.get("state")
    if not isinstance(cases, list) or not cases or not isinstance(thresholds, dict) or not isinstance(metrics, dict) or not isinstance(state, dict):
        raise ValueError("non-empty cases plus thresholds, metrics, and state objects are required")
    recalls: list[float] = []
    forbidden: set[str] = set()
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            raise ValueError(f"case {index} must be an object")
        exact = {str(value) for value in case.get("exact_ids", ())}
        candidate = [str(value) for value in case.get("candidate_ids", ())]
        denied = {str(value) for value in case.get("forbidden_ids", ())}
        if not exact:
            raise ValueError(f"case {index} exact_ids must not be empty")
        recalls.append(len(exact & set(candidate)) / len(exact))
        forbidden.update(denied & set(candidate))
    mean_recall = sum(recalls) / len(recalls)
    min_recall = float(thresholds.get("min_mean_recall", 1.0))
    max_p95 = float(thresholds.get("max_p95_ms", float("inf")))
    max_memory = float(thresholds.get("max_peak_memory_mib", float("inf")))
    p95 = float(metrics.get("p95_ms", float("inf")))
    memory = float(metrics.get("peak_memory_mib", float("inf")))
    compressed = bool(state.get("compressed", False))
    calibration_valid = (not compressed) or (
        state.get("lifecycle") in {"calibrated", "prepared", "persisted", "loaded"}
        and bool(state.get("calibration_fingerprint"))
        and state.get("calibration_fingerprint") == state.get("current_distribution_fingerprint")
    )
    checks = {
        "recall_floor": mean_recall >= min_recall,
        "forbidden_exposure_zero": not forbidden,
        "p95_budget": p95 <= max_p95,
        "memory_budget": memory <= max_memory,
        "calibration_current": calibration_valid,
    }
    return {
        "schema_version": "1.0", "complete": all(checks.values()), "checks": checks,
        "case_count": len(cases), "mean_recall": round(mean_recall, 6),
        "forbidden_ids_returned": sorted(forbidden), "metrics": {"p95_ms": p95, "peak_memory_mib": memory},
        "state": state,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = evaluate(json.loads(args.input.read_text(encoding="utf-8")))
    encoded = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    raise SystemExit(0 if result["complete"] else 1)
