"""Phase 1C â€” the canonical mutating-producer registry classifies every producer.

These tests prove the fail-closed contract of ``runtime.mutating_producer_registry``:
every discovered mutating producer is classified as leased or exempt-with-reason,
and any new unclassified producer is refused rather than silently allowed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.mutating_producer_registry import (
    EXEMPTION_REASONS,
    MutatingProducerError,
    build_registry,
    discover_mutating_producers,
    publish_registry,
    validate_registry,
)

ROOT = Path(__file__).resolve().parents[1]


def test_published_registry_is_valid():
    result = validate_registry(ROOT)
    assert result["valid"] is True, result["errors"]
    assert result["stale_entries"] == []


def test_every_discovered_producer_is_classified():
    built = build_registry(ROOT)
    assert built["unclassified"] == []
    assert built["producers"]


def test_every_classification_uses_a_proven_reason():
    built = build_registry(ROOT)
    for relative, entry in built["producers"].items():
        assert entry["classification"] in {"leased", "exempt"}, relative
        assert entry["reason"] in EXEMPTION_REASONS, relative


def test_unclassified_producer_fails_closed(tmp_path):
    # A temp module that mutates state and has no structural classification.
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    probe = runtime_dir / "unclassified_producer.py"
    probe.write_text(
        "from pathlib import Path\n"
        "def run(p: Path) -> None:\n"
        "    p.write_text('x')\n", encoding="utf-8")
    result = validate_registry(tmp_path)
    assert result["valid"] is False
    assert any("unclassified_producer" in error for error in result["errors"])
    with pytest.raises(MutatingProducerError, match="unclassified"):
        publish_registry(tmp_path)
    assert not (tmp_path / "registry/mutating_producers.json").exists()


def test_discovery_matches_effect_surface_owner():
    producers = discover_mutating_producers(ROOT)
    # The canonical lease/intent owners are always present on a real tree.
    assert "runtime/scope_lease.py" in producers
    assert "runtime/effect_intent.py" in producers