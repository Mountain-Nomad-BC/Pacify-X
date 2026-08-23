from pathlib import Path

from runtime.release_preflight import fixed_point


def test_fixed_point_accepts_unchanged_second_pass(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "registry/a.json"; target.parent.mkdir(); target.write_text("{}\n")
    monkeypatch.setattr("scripts.clean_source_export._rebuild_candidate_projections", lambda root: None)
    result = fixed_point(tmp_path, ["registry/a.json"])
    assert result["valid"] and result["pass_1_digest"] == result["pass_2_digest"]


def test_fixed_point_rejects_second_pass_change(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "registry/a.json"; target.parent.mkdir(); target.write_text("0")
    calls = {"count": 0}
    def rebuild(root: Path) -> None:
        calls["count"] += 1; (root / "registry/a.json").write_text(str(calls["count"]))
    monkeypatch.setattr("scripts.clean_source_export._rebuild_candidate_projections", rebuild)
    result = fixed_point(tmp_path, ["registry/a.json"])
    assert not result["valid"] and result["failures"][0]["code"] == "RP-FIX-001"
