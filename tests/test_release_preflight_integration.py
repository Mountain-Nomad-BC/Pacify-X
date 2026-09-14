"""Owned consumer, wrapper and metadata-boundary proof for release input checks."""
import importlib
import json
import os
from pathlib import Path
import sys

import pytest

from runtime import release_preflight as owner
from tests.test_release_preflight_inputs import policy, product


def configured(root):
    root = product(root)
    (root / "policies/release-preflight.json").write_text(
        json.dumps({**policy(), "post_certification_writes": ["evidence/out.json"]}), encoding="utf-8"
    )
    return root


@pytest.mark.parametrize("module", ["release_feedback_audit", "release_evidence_budget", "release_evidence_portability"])
def test_existing_cli_entrypoints_report_valid_owned_fixture_results(tmp_path, monkeypatch, capsys, module):
    root = configured(tmp_path)
    entry = importlib.import_module("scripts." + module)
    monkeypatch.setattr(sys, "argv", [module, "--root", str(root)])
    assert entry.main() == 0
    assert json.loads(capsys.readouterr().out)["valid"] is True


@pytest.mark.parametrize("module", ["release_feedback_audit", "release_evidence_budget", "release_evidence_portability"])
def test_cli_preserves_original_root_validation_before_normalization(tmp_path, monkeypatch, capsys, module):
    root = configured(tmp_path)
    (root / "child").mkdir()
    entry = importlib.import_module("scripts." + module)

    def forbidden(*args, **kwargs):
        raise AssertionError("original root must be refused before any audit consumer")

    monkeypatch.setattr(entry, module.removeprefix("release_") if module != "release_feedback_audit" else "feedback_audit", forbidden)
    monkeypatch.setattr(sys, "argv", [module, "--root", str(root / "child" / "..")])
    assert entry.main() == 2
    assert json.loads(capsys.readouterr().out)["valid"] is False


@pytest.mark.parametrize("payload", [
    b'{"schema_version":"future"}',
    b'{"schema_version":"px.release-preflight-policy/1.0","schema_version":"px.release-preflight-policy/1.0"}',
    b'[]', b'{"schema_version":"px.release-preflight-policy/1.0","n":NaN}',
], ids=["version", "duplicate", "array", "nonfinite"])
def test_disk_policy_is_strict_bounded_json(tmp_path, payload):
    root = configured(tmp_path)
    (root / "policies/release-preflight.json").write_bytes(payload)
    with pytest.raises(ValueError):
        owner.load_preflight_input_policy(root)


def test_oversized_disk_policy_is_refused_before_open(tmp_path, monkeypatch):
    root = configured(tmp_path)
    path = root / "policies/release-preflight.json"
    with path.open("wb") as stream:
        stream.truncate(1024 * 1024 + 1)
    original = Path.open

    def checked(candidate, *args, **kwargs):
        assert candidate != path, "oversized policy body was opened"
        return original(candidate, *args, **kwargs)

    monkeypatch.setattr(Path, "open", checked)
    with pytest.raises(ValueError):
        owner.load_preflight_input_policy(root)


def test_total_evidence_budget_precedes_any_selected_body(tmp_path, monkeypatch):
    root = configured(tmp_path)
    limits = {**policy(), "max_total_release_evidence_bytes": 3, "max_single_evidence_file_bytes": 2}
    (root / "policies/release-preflight.json").write_text(json.dumps(limits), encoding="utf-8")
    (root / "evidence/second.json").write_bytes(b"{}")
    original = Path.open

    def checked(candidate, *args, **kwargs):
        assert not candidate.is_relative_to(root / "evidence"), "body acquired before total-byte admission"
        return original(candidate, *args, **kwargs)

    monkeypatch.setattr(Path, "open", checked)
    result = owner.evidence_portability(root)
    assert result["valid"] is False and result["finding_count"] is None
    assert result["byte_budget"]["total_bytes"] == 4


def test_shallow_evidence_does_not_descend_into_unselected_directories(tmp_path, monkeypatch):
    root = configured(tmp_path)
    ignored = root / "evidence/old"
    ignored.mkdir()
    (ignored / "old.json").write_text('{"path":"C:/ignored"}', encoding="utf-8")
    original = os.scandir

    def checked(candidate):
        assert Path(candidate) != ignored, "unselected shallow evidence subtree was enumerated"
        return original(candidate)

    monkeypatch.setattr(os, "scandir", checked)
    assert owner.evidence_portability(root)["valid"] is True


def test_versioned_evidence_selects_only_current_transaction_and_installed_shallow_files(tmp_path, monkeypatch):
    root = configured(tmp_path)
    (root / "pyproject.toml").write_text('[project]\nversion="1.2.3"\n', encoding="utf-8")
    current = root / "evidence/releases/1.2.3/nested"
    current.mkdir(parents=True)
    (current / "current.json").write_text('{"path":"C:/current"}', encoding="utf-8")
    old = root / "evidence/releases/1.2.2"
    old.mkdir()
    (old / "old.json").write_text('{"path":"C:/old"}', encoding="utf-8")
    installed = root / "extension/evidence"
    installed.mkdir(parents=True)
    (installed / "installed.json").write_text('{"path":"C:/installed"}', encoding="utf-8")
    original = os.scandir

    def checked(candidate):
        assert Path(candidate) != old, "historical release evidence was enumerated"
        return original(candidate)

    monkeypatch.setattr(os, "scandir", checked)
    result = owner.evidence_portability(root)
    assert result["valid"] is False and result["scan_complete"] is True
    assert {row["path"] for row in result["findings"]} == {
        "evidence/releases/1.2.3/nested/current.json", "extension/evidence/installed.json"
    }


def test_actual_portability_consumer_honors_the_existing_hundred_mib_policy(tmp_path):
    root = configured(tmp_path)
    limits = {**policy(), "max_total_release_evidence_bytes": 250 * 1024**2, "max_single_evidence_file_bytes": 100 * 1024**2}
    (root / "policies/release-preflight.json").write_text(json.dumps(limits), encoding="utf-8")
    path = root / "evidence/large.log"
    with path.open("wb") as stream:
        stream.truncate(65 * 1024**2)
        stream.seek(-32, 2)
        stream.write(b'"C:/fixture/near-eof.json"' + b" " * 7)
    result = owner.evidence_portability(root)
    assert result["scan_complete"] is True
    assert result["findings"] == [{"path": "evidence/large.log", "locator": "C:/fixture/near-eof.json"}]


def test_existing_entry_admission_stops_before_effects(tmp_path, monkeypatch):
    from tests import test_release_preflight as existing

    existing.test_preflight_admission_uses_installed_operational_certify_boundary(tmp_path, monkeypatch)
    existing.test_unbound_discovery_bypasses_certification_stage_admission(tmp_path, monkeypatch)


@pytest.mark.parametrize("bad", ["not-list", "negative-size", "boolean-size", "bad-hash", "duplicate"])
def test_consumed_product_metadata_cannot_fake_a_valid_classifier(tmp_path, monkeypatch, bad):
    root = configured(tmp_path)
    result = owner.classify_tree(root)
    if bad == "not-list":
        result["product_records"] = "not records"
    elif bad == "negative-size":
        result["product_records"][0]["size"] = -1
    elif bad == "boolean-size":
        result["product_records"][0]["size"] = True
    elif bad == "bad-hash":
        result["product_records"][0]["sha256"] = "claimed"
    else:
        result["product_records"].append(dict(result["product_records"][0]))
    monkeypatch.setattr(owner, "classify_tree", lambda _: result)
    assert owner.feedback_audit(root, ["evidence/out.json"])["valid"] is False
