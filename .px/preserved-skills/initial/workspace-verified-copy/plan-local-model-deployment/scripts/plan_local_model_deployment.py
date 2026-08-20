"""Produce a deterministic, non-executing local-model feasibility matrix."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _number(
    container: dict[str, Any], key: str, *, required: bool = True
) -> float | None:
    value = container.get(key)
    if value is None and not required:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ValueError(f"{key} must be a non-negative number")
    return float(value)


def plan(inventory: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(inventory, dict):
        raise ValueError("inventory must be an object")
    hardware = inventory.get("hardware")
    model = inventory.get("model")
    workload = inventory.get("workload")
    if not all(isinstance(value, dict) for value in (hardware, model, workload)):
        raise ValueError("hardware, model, and workload objects are required")
    ram = _number(hardware, "available_ram_gib")
    vram = _number(hardware, "available_vram_gib")
    disk = _number(hardware, "free_disk_gib")
    disk_read = _number(hardware, "sustained_disk_read_mib_s", required=False)
    weights = _number(model, "weight_gib")
    transformed = _number(model, "transformed_weight_gib", required=False) or weights
    kv = _number(workload, "kv_cache_gib", required=False) or 0.0
    privacy_required = bool(workload.get("privacy_required", False))
    remote_allowed = bool(workload.get("remote_fallback_allowed", False))
    architecture_supported = bool(model.get("architecture_supported", False))
    streaming_supported = bool(model.get("streaming_supported", False))
    required_disk = weights + transformed + max(weights, transformed)
    artifact_budget = {
        "source_gib": weights,
        "transformed_gib": transformed,
        "temporary_and_rollback_gib": max(weights, transformed),
        "minimum_free_disk_gib": required_disk,
        "disk_preflight_passed": disk >= required_disk,
    }
    strategies: list[dict[str, Any]] = []

    def add(
        strategy: str,
        status: str,
        score: float,
        reasons: list[str],
        validations: list[str],
    ) -> None:
        strategies.append(
            {
                "strategy": strategy,
                "status": status,
                "score": round(score, 3),
                "reasons": reasons,
                "required_validations": validations,
            }
        )

    native_fit = architecture_supported and weights + kv <= vram * 0.85
    add(
        "native-accelerator",
        "feasible" if native_fit else "infeasible",
        100 if native_fit else 0,
        [
            "architecture adapter is supported"
            if architecture_supported
            else "architecture adapter is unverified",
            f"weights plus KV require {weights + kv:.3f} GiB against {vram:.3f} GiB available VRAM",
        ],
        ["runtime compatibility", "peak VRAM", "task quality", "cold/warm latency"],
    )
    combined_fit = architecture_supported and weights + kv <= vram * 0.9 + ram * 0.65
    add(
        "cpu-gpu-offload",
        "conditional" if combined_fit else "infeasible",
        75 if combined_fit else 0,
        [
            f"combined bounded memory budget is {vram * 0.9 + ram * 0.65:.3f} GiB",
            "transfer bandwidth and placement must be measured",
        ],
        ["placement trace", "host-to-device bandwidth", "peak RAM/VRAM", "throughput"],
    )
    quantized_sizes = model.get("quantized_weight_gib", {})
    if not isinstance(quantized_sizes, dict):
        raise ValueError("quantized_weight_gib must be an object when supplied")
    for label, raw_size in sorted(quantized_sizes.items()):
        if (
            isinstance(raw_size, bool)
            or not isinstance(raw_size, (int, float))
            or raw_size <= 0
        ):
            raise ValueError(f"quantized_weight_gib.{label} must be positive")
        size = float(raw_size)
        fit = architecture_supported and size + kv <= vram * 0.85
        add(
            f"quantized-{label}",
            "conditional" if fit else "infeasible",
            85 if fit else 0,
            [
                f"estimated quantized weights plus KV require {size + kv:.3f} GiB",
                "quality evidence is not inferred from storage reduction",
            ],
            [
                "representative task-quality baseline",
                "kernel/runtime compatibility",
                "peak VRAM",
                "serialized artifact integrity",
            ],
        )
    streaming_fit = (
        architecture_supported
        and streaming_supported
        and artifact_budget["disk_preflight_passed"]
        and bool(disk_read)
    )
    streaming_rate = (
        (disk_read / (weights * 1024)) if streaming_fit and weights else None
    )
    add(
        "layer-or-expert-streaming",
        "conditional" if streaming_fit else "infeasible",
        55 if streaming_fit else 0,
        [
            "streaming adapter is declared"
            if streaming_supported
            else "streaming adapter is unavailable",
            f"artifact disk preflight requires {required_disk:.3f} GiB",
            f"storage-only upper bound is {streaming_rate:.4f} model passes/s"
            if streaming_rate is not None
            else "sustained storage bandwidth is unknown",
        ],
        [
            "transformation fingerprint",
            "resumability",
            "bounded prefetch memory",
            "storage traffic",
            "tokens/s",
            "recovery",
        ],
    )
    add(
        "smaller-model-or-retrieval-augmentation",
        "conditional",
        65,
        [
            "requires task-level quality comparison",
            "retrieval must preserve authorization and grounding",
        ],
        [
            "task quality",
            "retrieval recall and precision",
            "policy filtering",
            "latency",
        ],
    )
    remote_status = (
        "conditional" if remote_allowed and not privacy_required else "forbidden"
    )
    add(
        "remote-fallback",
        remote_status,
        35 if remote_status == "conditional" else 0,
        [
            "caller allows remote fallback"
            if remote_allowed
            else "remote fallback is not allowed",
            "privacy policy allows remote processing"
            if not privacy_required
            else "privacy requires local execution",
        ],
        ["data classification", "provider policy", "cost/latency", "explicit approval"],
    )
    order = {"feasible": 0, "conditional": 1, "infeasible": 2, "forbidden": 3}
    strategies.sort(
        key=lambda item: (order[item["status"]], -item["score"], item["strategy"])
    )
    unknowns = []
    if disk_read is None:
        unknowns.append("sustained_disk_read_mib_s")
    return {
        "schema_version": "1.0",
        "complete": not unknowns,
        "artifact_budget": artifact_budget,
        "strategies": strategies,
        "blocking_unknowns": unknowns,
        "global_release_gates": [
            "compatibility",
            "task quality",
            "cold/warm performance",
            "peak resources",
            "cancellation",
            "artifact corruption",
            "rollback",
            "evidence freshness",
        ],
        "effects": [],
        "installed_or_executed": False,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = plan(json.loads(args.inventory.read_text(encoding="utf-8")))
    encoded = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
