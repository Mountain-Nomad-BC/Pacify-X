"""Declaration presence cannot stand in for exact unique ordered relationships."""

import copy
import json
from pathlib import Path

import pytest

from runtime.clean_room_capabilities import validate_clean_room_capability_workflow
from runtime.project_impact import validate_project_change_intelligence_orchestration
from runtime.project_reasoning.frontier import validate_reasoning_orchestration
from runtime.structural_integrity import _skill_errors, _workflow_errors


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = {
    "reasoning": ("engineering-reasoning-loop", validate_reasoning_orchestration),
    "clean": ("clean-room-capability-controls", validate_clean_room_capability_workflow),
    "impact": ("project-change-intelligence", validate_project_change_intelligence_orchestration),
}


def _write(root, relative, value):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _source_fixture(tmp_path, kind):
    name, validator = WORKFLOWS[kind]
    relative = "orchestration/workflows/" + name + ".yaml"
    payload = json.loads((ROOT / relative).read_text(encoding="utf-8"))
    path = _write(tmp_path, relative, payload)
    catalog = tmp_path / "registry/skill_catalog.toml"
    catalog.parent.mkdir(exist_ok=True)
    catalog.write_bytes((ROOT / "registry/skill_catalog.toml").read_bytes())
    contracts = {"contracts/project-impact.schema.json"}
    if kind == "clean":
        contracts |= {s["contract"] for s in payload["workflows"][0]["steps"]}
    for relative in contracts:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())
    return path, payload, validator


def _steps(payload):
    return payload["workflows"][0]["steps"] if "workflows" in payload else payload["steps"]


@pytest.mark.parametrize("kind", WORKFLOWS)
def test_declared_workflow_positive_preserves_current_structure(tmp_path, kind):
    _, _, validator = _source_fixture(tmp_path, kind)
    assert validator(tmp_path)["valid"] is True


@pytest.mark.parametrize("kind", WORKFLOWS)
@pytest.mark.parametrize("malformed", [[], True, {"workflows": [True]}, {"steps": [True]}])
def test_malformed_workflow_is_a_structured_refusal(tmp_path, kind, malformed):
    path, _, validator = _source_fixture(tmp_path, kind)
    path.write_text(json.dumps(malformed), encoding="utf-8")
    result = validator(tmp_path)
    assert result["valid"] is False and result["errors"]


@pytest.mark.parametrize("kind", WORKFLOWS)
def test_duplicate_json_keys_are_not_last_value_wins(tmp_path, kind):
    path, payload, validator = _source_fixture(tmp_path, kind)
    raw = json.dumps(payload)
    path.write_text('{"schema_version":"wrong",' + raw[1:], encoding="utf-8")
    assert validator(tmp_path)["valid"] is False


@pytest.mark.parametrize("kind", WORKFLOWS)
@pytest.mark.parametrize("mutation", ["duplicate", "order", "dependency", "boolean_dependency", "inactive"])
def test_workflow_relationship_mutations_are_refused(tmp_path, kind, mutation):
    path, payload, validator = _source_fixture(tmp_path, kind)
    steps = _steps(payload)
    if mutation == "duplicate":
        extra = copy.deepcopy(steps[0])
        extra["id"] = "extra-copy"
        steps.append(extra)
    elif mutation == "order":
        steps.reverse()
    elif mutation == "dependency":
        steps[0]["depends_on"] = [steps[-1]["id"]]
    elif mutation == "boolean_dependency":
        steps[0]["depends_on"] = [True]
    else:
        catalog = tmp_path / "registry/skill_catalog.toml"
        catalog.write_text(catalog.read_text(encoding="utf-8").replace('status = "active"', 'status = "retired"'), encoding="utf-8")
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert validator(tmp_path)["valid"] is False


def test_reasoning_names_in_irrelevant_metadata_do_not_prove_steps(tmp_path):
    path, payload, validator = _source_fixture(tmp_path, "reasoning")
    payload["irrelevant_names"] = [s["skill"] for s in _steps(payload)]
    payload["workflows"][0]["steps"] = []
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert validator(tmp_path)["valid"] is False


@pytest.mark.parametrize("mutation", ["binding", "contract", "escaping_contract", "schema", "schema_id", "schema_ref", "schema_pattern", "effects"])
def test_clean_room_contracts_are_bound_to_their_exact_operations(tmp_path, mutation):
    path, payload, validator = _source_fixture(tmp_path, "clean")
    steps = _steps(payload)
    if mutation == "binding":
        steps[0]["runtime_binding"] = steps[1]["runtime_binding"]
    elif mutation == "contract":
        steps[0]["contract"] = steps[1]["contract"]
    elif mutation == "escaping_contract":
        outside = tmp_path.parent / "outside-contract.json"
        outside.write_text("{}", encoding="utf-8")
        steps[0]["contract"] = "../outside-contract.json"
    elif mutation == "effects":
        payload["workflows"][0]["effects"] = ["write_workspace"]
    else:
        schema_path = tmp_path / steps[0]["contract"]
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        if mutation == "schema":
            schema["required"] = True
        elif mutation == "schema_id":
            schema["$id"] = "urn:unrelated:contract"
        elif mutation == "schema_pattern":
            schema["pattern"] = "(" * 2048
        else:
            schema["$ref"] = "../../outside-contract.json"
        schema_path.write_text(json.dumps(schema), encoding="utf-8")
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert validator(tmp_path)["valid"] is False


