"""Causal producer/consumer contracts for model and calculation inputs."""

from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from runtime.knowledge_foundry import (
    CalculationSpec,
    SourceArtifact,
    compile_calculation,
    compile_foundry_bundle,
)
from runtime.foundry_studio_bridge import (
    export_foundry_candidate,
    build_skill_studio_draft,
    validate_foundry_candidate,
)


@pytest.mark.parametrize(
    "name", ["class", "return", "var", "let", "await", "arguments", "eval"]
)
def test_calculation_function_identifiers_are_valid_in_both_target_languages(name):
    with pytest.raises(ValueError, match="identifier"):
        compile_calculation(
            CalculationSpec(name, "x + 1", ("x",), {"x": "1", "result": "1"})
        )


@pytest.mark.parametrize(
    "extra", ["class", "a-b", "arguments", "eval", "let", "await", "pyMod", "x"]
)
def test_unused_calculation_variables_still_obey_unique_identifier_contract(extra):
    with pytest.raises(ValueError, match="identifier"):
        compile_calculation(
            CalculationSpec(
                "safe", "x + 1", ("x", extra), {"x": "1", extra: "1", "result": "1"}
            )
        )


def test_calculation_equation_budget_precedes_ast_parsing(monkeypatch):
    import runtime.knowledge_foundry as foundry

    equation = "x + " * 2000 + "1"
    original = foundry.ast.parse

    def forbidden(source, *args, **kwargs):
        if source == equation:
            raise AssertionError(
                "oversized input must be refused before AST allocation"
            )
        return original(source, *args, **kwargs)

    monkeypatch.setattr(foundry.ast, "parse", forbidden)
    with pytest.raises(ValueError, match="budget|bounded"):
        compile_calculation(
            CalculationSpec("oversized", equation, ("x",), {"x": "1", "result": "1"})
        )


def test_nonempty_calculation_survives_foundry_export_and_draft_intake():
    text = "# Calculation\n- Apply formula units with evidence and validation.\n"
    source = SourceArtifact(
        "calculation-note",
        "engineering_note",
        "memory:calculation-note",
        hashlib.sha256(text.encode()).hexdigest(),
        text,
        "internal-reference",
        "Owned calculation contract fixture, revision 1",
        "1",
    )
    bundle = compile_foundry_bundle(
        (source,),
        calculations=(
            CalculationSpec(
                "speed",
                "distance / duration",
                ("distance", "duration"),
                {"distance": "m", "duration": "s", "result": "m/s"},
            ),
        ),
    )
    calculation = bundle.calculations[0]
    candidate = export_foundry_candidate(bundle, bundle.skills[0].skill_id)
    validate_foundry_candidate(candidate)
    assert candidate.formulas == (
        {
            "calculation_id": calculation.calculation_id,
            "expression": "distance / duration",
            "normalized_dimension": calculation.normalized_dimension,
            "formula_engine_revision": calculation.formula_engine_revision,
        },
    )
    assert isinstance(candidate.formulas[0]["normalized_dimension"], str)
    draft = build_skill_studio_draft(
        candidate,
        studio_decision="accept",
        decided_by="fixture-reviewer",
        decision_reason="verify complete producer-to-consumer fields",
    )
    assert draft.manifest["formulas"] == candidate.formulas
    assert draft.canonical_promotion_authorized is False
    assert ast.parse(calculation.python_source).body[0].name == "speed"


