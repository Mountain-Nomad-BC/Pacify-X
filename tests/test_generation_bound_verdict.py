from pathlib import Path
import shutil

import pytest
import runtime.generation_bound_verdict as owner


def verdict(**changes):
    args = dict(candidate_sha256="a" * 64, dependencies={"source": "b" * 64},
                verifier_revision="controlled-verifier-v1", evidence_sha256=["c" * 64], status="PASS")
    args.update(changes)
    return owner.create_verdict(**args)


def test_current_verdict_is_bound_to_candidate_and_exact_dependencies():
    row = verdict()
    assert row["authority_granted"] is False
    assert owner.verdict_is_current(row, "a" * 64, {"source": "b" * 64})
    assert not owner.verdict_is_current(row, "d" * 64, {"source": "b" * 64})
    assert not owner.verdict_is_current(row, "a" * 64, {"source": "d" * 64})
    assert not owner.verdict_is_current({**row, "status": "FAIL"}, "a" * 64, {"source": "b" * 64})


def test_failed_verdict_can_be_current_without_becoming_a_pass():
    row = verdict(status="FAIL")
    assert owner.verdict_is_current(row, "a" * 64, {"source": "b" * 64})
    assert row["status"] == "FAIL"


@pytest.mark.parametrize("changes", [{"dependencies": {}}, {"candidate_sha256": "latest"},
    {"evidence_sha256": []}, {"status": "success"}, {"verifier_revision": ""}])
def test_malformed_verdict_is_refused(changes):
    with pytest.raises(ValueError):
        verdict(**changes)


def test_schema_resolves_from_framework_asset_owner_in_lean_layout(tmp_path, monkeypatch):
    assets = tmp_path / "installed-share"
    schema = assets / "contracts/models/generation-bound-verdict.schema.json"
    schema.parent.mkdir(parents=True)
    shutil.copyfile(Path(__file__).resolve().parents[1] / "contracts/models/generation-bound-verdict.schema.json", schema)
    monkeypatch.setattr(owner, "framework_root", lambda: assets)
    assert verdict()["status"] == "PASS"


def test_schema_name_cannot_escape_the_contract_owner():
    with pytest.raises(ValueError, match="schema name"):
        owner.validate_record({}, "../../outside")