@pytest.mark.parametrize("kind", WORKFLOWS)
def test_workflow_byte_limit_precedes_body_read(tmp_path, monkeypatch, kind):
    path, payload, validator = _source_fixture(tmp_path, kind)
    with path.open("wb") as stream:
        stream.write(json.dumps(payload).encode())
        stream.seek(1024 * 1024)
        stream.write(b" ")
    original = Path.open
    def guarded(self, *args, **kwargs):
        if self == path:
            raise AssertionError("oversized declaration body was opened")
        return original(self, *args, **kwargs)
    monkeypatch.setattr(Path, "open", guarded)
    assert validator(tmp_path)["valid"] is False


def _registry_fixture(tmp_path, monkeypatch):
    import runtime.project_stream_orchestrator as owner
    monkeypatch.setattr(owner, "BUILTIN_HANDLERS", {"one": object()})
    catalog = tmp_path / "registry/skill_catalog.toml"
    catalog.parent.mkdir()
    catalog.write_text('schema_version = "1.0"\n[[skills]]\nid = "skill-a"\nstatus = "active"\n', encoding="utf-8")
    (tmp_path / ".px/skills/skill-a").mkdir(parents=True)
    _write(tmp_path, "registry/semantic_capability_index.json", {"records": [{"id": "skill-a", "kind": "skill"}]})
    _write(tmp_path, "orchestration/workflows/project_stream/one.yaml", {})
    _write(tmp_path, "orchestration/workflows/one.yaml", {})
    _write(tmp_path, "registry/project_stream_orchestrations.json", {"count": 1, "orchestrations": [{"orchestration_id": "one"}]})
    _write(tmp_path, "registry/project_stream_handlers.json", {"executable_count": 1, "plan_only_count": 0, "workflows": [{"orchestration_id": "one", "status": "executable"}]})
    _write(tmp_path, "registry/workflow_execution_bindings.json", {"count": 1, "bindings": [{"path": "orchestration/workflows/one.yaml", "entrypoint": "runtime.clean_room_capabilities:run_clean_room_operation", "mode": "executable_validator"}]})
    _write(tmp_path, "registry/skill_orchestrations.json", {"count": 1, "workflows": [{"id": "one", "steps": [{"id": "a", "skill": "skill-a", "depends_on": []}, {"id": "b", "skill": "skill-a", "depends_on": ["a"]}]}]})


def test_structural_relationship_fixture_has_complete_denominators(tmp_path, monkeypatch):
    _registry_fixture(tmp_path, monkeypatch)
    assert _workflow_errors(tmp_path) == []
    assert _skill_errors(tmp_path) == []


@pytest.mark.parametrize("mutation", ["project", "handler", "binding", "workflow", "step", "edge", "catalog", "order", "boolean_count"])
def test_structural_sets_cannot_hide_duplicate_or_out_of_order_declarations(tmp_path, monkeypatch, mutation):
    _registry_fixture(tmp_path, monkeypatch)
    if mutation == "catalog":
        with (tmp_path / "registry/skill_catalog.toml").open("a", encoding="utf-8") as stream:
            stream.write('[[skills]]\nid = "skill-a"\nstatus = "active"\n')
    else:
        relative, field = {
            "project": ("project_stream_orchestrations", "orchestrations"),
            "handler": ("project_stream_handlers", "workflows"),
            "binding": ("workflow_execution_bindings", "bindings"),
        }.get(mutation, ("skill_orchestrations", "workflows"))
        path = tmp_path / ("registry/" + relative + ".json")
        value = json.loads(path.read_text(encoding="utf-8"))
        if mutation == "step":
            value[field][0]["steps"].append(copy.deepcopy(value[field][0]["steps"][0]))
        elif mutation == "edge":
            value[field][0]["steps"][1]["depends_on"] = ["a", "a"]
        elif mutation == "order":
            value[field][0]["steps"].reverse()
        elif mutation == "boolean_count":
            value["count"] = True
        else:
            value[field].append(copy.deepcopy(value[field][0]))
            value["count" if mutation != "handler" else "executable_count"] = 2
        path.write_text(json.dumps(value), encoding="utf-8")
    assert _workflow_errors(tmp_path)


@pytest.mark.parametrize("mutation", ["catalog", "semantic"])
def test_skill_identity_comparison_rejects_duplicate_rows(tmp_path, monkeypatch, mutation):
    _registry_fixture(tmp_path, monkeypatch)
    if mutation == "catalog":
        with (tmp_path / "registry/skill_catalog.toml").open("a", encoding="utf-8") as stream:
            stream.write('[[skills]]\nid = "skill-a"\nstatus = "active"\n')
    else:
        path = tmp_path / "registry/semantic_capability_index.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        value["records"].append(copy.deepcopy(value["records"][0]))
        path.write_text(json.dumps(value), encoding="utf-8")
    assert _skill_errors(tmp_path)


def test_current_workflow_and_skill_relationships_remain_structurally_valid():
    assert _workflow_errors(ROOT) == []
    assert _skill_errors(ROOT) == []