def test_admitted_calculation_sources_pass_independent_python_and_javascript_parsers(
    tmp_path,
):
    import os
    import shutil
    from runtime.test_runner import run_test_command

    node = shutil.which("node")
    if node is None:
        pytest.skip(
            "A local Node parser is required for generated JavaScript syntax proof"
        )
    specs = [
        CalculationSpec(
            "safe-sum",
            "arg_1 + value2",
            ("arg_1", "value2"),
            {"arg_1": "1", "value2": "1", "result": "1"},
        ),
        CalculationSpec(
            "safe-modulo",
            "_value % divisor",
            ("_value", "divisor"),
            {"_value": "1", "divisor": "1", "result": "1"},
        ),
    ]
    packages = [compile_calculation(spec) for spec in specs]
    for package in packages:
        parsed = ast.parse(package.python_source)
        assert [arg.arg for arg in parsed.body[0].args.args] == list(package.variables)
    module = tmp_path / "compiled-calculations.mjs"
    module.write_text(
        "\n".join(p.javascript_source for p in packages), encoding="utf-8"
    )
    result = run_test_command(
        [node, "--check", str(module)],
        cwd=tmp_path,
        environment={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        timeout_seconds=30,
        run_id="calculation-target-syntax",
        lane_id="causal-parser-proof",
        manage_process_temp=True,
    )
    assert result["valid"], result
    assert result["process_tree_terminated"] and result["test_workspace"]["reclaimed"]


def _model_values(**changes):
    values = dict(
        model_id="provider/model",
        model_revision="revision-1",
        artifact_sha256="a" * 64,
        runtime="provider-gateway",
        context_tokens=32768,
        modalities=("text",),
        supports_tools=True,
        privacy="policy_gated",
        authority_class="contained",
        benchmark_revision="b" * 64,
        hardware_requirements={"memory": "8GiB"},
    )
    values.update(changes)
    return values


def _reseal_attachment(attachment, **changes):
    updated = replace(attachment, **changes)
    payload = updated.as_dict()
    payload.pop("attachment_sha256")
    payload.pop("attachment_id")

    def digest(value):
        return hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    identifier = "model-attachment-" + digest(payload)[:24]
    payload["attachment_id"] = identifier
    return replace(updated, attachment_id=identifier, attachment_sha256=digest(payload))


@pytest.mark.parametrize(
    "changes",
    [
        {"schema_version": "unsupported"},
        {"context_tokens": True},
        {"supports_tools": "false"},
        {"quantization": "Q4"},
    ],
)
def test_self_consistent_decoded_attachment_still_requires_the_complete_schema(
    tmp_path, changes
):
    from runtime.model_attachment import (
        build_model_attachment,
        validate_model_attachment,
    )

    original = build_model_attachment(tmp_path, **_model_values())
    report = validate_model_attachment(
        _reseal_attachment(original, **changes), root=tmp_path
    )
    assert report["valid"] is False


def test_self_consistent_fallback_revision_cannot_float(tmp_path):
    from runtime.model_attachment import (
        ModelFallback,
        build_model_attachment,
        validate_model_attachment,
    )

    original = build_model_attachment(tmp_path, **_model_values())
    fallback = ModelFallback("other/model", "latest", "c" * 64, "local", "contained")
    report = validate_model_attachment(
        _reseal_attachment(original, fallback_chain=(fallback,)), root=tmp_path
    )
    assert report["valid"] is False


@pytest.mark.parametrize(
    "changes",
    [
        {"supports_tools": "false"},
        {"context_tokens": True},
        {"fallback_chain": ["discarded"]},
        {"hardware_requirements": []},
        {"undeclared_field": True},
    ],
)
def test_attachment_decoder_does_not_coerce_or_discard_invalid_fields(
    tmp_path, changes
):
    from runtime.model_attachment import (
        build_model_attachment,
        model_attachment_from_dict,
    )

    payload = build_model_attachment(tmp_path, **_model_values()).as_dict()
    payload.update(changes)
    with pytest.raises(ValueError):
        model_attachment_from_dict(payload)


def test_decoded_local_attachment_refuses_escape_before_reading_bytes(
    tmp_path, monkeypatch
):
    from runtime.model_attachment import (
        build_model_attachment,
        validate_model_attachment,
    )

    root = tmp_path / "project"
    root.mkdir()
    outside = tmp_path / "outside.gguf"
    outside.write_bytes(b"GGUF fixture")
    original = build_model_attachment(root, **_model_values())
    altered = _reseal_attachment(
        original,
        local_artifact_path="../outside.gguf",
        quantization="Q4",
        artifact_sha256=hashlib.sha256(b"GGUF fixture").hexdigest(),
    )
    original_open = Path.open

    def guarded(path, *args, **kwargs):
        if path.resolve() == outside:
            raise AssertionError("escaping model bytes must never be acquired")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded)
    assert validate_model_attachment(altered, root=root)["valid"] is False


def test_decoded_local_attachment_requires_gguf_suffix(tmp_path):
    from runtime.model_attachment import (
        build_model_attachment,
        validate_model_attachment,
    )

    path = tmp_path / "not-a-model.txt"
    path.write_bytes(b"fixture")
    original = build_model_attachment(tmp_path, **_model_values())
    altered = _reseal_attachment(
        original,
        local_artifact_path=path.name,
        quantization="Q4",
        artifact_sha256=hashlib.sha256(b"fixture").hexdigest(),
    )
    assert validate_model_attachment(altered, root=tmp_path)["valid"] is False


