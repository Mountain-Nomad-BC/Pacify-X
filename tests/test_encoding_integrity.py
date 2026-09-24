"""Tests for the text/encoding integrity gate.

Promoted from the temporary BOM audit that found a real defect during this campaign. The gate must
catch encoded corruption in both directions: a BOM or a parse failure must be reported, and an
intentionally invalid fixture or a documented historical-evidence file must not be.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

import scripts.verify_encoding_integrity as encoding  # noqa: E402

ROOT = Path(__file__).parents[1]
BOM = b"\xef\xbb\xbf"


def test_gate_is_clean_on_the_real_tree() -> None:
    result = encoding.verify(ROOT)
    assert result["valid"], result["findings"]


def test_bom_is_detected() -> None:
    assert "utf-8-bom" in encoding._check_bytes(BOM + b'{"a": 1}\n')


def test_clean_utf8_passes_byte_check() -> None:
    assert encoding._check_bytes(b'{"a": 1}\n') == []


def test_invalid_utf8_is_detected() -> None:
    problems = encoding._check_bytes(b"abc\xff\xfe")
    assert any(p.startswith("invalid-utf-8") for p in problems)


def test_nul_byte_is_treated_as_corruption() -> None:
    problems = encoding._check_bytes(b"abc\x00def")
    assert any(p.startswith("control-byte") for p in problems)


def test_replacement_character_is_detected() -> None:
    assert "replacement-character" in encoding._check_bytes(
        "broken \ufffd here".encode("utf-8")
    )


def test_json_parse_failure_is_detected(tmp_path: Path) -> None:
    path = tmp_path / "x.json"
    path.write_text("{not json", encoding="utf-8")
    assert any(
        "json-parse-failure" in p for p in encoding._check_parse(path, "{not json")
    )


def test_python_ast_failure_is_detected(tmp_path: Path) -> None:
    path = tmp_path / "x.py"
    assert any(
        "python-ast-failure" in p for p in encoding._check_parse(path, "def (:\n")
    )


def test_toml_parse_failure_is_detected(tmp_path: Path) -> None:
    path = tmp_path / "x.toml"
    assert any(
        "toml-parse-failure" in p for p in encoding._check_parse(path, "= broken")
    )


def test_valid_parses_are_clean(tmp_path: Path) -> None:
    assert encoding._check_parse(tmp_path / "a.json", '{"a": 1}') == []
    assert encoding._check_parse(tmp_path / "a.py", "x = 1\n") == []
    assert encoding._check_parse(tmp_path / "a.toml", "a = 1\n") == []


# ---------------------------------------------------------------------------
# Allowlists must be visible, narrow, and correct
# ---------------------------------------------------------------------------


def test_intentional_invalid_fixture_is_allowlisted_not_silently_skipped() -> None:
    result = encoding.verify(ROOT)
    allowlisted_paths = {
        entry["path"] for entry in result["allowlisted_historical_evidence"]
    }
    fixture = "tests/fixtures/semantic_code/python_project/broken.py"
    assert fixture in allowlisted_paths
    # It must be recorded with its classification, not omitted.
    entry = next(
        e for e in result["allowlisted_historical_evidence"] if e["path"] == fixture
    )
    assert entry["classification"] == "intentional_invalid_fixture"


def test_historical_evidence_allowlist_is_exact_paths_only() -> None:
    # A broad pattern would hide real defects; the allowlist must be precise file paths.
    for entry in encoding.HISTORICAL_EVIDENCE_ALLOWLIST:
        assert entry.endswith((".json", ".md"))
        assert "*" not in entry
    for entry in encoding.INTENTIONAL_INVALID_ALLOWLIST:
        assert entry.endswith(".py")
        assert "*" not in entry


def test_a_bom_in_a_synthetic_tree_is_a_finding(tmp_path: Path) -> None:
    target = tmp_path / "runtime"
    target.mkdir(parents=True, exist_ok=True)
    (target / "mod.py").write_bytes(BOM + b"x = 1\n")
    result = encoding.verify(tmp_path)
    assert result["valid"] is False
    assert any(f["path"] == "runtime/mod.py" for f in result["findings"])


def test_scanned_file_count_is_substantial() -> None:
    # A gate that scans almost nothing is not a gate.
    result = encoding.verify(ROOT)
    assert result["files_scanned"] > 1000
