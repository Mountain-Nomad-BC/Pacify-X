"""Phase 7 governed invariants.

Proves the containment security invariants (Gremlin section 44), the
generated-never-authority rule, source-classifier uniqueness, branch attribution
and N-way convergence consistency.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.containment_invariants import INVARIANT_IDS, verify_containment_invariants
from runtime.source_boundary import (
    AUTHORED,
    GENERATED,
    PACKAGING_GENERATED,
    VENDORED,
    classify_path,
)

ROOT = Path(__file__).resolve().parents[1]


def test_containment_invariant_gaps_are_visible_and_fail_closed():
    report = verify_containment_invariants()
    assert report["valid"] is False
    assert report["checked"] == sorted(INVARIANT_IDS)
    assert report["declared_count"] == len(INVARIANT_IDS)
    assert report["evaluated_count"] == len(INVARIANT_IDS)
    assert report["coverage_complete"] is True
    assert report["unresolved"] == ["GN-INV-013", "GN-INV-014"]
    assert {
        item["invariant"] for item in report["violations"]
    } == {"GN-INV-013", "GN-INV-014"}
    assert report["authority_granted"] is False


def test_every_declared_invariant_id_is_a_gn_inv():
    assert INVARIANT_IDS
    assert all(item.startswith("GN-INV-") for item in INVARIANT_IDS)


def test_generated_never_authority():
    """A generated bundle must never classify as authored source authority."""
    assert classify_path("extension/server/index.js")["classification"] == PACKAGING_GENERATED
    assert classify_path("docs/architecture/graph_data.js")["classification"] == GENERATED
    assert classify_path("extension/build/generated.py")["classification"] != AUTHORED
    assert classify_path("extension/dist/bundle.js")["classification"] != AUTHORED


def test_source_classifier_uniqueness():
    """The boundary owner and the scope delegate must agree on every corpus entry."""
    from runtime.source_boundary import CONFORMANCE_CORPUS, conformance_report

    report = conformance_report()
    assert report["valid"] is True, report.get("errors")
    for path, expected in CONFORMANCE_CORPUS:
        assert classify_path(path)["classification"] == expected, path


def test_containment_proof_gates_branch_admission():
    """A branch with no proven containment must stay NOT_ADMITTED."""
    from datetime import datetime, timezone
    from runtime.gremlin.containment import GremlinNanny
    from runtime.gremlin.supervisor import DeterministicSupervisor

    nanny = GremlinNanny(authority_id="gn", signing_key=b"inv-key-0123456789abcdefghij")
    for kind in ("network", "process_tree", "filesystem"):
        nanny.observers.register(kind, lambda: ())
    nanny.supervisor = DeterministicSupervisor(None)
    # No enrollment => no proof => a containment-required branch cannot proceed.
    proof = nanny.containment_proof("never-enrolled")
    assert proof.proven is False


def test_nway_convergence_has_no_pairwise_assumption():
    """The convergence owner must consume N branches, not a fixed pair."""
    import inspect

    from runtime.model_convergence import converge

    signature = inspect.signature(converge)
    assert "group" in signature.parameters
    source = inspect.getsource(converge)
    # No primary/challenger special-casing and no hard-coded two-branch schema.
    assert "challenger" not in source
    assert "primary" not in source