def test_local_attachment_builder_acquires_one_model_image(tmp_path, monkeypatch):
    from runtime.model_attachment import build_model_attachment

    path = tmp_path / "model.gguf"
    path.write_bytes(b"GGUF fixture")
    original_open = Path.open
    reads = []

    def counted(target, *args, **kwargs):
        if target == path:
            reads.append(target)
        return original_open(target, *args, **kwargs)

    monkeypatch.setattr(Path, "open", counted)
    build_model_attachment(
        tmp_path,
        **_model_values(
            local_artifact_path=path.name,
            quantization="Q4",
            artifact_sha256=hashlib.sha256(b"GGUF fixture").hexdigest(),
        ),
    )
    assert reads == [path]


def test_model_inventory_duplicate_identity_is_rejected_before_ranking(tmp_path):
    from runtime.model_attachment import select_model_attachment
    from runtime.capability_routing import route_task
    from runtime.skill_navigator import CapabilitySummary

    route = route_task(
        "review code", {"skills": (CapabilitySummary("review", "review code"),)}
    )
    rejected = {**_model_values(), "available": False, "traits": ("reasoning",)}
    eligible = {
        **_model_values(model_revision="revision-2", artifact_sha256="c" * 64),
        "available": True,
        "traits": ("reasoning",),
    }
    with pytest.raises(ValueError, match="duplicate|unique"):
        select_model_attachment(tmp_path, route, [rejected, eligible])


@pytest.mark.parametrize(
    "changes",
    [
        {"available": "false"},
        {"supports_tools": "false"},
        {"context_tokens": "32768"},
        {"traits": "reasoning"},
        {"cold_cost": float("nan")},
        {"warm_cost": float("inf")},
    ],
)
def test_model_selection_preserves_types_before_capability_conversion(
    tmp_path, changes
):
    from runtime.model_attachment import select_model_attachment
    from runtime.capability_routing import route_task
    from runtime.skill_navigator import CapabilitySummary

    route = route_task(
        "review code", {"skills": (CapabilitySummary("review", "review code"),)}
    )
    row = {**_model_values(), "available": True, "traits": ("reasoning",), **changes}
    with pytest.raises(ValueError):
        select_model_attachment(tmp_path, route, [row])


def test_direct_ranker_rejects_duplicate_identity_even_when_one_row_is_ineligible():
    from runtime.models import ModelCapability, rank_models

    model = ModelCapability(
        "duplicate",
        "runtime",
        True,
        1000,
        ("reasoning",),
        False,
        "local",
        "free",
        "low",
        0,
        0,
        (),
    )
    with pytest.raises(ValueError, match="duplicate|unique"):
        rank_models(("reasoning",), (replace(model, available=False), model))


def test_local_model_budget_is_checked_before_open(tmp_path, monkeypatch):
    import runtime.model_attachment as attachments

    path = tmp_path / "model.gguf"
    path.write_bytes(b"GGUF fixture")
    monkeypatch.setattr(attachments, "MAX_LOCAL_ARTIFACT_BYTES", 8)
    original = Path.open

    def guarded(target, *args, **kwargs):
        if target == path:
            raise AssertionError("oversized model must be refused before acquisition")
        return original(target, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded)
    with pytest.raises(ValueError, match="byte budget"):
        attachments.build_model_attachment(
            tmp_path, **_model_values(local_artifact_path=path.name, quantization="Q4")
        )


def test_local_model_hash_uses_bounded_stream_reads(tmp_path, monkeypatch):
    from runtime.model_attachment import build_model_attachment

    data = b"GGUF" + b"x" * 150000
    path = tmp_path / "model.gguf"
    path.write_bytes(data)
    original = Path.open
    requested = []

    class CheckedStream:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.stream.close()

        def fileno(self):
            return self.stream.fileno()

        def read(self, size=-1):
            assert 0 < size <= 65536
            requested.append(size)
            return self.stream.read(size)

    def opened(target, *args, **kwargs):
        stream = original(target, *args, **kwargs)
        return CheckedStream(stream) if target == path else stream

    monkeypatch.setattr(Path, "open", opened)
    build_model_attachment(
        tmp_path,
        **_model_values(
            local_artifact_path=path.name,
            quantization="Q4",
            artifact_sha256=hashlib.sha256(data).hexdigest(),
        ),
    )
    assert len(requested) >= 3 and max(requested) == 65536


