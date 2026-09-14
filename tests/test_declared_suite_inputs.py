"""Prepared causal checks; install only after declared-suite repair admission."""

import json
import math
from pathlib import Path

import pytest

from runtime.declared_suite import (
    _compare,
    _rank,
    _scan,
    _validate,
    _walk_inventory,
    list_outcomes,
    describe_outcome,
    plan_outcome,
    run_script_outcome,
)


def metadata_root(tmp_path, *, outcome="repo-mapper"):
    root = tmp_path / "metadata"
    registry = root / "registry/declared_outcome_owners.json"
    registry.parent.mkdir(parents=True)
    registry.write_text(
        json.dumps(
            {
                "record_count": 1,
                "records": [
                    {
                        "kind": "script",
                        "owner": "sample",
                        "source_id": outcome,
                        "state": "implemented_verified",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    contracts = root / ".px/skills/sample/references/script-contracts.json"
    contracts.parent.mkdir(parents=True)
    contracts.write_text(
        json.dumps(
            {
                "contracts": [
                    {
                        "id": outcome,
                        "kind": "script",
                        "procedure": ["inspect"],
                        "failure_policy": "stop",
                        "recovery": "restore",
                        "evidence": ["receipt"],
                        "source_paths": ["declared.py"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return root


def test_nested_script_request_acquires_each_metadata_image_once(tmp_path, monkeypatch):
    root = metadata_root(tmp_path)
    target = tmp_path / "project"
    target.mkdir()
    (target / "a.txt").write_text("hello", encoding="utf-8")
    original = Path.open
    opens = []

    def counted(self, *args, **kwargs):
        if self.is_relative_to(root):
            opens.append(self.relative_to(root).as_posix())
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", counted)
    result = run_script_outcome(
        root, "repo-mapper", {"target": str(target), "constraints": {}}
    )
    assert result["valid"]
    assert opens.count("registry/declared_outcome_owners.json") == 1
    assert opens.count(".px/skills/sample/references/script-contracts.json") == 1
    assert result["result"]["files"][0]["path"] == "a.txt"


@pytest.mark.parametrize("minimum", [True, 0, "2", 10001])
def test_inventory_limit_is_actual_bounded_integer(tmp_path, minimum):
    with pytest.raises(ValueError):
        _walk_inventory(tmp_path, minimum)


def test_inventory_preflights_all_sizes_before_any_body(tmp_path, monkeypatch):
    (tmp_path / "a.txt").write_text("small", encoding="utf-8")
    with (tmp_path / "z.bin").open("wb") as stream:
        stream.truncate(8 * 1024 * 1024 + 1)
    original = Path.open

    def guarded(self, *args, **kwargs):
        if self.is_relative_to(tmp_path):
            pytest.fail("oversize inventory reached a body read")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded)
    with pytest.raises(ValueError):
        _walk_inventory(tmp_path, 10)


def test_inventory_rejects_descendant_junction(tmp_path):
    import os

    root = tmp_path / "project"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "external.txt").write_text("external", encoding="utf-8")
    linked = root / "linked"
    if os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(outside), str(linked))
    else:
        linked.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        _walk_inventory(root, 10)


def test_owner_locator_refuses_before_referenced_contract_read(tmp_path, monkeypatch):
    root = metadata_root(tmp_path)
    p = root / "registry/declared_outcome_owners.json"
    data = json.loads(p.read_text())
    data["records"][0]["owner"] = "../../escape"
    p.write_text(json.dumps(data))
    original = Path.open

    def guarded(self, *args, **kwargs):
        if self != p:
            pytest.fail("invalid owner reached a referenced path")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded)
    with pytest.raises(ValueError):
        describe_outcome(root, "script", "repo-mapper")


def test_duplicate_registry_identity_is_not_first_match(tmp_path):
    root = metadata_root(tmp_path)
    p = root / "registry/declared_outcome_owners.json"
    data = json.loads(p.read_text())
    data["records"] *= 2
    data["record_count"] = 2
    p.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        describe_outcome(root, "script", "repo-mapper")


@pytest.mark.parametrize("weight", [math.nan, math.inf, True, "1"])
def test_rank_weights_are_actual_finite_numbers(weight):
    with pytest.raises(ValueError):
        _rank(
            {
                "candidates": [{"id": "a", "metrics": {"quality": 1}}],
                "weights": {"quality": weight},
            }
        )


def test_rank_requires_nonempty_weights():
    with pytest.raises(ValueError):
        _rank({"candidates": [{"id": "a", "metrics": {}}], "weights": {}})


def test_rank_rejects_malformed_metrics_with_structured_refusal():
    with pytest.raises(ValueError):
        _rank(
            {"candidates": [{"id": "a", "metrics": "bad"}], "weights": {"quality": 1}}
        )


def test_rank_rejects_duplicate_candidate_ids():
    with pytest.raises(ValueError):
        _rank(
            {
                "candidates": [{"id": "a", "metrics": {"quality": 1}}] * 2,
                "weights": {"quality": 1},
            }
        )


@pytest.mark.parametrize(
    "value", [math.nan, math.inf, True], ids=["nan", "infinity", "boolean"]
)
def test_numeric_comparison_refuses_nonfinite_or_boolean_values(value):
    with pytest.raises(ValueError):
        _compare({"baseline": value, "candidate": 1})


def test_numeric_comparison_refuses_unrepresentable_delta():
    with pytest.raises(ValueError):
        _compare({"baseline": -1e308, "candidate": 1e308})


def test_scan_rejects_empty_literal_pattern():
    with pytest.raises(ValueError):
        _scan({"text": "abc", "patterns": [""]})


def test_scan_limits_raw_matches():
    with pytest.raises(ValueError):
        _scan({"text": "a" * 10001, "patterns": ["a"]})


def test_validation_field_names_are_actual_text():
    with pytest.raises(ValueError):
        _validate({"record": {}, "required": [1]})


def test_list_filter_is_not_an_opaque_value(tmp_path):
    root = metadata_root(tmp_path)
    with pytest.raises(ValueError):
        list_outcomes(root, kind={"script": True})


def test_planning_preserves_record_set_target(tmp_path):
    root = metadata_root(tmp_path)
    target = [{"id": "record"}]
    result = plan_outcome(
        root, "script", "repo-mapper", {"target": target, "constraints": {}}
    )
    assert result["valid"] and result["dry_run"]
    assert result["target"] == target


def test_literal_scan_preserves_whitespace_and_newline_patterns():
    result = _scan({"text": "a b\nc", "patterns": [" ", "\n"]})
    assert result["match_count"] == 2
    assert [(row["start"], row["end"]) for row in result["matches"]] == [(1, 2), (3, 4)]


def test_inventory_preserves_exact_content_hash(tmp_path):
    import hashlib

    raw = b"alpha\r\nbeta\x00"
    (tmp_path / "a.bin").write_bytes(raw)
    assert _walk_inventory(tmp_path, 10) == [
        {"path": "a.bin", "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    ]


def test_independent_requests_observe_new_contract_metadata(tmp_path):
    root = metadata_root(tmp_path)
    first = describe_outcome(root, "script", "repo-mapper")
    p = root / ".px/skills/sample/references/script-contracts.json"
    data = json.loads(p.read_text())
    data["contracts"][0]["recovery"] = "new recovery\nsecond line"
    p.write_text(json.dumps(data))
    second = describe_outcome(root, "script", "repo-mapper")
    assert first["contract"]["recovery"] == "restore"
    assert second["contract"]["recovery"] == "new recovery\nsecond line"


def test_failed_request_does_not_leak_its_root_into_another_request(tmp_path):
    first = metadata_root(tmp_path / "first")
    second = metadata_root(tmp_path / "second")
    p = first / "registry/declared_outcome_owners.json"
    data = json.loads(p.read_text())
    data["records"][0]["owner"] = "../bad"
    p.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        describe_outcome(first, "script", "repo-mapper")
    assert describe_outcome(second, "script", "repo-mapper")["valid"]


def test_duplicate_contract_identity_refuses_before_selection(tmp_path):
    root = metadata_root(tmp_path)
    p = root / ".px/skills/sample/references/script-contracts.json"
    data = json.loads(p.read_text())
    data["contracts"] *= 2
    p.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        describe_outcome(root, "script", "repo-mapper")


def test_duplicate_json_keys_are_not_last_wins(tmp_path):
    root = metadata_root(tmp_path)
    p = root / "registry/declared_outcome_owners.json"
    p.write_text(
        p.read_text().replace(
            '"record_count": 1', '"record_count": 1, "record_count": 1'
        )
    )
    with pytest.raises(ValueError):
        list_outcomes(root)


def test_oversized_metadata_image_refuses_before_body_open(tmp_path, monkeypatch):
    root = metadata_root(tmp_path)
    p = root / "registry/declared_outcome_owners.json"
    p.write_text(p.read_text() + " " * (1024 * 1024))
    original = Path.open

    def guarded(self, *args, **kwargs):
        if self == p:
            pytest.fail("oversized metadata image reached body acquisition")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded)
    with pytest.raises(ValueError):
        list_outcomes(root)


def test_invalid_inventory_limit_refuses_before_metadata_read(tmp_path, monkeypatch):
    root = metadata_root(tmp_path)
    original = Path.open

    def guarded(self, *args, **kwargs):
        if self.is_relative_to(root):
            pytest.fail("invalid inventory limit reached metadata acquisition")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded)
    with pytest.raises(ValueError):
        run_script_outcome(
            root,
            "repo-mapper",
            {"target": str(tmp_path), "constraints": {}, "maximum_files": True},
        )


def test_planning_preserves_original_json_hash_framing(tmp_path):
    import hashlib

    root = metadata_root(tmp_path)
    payload = {"target": [{"id": "é"}], "constraints": {"note": "a\r\nb"}}
    report = plan_outcome(root, "script", "repo-mapper", payload)
    expected = hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode()
    ).hexdigest()
    assert report["request_sha256"] == expected


def test_whole_suite_uses_one_image_per_metadata_file(monkeypatch):
    from runtime.declared_suite import validate_declared_suite

    root = Path(__file__).resolve().parents[1]
    original = Path.open
    opens = []

    def counted(self, *args, **kwargs):
        if self.is_relative_to(root) and (
            self.name
            in {
                "declared_outcome_owners.json",
                "declared-suite.yaml",
                "capability-contracts.json",
                "script-contracts.json",
            }
        ):
            opens.append(self.relative_to(root).as_posix())
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", counted)
    report = validate_declared_suite(root)
    assert report["valid"] and report["outcomes"] == 257
    assert len(opens) == len(set(opens)) == 16
