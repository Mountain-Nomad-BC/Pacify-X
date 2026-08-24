from pathlib import Path

from runtime.release_preflight import evidence_portability


def test_machine_local_release_evidence_fails_preflight(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "installed.json").write_text(
        '{"python":"C:\\\\Python314\\\\python.exe"}'
    )
    result = evidence_portability(tmp_path)
    assert not result["valid"]
    assert result["failures"][0]["code"] == "RP-EVD-001"


def test_portable_release_evidence_passes(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "installed.json").write_text('{"python":"[release-python]"}')
    assert evidence_portability(tmp_path)["valid"]
