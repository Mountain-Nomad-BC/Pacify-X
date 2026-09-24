"""Stage 4 regression: producer -> registry -> consumer -> runtime -> failure path.

These pin the verification the owner required. The point is not that a registry file exists; it is
that the chain resolves, the runtime uses it, and malformed/stale/unowned state is refused.

A probe that searches source for a template *filename* produces false "orphan" claims, because the
loaders enumerate directories. That lesson is pinned here too.
"""

from __future__ import annotations

import importlib
import json
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from runtime.registry import validate_registry  # noqa: E402

REQUIRED_FOR_VALIDATION = (
    "bootstrap/startup.toml",
    "registry/capability_map.json",
    "registry/admission_ledger.json",
)


# ---------------------------------------------------------------------------
# 1. producer -> registry -> consumer
# ---------------------------------------------------------------------------

CONSUMERS = (
    "runtime.models",
    "runtime.model_profile",
    "runtime.registry",
    "runtime.provider_gateway",
    "runtime.system_one_decision",
    "runtime.test_profiles",
    "runtime.local_model_lane_orchestration",
)


@pytest.mark.parametrize("module_name", CONSUMERS)
def test_consumer_imports_and_exposes_public_api(module_name: str) -> None:
    module = importlib.import_module(module_name)
    public = [
        n
        for n in dir(module)
        if not n.startswith("_") and callable(getattr(module, n, None))
    ]
    assert public, f"{module_name} exposes no public callable"


@pytest.mark.parametrize(
    "relative",
    (
        "models/model-portfolio.json",
        "models/runtime-profiles.json",
        "registry/skill_catalog.toml",
        "registry/admission_ledger.json",
        "registry/provider_adapters.json",
        "registry/system_one_decision_policy.json",
        "registry/test_profiles.json",
        "registry/workflow_execution_bindings.json",
    ),
)
def test_produced_artifacts_exist(relative: str) -> None:
    assert (ROOT / relative).is_file(), f"{relative} must be produced"


# ---------------------------------------------------------------------------
# 2. contracts
# ---------------------------------------------------------------------------


def test_registry_validates_with_no_errors() -> None:
    result = validate_registry(ROOT)
    assert result["valid"], result["errors"]
    assert result["active_count"] > 100


def test_every_active_entry_has_a_valid_contract() -> None:
    payload = json.loads(
        (ROOT / "registry/capability_map.json").read_text(encoding="utf-8")
    )
    ledger = {
        r["id"]
        for r in json.loads(
            (ROOT / "registry/admission_ledger.json").read_text(encoding="utf-8")
        )["records"]
        if r.get("status") == "active"
    }
    for entry in payload["active_capabilities"]:
        assert entry["id"] in ledger, f"{entry['id']} has no ACTIVE admission record"
        contract_path = ROOT / entry["contract"]
        assert contract_path.is_file(), f"{entry['id']} contract missing"
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        assert contract["id"] == entry["id"]
        assert contract["version"] == entry["version"]


# ---------------------------------------------------------------------------
# 3. templates are consumed by directory-level loaders
# ---------------------------------------------------------------------------


DIRECTORY_LOADERS = (
    "runtime/generated_artifacts.py",
    "runtime/integration_disposition.py",
    "runtime/python_surface_certification.py",
    "runtime/release_audit.py",
    "runtime/release_distribution.py",
    "runtime/structural_integrity.py",
)


@pytest.mark.parametrize("relative", DIRECTORY_LOADERS)
def test_template_directory_loader_exists(relative: str) -> None:
    assert (ROOT / relative).is_file()


@pytest.mark.parametrize(
    "family,token",
    (
        ("templates/project_stream", "project_stream"),
        ("templates/declared_suite", "declared_suite"),
        ("templates/metacognitive", "metacognitive"),
        ("templates/service_capabilities", "service_capabilities"),
    ),
)
def test_template_family_is_referenced_by_a_loader(family: str, token: str) -> None:
    # A template family is consumed when a loader references the family, even though no source
    # file names an individual template file. Searching only for filenames produces false orphans.
    directory = ROOT / family
    assert directory.is_dir(), f"{family} must exist"
    assert list(directory.rglob("*")), f"{family} must contain templates"
    referencing = []
    for source in list((ROOT / "runtime").rglob("*.py")) + list(
        (ROOT / "scripts").rglob("*.py")
    ):
        if token in source.read_text(encoding="utf-8-sig", errors="replace"):
            referencing.append(source.relative_to(ROOT).as_posix())
    assert referencing, f"no loader references the {family} family"


