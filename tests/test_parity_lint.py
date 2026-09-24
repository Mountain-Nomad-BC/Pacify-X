from __future__ import annotations

from runtime.parity_lint import compare_identifier_sets, compare_projection_revisions, find_dead_references, parity_summary


def test_parity_findings_have_stable_ids() -> None:
    first = compare_identifier_sets(("a", "b"), ("a",), left_name="owner", right_name="projection")
    second = compare_identifier_sets(("b", "a"), ("a",), left_name="owner", right_name="projection")
    assert first == second
    assert first[0].finding_id.startswith("missing_right:")


def test_stale_projection_is_high_severity() -> None:
    findings = compare_projection_revisions({"a": "r2"}, {"a": "r1"})
    assert findings[0].kind == "stale_projection"
    assert findings[0].severity == "high"
    assert parity_summary(findings)["valid"] is False
    assert parity_summary(findings)["authority_granted"] is False


def test_dead_references_are_deterministic() -> None:
    findings = find_dead_references(("a",), (("a", "links", "b"),))
    assert len(findings) == 1
    assert findings[0].kind == "dead_target"
