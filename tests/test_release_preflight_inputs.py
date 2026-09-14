"""Causal checks for captured release-preflight declarations and evidence inputs."""
from pathlib import Path
import json

import pytest

from runtime import release_preflight as owner
from tests.release_preflight_testkit import minimal_product


def product(root):
    minimal_product(root)
    policy_path = root / "policies/release-artifact-policy.json"
    artifact_policy = json.loads(policy_path.read_text(encoding="utf-8"))
    artifact_policy["evidence_allowed_suffixes"] = [".json", ".jsonl", ".ndjson", ".md", ".txt", ".log", ".xml", ".png", ".svg", ".sig"]
    artifact_policy["evidence_allowed_names"] = ["SHA256SUMS"]
    policy_path.write_text(json.dumps(artifact_policy), encoding="utf-8")
    (root / "evidence").mkdir()
    (root / "evidence/summary.json").write_bytes(b"{}")
    return root


def policy():
    return {
        "schema_version": "px.release-preflight-policy/1.0",
        "max_total_release_evidence_bytes": 1024,
        "max_single_evidence_file_bytes": 512,
        "max_context_amplification_ratio": 20.0,
    }


@pytest.mark.parametrize("target", [
    "evidence/../runtime/owner.py", "evidence/nested/../../runtime/owner.py",
    ".engineering-bootstrap/../runtime/owner.py", "evidence//out.json",
    "evidence/./out.json", "evidence/out.json:stream", "evidence/NUL.json",
    "evidence/out.json.", "evidence/out.json ", "evidence/<unknown>/out.json",
    "evidence/x<release>/out.json", "evidence/\x00out.json", "evidence/" + "x" * 4097,
])
def test_malformed_feedback_targets_are_refused_before_classification(tmp_path, monkeypatch, target):
    root = product(tmp_path)
    calls = []

    def classify(candidate):
        calls.append(candidate)
        return {"valid": True, "product_valid": True, "errors": [], "product_records": []}

    monkeypatch.setattr(owner, "classify_tree", classify)
    result = owner.feedback_audit(root, [target])
    assert result["valid"] is False
    assert calls == []


@pytest.mark.parametrize("field,value", [("valid", False), ("valid", 1), ("product_valid", False), ("product_valid", 1), ("errors", ["fixture failure"])])
def test_failed_classifier_cannot_authorize_declared_feedback(tmp_path, monkeypatch, field, value):
    root = product(tmp_path)
    result = {"valid": True, "product_valid": True, "errors": [], "product_records": []}
    result[field] = value
    monkeypatch.setattr(owner, "classify_tree", lambda _: result)
    assert owner.feedback_audit(root, ["evidence/output.json"])["valid"] is False


@pytest.mark.parametrize("targets", ["evidence/out.json", ["evidence/out.json"] * 1025, [None], [True]])
def test_feedback_collection_is_bounded_and_not_coerced(tmp_path, monkeypatch, targets):
    root = product(tmp_path)
    calls = []
    monkeypatch.setattr(owner, "classify_tree", lambda _: calls.append(True) or {"valid": True, "product_valid": True, "errors": [], "product_records": []})
    assert owner.feedback_audit(root, targets)["valid"] is False
    assert calls == []


def test_feedback_never_invokes_custom_iteration_or_stringification(tmp_path):
    root = product(tmp_path)

    class Untrusted:
        def __iter__(self):
            raise AssertionError("caller-controlled iteration invoked")

        def __str__(self):
            raise AssertionError("caller-controlled stringification invoked")

    assert owner.feedback_audit(root, Untrusted())["valid"] is False
    assert owner.feedback_audit(root, [Untrusted()])["valid"] is False


@pytest.mark.parametrize("pair", [
    ["evidence/One.json", "evidence/one.json"],
    ["evidence/\u00e9.json", "evidence/e\u0301.json"],
    ["evidence/out.json", "evidence\\out.json"],
])
def test_portable_feedback_aliases_are_not_distinct_authorizations(tmp_path, pair):
    assert owner.feedback_audit(product(tmp_path), pair)["valid"] is False