# ---------------------------------------------------------------------------
# 4. runtime actually uses the registry
# ---------------------------------------------------------------------------


def test_graph_artifacts_are_built_from_the_capability_registry() -> None:
    from runtime.graph_registry import build_graph_artifacts

    artifacts = build_graph_artifacts(ROOT)
    assert "capability_graph.json" in artifacts
    graph = json.loads(artifacts["capability_graph.json"])
    # The graph must reflect the real capability surface, not a small stub.
    assert len(graph.get("nodes", [])) > 100


def test_lane_orchestration_resolves_models_from_the_profile_registry() -> None:
    from runtime.local_model_lane_orchestration import (
        load_lane_models,
        plan_lane_decision,
    )

    lanes = load_lane_models(ROOT)
    assert set(lanes) == {"control", "deep"}
    assert lanes["control"]["model_id"] != lanes["deep"]["model_id"]
    decision = plan_lane_decision(ROOT, traits=["deep_reasoning"])
    assert decision.model_id == lanes["deep"]["model_id"]


def test_provider_registry_admission_is_consumed() -> None:
    from runtime.provider_gateway import load_provider_registry

    registry = load_provider_registry(ROOT)
    admitted = {a["adapter_id"] for a in registry["adapters"] if a.get("admitted")}
    assert "llama-cpp-stream" in admitted
    # Remote adapters must remain unadmitted until deliberately enabled.
    remote = {
        a["adapter_id"] for a in registry["adapters"] if a.get("mode") == "remote"
    }
    assert not (remote & admitted)


def test_decision_policy_actually_gates_a_decision() -> None:
    from runtime.system_one_decision import (
        DecisionResult,
        evaluate_decision,
        load_decision_policy,
    )

    policies = load_decision_policy(ROOT)
    policy = policies["routing.model_tier"]
    strong = DecisionResult(
        decision_id="routing.model_tier",
        answers={
            "tier": {
                "type": "choice",
                "choice": "active_librarian",
                "probabilities": {
                    "nano": 0.03,
                    "active_librarian": 0.77,
                    "heavy_local": 0.17,
                    "remote": 0.03,
                },
            }
        },
        checkpoint="typed-decisions",
        revision=None,
        routing_reason=None,
        input_state_sha256="0" * 64,
        latency_ms=1.0,
    )
    assert evaluate_decision(strong, policy, question_id="tier").accepted is True


# ---------------------------------------------------------------------------
# 5. failure paths reject malformed / stale / unowned state
# ---------------------------------------------------------------------------


def _seed(tmp_path: Path) -> None:
    for relative in REQUIRED_FOR_VALIDATION:
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((ROOT / relative).read_bytes())


def test_malformed_contract_is_rejected(tmp_path: Path) -> None:
    _seed(tmp_path)
    payload = json.loads(
        (tmp_path / "registry/capability_map.json").read_text(encoding="utf-8")
    )
    contract = tmp_path / payload["active_capabilities"][0]["contract"]
    contract.parent.mkdir(parents=True, exist_ok=True)
    contract.write_text("{ not valid json", encoding="utf-8")
    assert validate_registry(tmp_path)["valid"] is False


def test_unowned_capability_is_rejected(tmp_path: Path) -> None:
    _seed(tmp_path)
    ledger_path = tmp_path / "registry/admission_ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["records"] = []
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
    assert validate_registry(tmp_path)["valid"] is False


def test_stale_admission_is_rejected(tmp_path: Path) -> None:
    _seed(tmp_path)
    payload = json.loads(
        (tmp_path / "registry/capability_map.json").read_text(encoding="utf-8")
    )
    first_id = payload["active_capabilities"][0]["id"]
    ledger_path = tmp_path / "registry/admission_ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["records"] = [r for r in ledger["records"] if r.get("id") != first_id]
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
    assert validate_registry(tmp_path)["valid"] is False


def test_unknown_decision_policy_is_absent_not_defaulted() -> None:
    from runtime.system_one_decision import load_decision_policy

    assert load_decision_policy(ROOT, "no.such.decision") == {}


def test_missing_model_artifact_is_rejected() -> None:
    from runtime.local_model_runtime import LocalModelRuntime

    runtime = LocalModelRuntime(
        ROOT,
        allowed_model_roots=[ROOT / ".pacify-x/models"],
        allowed_runtime_roots=[Path.home() / ".px"],
    )
    with pytest.raises(Exception):
        runtime.inspect_model(ROOT / ".pacify-x/models/definitely-absent.gguf")
