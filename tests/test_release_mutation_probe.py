from pathlib import Path

from runtime.release_preflight import mutation_probe


def test_mutation_probe_names_exact_polluting_path(tmp_path: Path) -> None:
    (tmp_path / "runtime").mkdir()
    (tmp_path / "runtime/a.py").write_text("x=1\n")
    result = mutation_probe(
        tmp_path, (lambda root: (root / "runtime/a.py").write_text("x=2\n"),)
    )
    assert not result["valid"]
    assert result["diff"]["changed"] == ["runtime/a.py"]
    assert result["failures"][0]["code"] == "RP-MUT-001"


def test_read_only_mutation_probe_is_stable(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("stable\n")
    assert mutation_probe(tmp_path, (lambda root: (root / "a.txt").read_bytes(),))[
        "valid"
    ]