@pytest.mark.parametrize(
    "changes",
    [
        {"trait_weight": float("nan")},
        {"cold_cost_weight": float("inf")},
        {"privacy_weights": {"local": float("nan")}},
        {"unavailable_is_ineligible": "false"},
        {"sensitive_privacy": "local"},
    ],
)
def test_ranker_requires_typed_finite_policy_even_for_an_empty_inventory(changes):
    from runtime.models import DEFAULT_ROUTING_POLICY, rank_models

    with pytest.raises(ValueError):
        rank_models((), (), policy=replace(DEFAULT_ROUTING_POLICY, **changes))


@pytest.mark.parametrize(
    "mutation", ["numeric-string", "boolean-string", "unsupported-trait-mode"]
)
def test_model_policy_loader_does_not_coerce_or_ignore_declared_controls(
    tmp_path, mutation
):
    from runtime.models import load_model_routing_policy

    source = Path(__file__).parents[1] / "models/routing-policy.json"
    data = json.loads(source.read_text(encoding="utf-8"))
    if mutation == "numeric-string":
        data["scoring"]["trait_weight"] = "10"
    elif mutation == "boolean-string":
        data["eligibility"]["unavailable_is_ineligible"] = "false"
    else:
        data["eligibility"]["required_traits_must_all_match"] = False
    directory = tmp_path / "models"
    directory.mkdir()
    (directory / "routing-policy.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        load_model_routing_policy(tmp_path)


@pytest.mark.parametrize(
    "changes",
    [
        {"model_revision": 42},
        {"hardware_requirements": [("ram", "8gb")]},
    ],
)
def test_selection_preserves_attachment_metadata_types(tmp_path, changes):
    from runtime.model_attachment import select_model_attachment
    from runtime.capability_routing import route_task
    from runtime.skill_navigator import CapabilitySummary

    route = route_task(
        "review code", {"skills": (CapabilitySummary("review", "review code"),)}
    )
    row = {**_model_values(), "available": True, "traits": ("reasoning",), **changes}
    with pytest.raises(ValueError):
        select_model_attachment(tmp_path, route, [row])


def test_selection_rejects_fallback_generator_before_materializing(tmp_path):
    from runtime.model_attachment import select_model_attachment
    from runtime.capability_routing import route_task
    from runtime.skill_navigator import CapabilitySummary

    route = route_task(
        "review code", {"skills": (CapabilitySummary("review", "review code"),)}
    )

    def forbidden():
        raise AssertionError("fallback collection must be checked before iteration")
        yield

    row = {
        **_model_values(),
        "available": True,
        "traits": ("reasoning",),
        "fallback_chain": forbidden(),
    }
    with pytest.raises(ValueError):
        select_model_attachment(tmp_path, route, [row])


@pytest.mark.parametrize("profile", [{"domains": "reasoning"}, [], {"mechanisms": 42}])
def test_selection_rejects_malformed_semantic_requirements(tmp_path, profile):
    from runtime.model_attachment import select_model_attachment
    from runtime.capability_routing import route_task
    from runtime.skill_navigator import CapabilitySummary

    route = route_task(
        "review code", {"skills": (CapabilitySummary("review", "review code"),)}
    )
    row = {**_model_values(), "available": True, "traits": ("reasoning",)}
    with pytest.raises(ValueError):
        select_model_attachment(tmp_path, route, [row], semantic_profile=profile)


def test_runtime_discovery_counts_duplicate_input_before_deduplication():
    from runtime.models import discover_local_runtimes

    consumed = []
    resolved = []

    def names():
        for index in range(258):
            if index == 257:
                raise AssertionError("discovery read beyond its bounded intake")
            consumed.append(index)
            yield "ollama"

    with pytest.raises(ValueError):
        discover_local_runtimes(names(), resolver=lambda name: resolved.append(name))
    assert len(consumed) == 257
    assert resolved == []


def test_runtime_discovery_limit_is_an_integer():
    from runtime.models import discover_local_runtimes

    with pytest.raises(ValueError):
        discover_local_runtimes((), max_runtimes=True)
