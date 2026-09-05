from __future__ import annotations

from dataclasses import replace
import hashlib
from pathlib import Path

import pytest

from runtime.capability_routing import compile_route_plan, route_task
from runtime.model_attachment import build_model_attachment, validate_model_attachment
from runtime.skill_navigator import CapabilitySummary


H = "a" * 64


def _remote(**changes):
    values = {
        "model_id": "provider/model",
        "model_revision": "revision-2026-09-05",
        "artifact_sha256": H,
        "runtime": "provider-gateway",
        "context_tokens": 32768,
        "modalities": ("text",),
        "supports_tools": True,
        "privacy": "policy_gated",
        "authority_class": "contained",
        "benchmark_revision": "b" * 64,
        "hardware_requirements": {"memory": "8GiB"},
    }
    values.update(changes)
    return values


def test_remote_attachment_has_deterministic_exact_identity(tmp_path: Path) -> None:
    first = build_model_attachment(tmp_path, **_remote())
    second = build_model_attachment(tmp_path, **_remote())
    assert first == second
    assert validate_model_attachment(first)["valid"]


def test_local_gguf_binds_path_quantization_and_bytes(tmp_path: Path) -> None:
    model = tmp_path / "models/model.gguf"
    model.parent.mkdir()
    model.write_bytes(b"GGUF exact model")
    digest = hashlib.sha256(model.read_bytes()).hexdigest()
    attachment = build_model_attachment(
        tmp_path,
        **_remote(
            model_id="local/model",
            model_revision="gguf-revision-1",
            artifact_sha256=digest,
            runtime="llama.cpp",
            privacy="local",
            local_artifact_path="models/model.gguf",
            quantization="Q4_K_M",
        ),
    )
    assert validate_model_attachment(attachment, root=tmp_path)["valid"]
    model.write_bytes(b"drift")
    assert not validate_model_attachment(attachment, root=tmp_path)["valid"]


def test_floating_revision_and_unhashed_local_path_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="floating"):
        build_model_attachment(tmp_path, **_remote(model_revision="latest"))
    model = tmp_path / "model.gguf"
    model.write_bytes(b"GGUF")
    with pytest.raises(ValueError, match="hash does not match"):
        build_model_attachment(
            tmp_path,
            **_remote(local_artifact_path="model.gguf", quantization="Q4"),
        )


def test_benchmark_and_fallback_privacy_authority_are_required(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="benchmark_revision"):
        build_model_attachment(tmp_path, **_remote(benchmark_revision="missing"))
    with pytest.raises(ValueError, match="weakens privacy"):
        build_model_attachment(
            tmp_path,
            **_remote(
                privacy="local",
                fallback_chain=[
                    {
                        "model_id": "remote/fallback",
                        "model_revision": "revision-1",
                        "artifact_sha256": H,
                        "privacy": "policy_gated",
                        "authority_class": "contained",
                    }
                ],
            ),
        )


def test_task_plan_hash_binding_detects_attachment_drift(tmp_path: Path) -> None:
    attachment = build_model_attachment(tmp_path, **_remote())
    report = validate_model_attachment(
        attachment, expected_attachment_sha256="c" * 64
    )
    assert not report["valid"]
    tampered = replace(attachment, context_tokens=1)
    assert not validate_model_attachment(tampered)["valid"]


def test_task_route_automatically_selects_exact_model_into_immutable_plan(tmp_path: Path) -> None:
    capability = CapabilitySummary("code-review", "review python coding changes", capability_tags=("coding", "python"))
    route = route_task("review python coding changes", {"skills": (capability,)})
    inventory = (
        {
            **_remote(),
            "available": True,
            "traits": ("coding", "reasoning"),
            "cost_class": "low",
            "latency_class": "low",
            "warm_cost": 0,
            "cold_cost": 0,
            "failure_modes": (),
        },
    )
    plan = compile_route_plan(
        route,
        project_id="project",
        source_revision="source-revision",
        projection_revisions={"semantic": "semantic-revision"},
        effect_budget=("read",),
        authority_bindings=("authority:read",),
        model_inventory=inventory,
        semantic_profile={"domains": ("coding",)},
        model_requirements={"required_traits": ("coding",), "tools_required": True},
        model_root=tmp_path,
        created_utc="2026-09-04T12:00:00Z",
    )
    assert plan.model_attachment["model_id"] == "provider/model"
    assert plan.model_ranking_receipt["selected_attachment_sha256"] == plan.model_attachment["attachment_sha256"]
    assert dict(plan.projection_revisions)["model_attachment"] == plan.model_attachment["attachment_sha256"]


def test_automatic_selection_fails_closed_without_compatible_model(tmp_path: Path) -> None:
    capability = CapabilitySummary("vision", "inspect image", capability_tags=("vision",))
    route = route_task("inspect image", {"skills": (capability,)})
    unavailable = ({**_remote(), "available": False, "traits": ("vision",), "modalities": ("text",)},)
    with pytest.raises(ValueError, match="no compatible model"):
        compile_route_plan(
            route,
            project_id="project",
            source_revision="source-revision",
            projection_revisions={"semantic": "semantic-revision"},
            effect_budget=("read",),
            authority_bindings=("authority:read",),
            model_inventory=unavailable,
            model_requirements={"required_modalities": ("image",)},
            model_root=tmp_path,
        )