def test_shipped_feedback_templates_keep_their_classifications(tmp_path):
    root = product(tmp_path)
    targets = [
        ".engineering-bootstrap/release-transaction.json",
        ".engineering-bootstrap/runtime-core/completion_status.json",
        "evidence/releases/<release>/certificate.json",
        "evidence/releases/<release>/certificate.json.sig",
        "evidence/releases/<release>/<run-id>",
    ]
    result = owner.feedback_audit(root, targets)
    assert result["valid"] is True
    assert [item["classification"] for item in result["writes"]] == [
        "temporary_workspace", "post_cert_runtime_state",
        "release_transaction_evidence", "release_transaction_evidence", "release_transaction_evidence",
    ]
    assert not (root / ".engineering-bootstrap").exists()
    assert not (root / "evidence/releases").exists()


def test_case_alias_of_product_input_stays_protected(tmp_path):
    root = product(tmp_path)
    result = owner.feedback_audit(root, ["RUNTIME/OWNER.PY"])
    assert result["valid"] is False
    assert result["writes"][0]["classification"] == "generated_product"


def test_ndjson_evidence_is_scanned_for_machine_local_locators(tmp_path):
    root = product(tmp_path)
    (root / "evidence/events.ndjson").write_text('{"source":"C:/Users/fixture/out.json"}\n', encoding="utf-8")
    result = owner.evidence_portability(root)
    assert result["valid"] is False
    assert any(row["path"] == "evidence/events.ndjson" for row in result["findings"])


def test_evidence_metadata_budget_precedes_any_body_read(tmp_path, monkeypatch):
    root = product(tmp_path)
    limits = policy()
    limits["max_single_evidence_file_bytes"] = 1
    (root / "policies/release-preflight.json").write_text(json.dumps(limits), encoding="utf-8")
    original = Path.open

    def bounded(candidate, *args, **kwargs):
        if candidate.is_relative_to(root / "evidence"):
            raise AssertionError("body opened before release evidence byte admission")
        return original(candidate, *args, **kwargs)

    monkeypatch.setattr(Path, "open", bounded)
    result = owner.evidence_portability(root)
    assert result["valid"] is False


def test_unknown_source_denominator_is_not_numeric_zero_or_complete_assurance(tmp_path):
    (tmp_path / "evidence").mkdir()
    (tmp_path / "evidence/summary.json").write_bytes(b"{}")
    result = owner.evidence_budget(tmp_path, policy())
    assert result["valid"] is False
    assert result["context_amplification_ratio"] is None


def test_known_positive_source_denominator_preserves_valid_budget(tmp_path):
    result = owner.evidence_budget(product(tmp_path), policy())
    assert result["valid"] is True
    assert result["source_bytes"] > 0
    assert result["context_amplification_ratio"] > 0


@pytest.mark.parametrize("field,value", [
    ("max_total_release_evidence_bytes", True), ("max_single_evidence_file_bytes", "512"),
    ("max_single_evidence_file_bytes", 512.0), ("max_context_amplification_ratio", True),
    ("max_context_amplification_ratio", float("inf")),
])
def test_budget_policy_is_typed_before_metadata_acquisition(tmp_path, monkeypatch, field, value):
    root = product(tmp_path)
    limits = policy()
    limits[field] = value
    original = Path.stat

    def no_evidence_metadata(candidate, *args, **kwargs):
        if candidate.is_relative_to(root / "evidence"):
            raise AssertionError("evidence metadata acquired before policy admission")
        return original(candidate, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", no_evidence_metadata)
    assert owner.evidence_budget(root, limits)["valid"] is False


def test_feedback_target_cannot_alias_owned_fixture_product_through_a_hardlink(tmp_path):
    import os

    root = product(tmp_path)
    target = root / "evidence/linked.json"
    os.link(root / "runtime/owner.py", target)
    assert target.samefile(root / "runtime/owner.py")
    assert owner.feedback_audit(root, ["evidence/linked.json"])["valid"] is False


def test_feedback_target_parent_must_be_a_directory_before_classification(tmp_path, monkeypatch):
    root = product(tmp_path)
    (root / "evidence/parent.json").write_bytes(b"{}")
    calls = []
    original = owner.classify_tree

    def classify(candidate):
        calls.append(candidate)
        return original(candidate)

    monkeypatch.setattr(owner, "classify_tree", classify)
    assert owner.feedback_audit(root, ["evidence/parent.json/out.json"])["valid"] is False
    assert calls == []


def selected_callbacks(root, configuration):
    import ast
    import inspect

    # Execute only the actual static callback-construction assignment. This
    # never calls run_preflight or any binding, writer, cache or finalizer path.
    tree = ast.parse(inspect.getsource(owner.run_preflight))
    assignment = next(node for node in tree.body[0].body if isinstance(node, ast.Assign)
                      and any(isinstance(target, ast.Name) and target.id == "static" for target in node.targets))
    module = ast.fix_missing_locations(ast.Module(body=[assignment], type_ignores=[]))
    namespace = {**vars(owner), "root": root, "policy": configuration}
    exec(compile(module, "<actual-static-preflight-callbacks>", "exec"), namespace)
    return namespace["static"]


def test_static_callback_order_and_construction_stay_lazy(monkeypatch):
    def reject(*args, **kwargs):
        raise AssertionError("callback construction performed IO")

    monkeypatch.setattr(owner, "classify_tree", reject)
    monkeypatch.setattr(Path, "stat", reject)
    callbacks = selected_callbacks(Path("unresolved-fixture-root"), {**policy(), "post_certification_writes": []})
    assert [name for name, _ in callbacks] == [
        "generated_dependency_dag", "feedback_audit", "evidence_portability", "evidence_budget", "skip_policy",
        "release_gate_repository_context", "test_group_readiness", "release_test_completion_projection",
    ]


def test_preflight_callbacks_share_one_classifier_and_selected_inventory(tmp_path, monkeypatch):
    import os

    root = product(tmp_path)
    calls = {"classification": 0, "evidence_enumeration": 0}
    classifying = False
    original_classifier = owner.classify_tree
    original_scan = os.scandir

    def classifier(candidate):
        nonlocal classifying
        calls["classification"] += 1
        classifying = True
        try:
            return original_classifier(candidate)
        finally:
            classifying = False

    def scandir(candidate):
        if not classifying and Path(candidate) == root / "evidence":
            calls["evidence_enumeration"] += 1
        return original_scan(candidate)

    monkeypatch.setattr(owner, "classify_tree", classifier)
    monkeypatch.setattr(os, "scandir", scandir)
    callbacks = dict(selected_callbacks(root, {**policy(), "post_certification_writes": ["evidence/out.json"]}))
    for name in ["feedback_audit", "evidence_portability", "evidence_budget"]:
        assert callbacks[name]()["valid"] is True
    assert calls == {"classification": 1, "evidence_enumeration": 1}


def test_budget_cannot_silently_switch_images_after_portability(tmp_path):
    root = product(tmp_path)
    callbacks = dict(selected_callbacks(root, {**policy(), "post_certification_writes": ["evidence/out.json"]}))
    assert callbacks["feedback_audit"]()["valid"] is True
    assert callbacks["evidence_portability"]()["valid"] is True
    (root / "evidence/summary.json").write_bytes(b'{"changed":true}')
    assert callbacks["evidence_budget"]()["valid"] is False


def test_callback_construction_captures_consumed_declarations(tmp_path):
    root = product(tmp_path)
    configuration = {**policy(), "post_certification_writes": ["evidence/out.json"]}
    callbacks = dict(selected_callbacks(root, configuration))
    configuration["post_certification_writes"][0] = "runtime/owner.py"
    configuration["max_single_evidence_file_bytes"] = 1
    assert callbacks["feedback_audit"]()["valid"] is True
    assert callbacks["evidence_budget"]()["valid"] is True
