"""Output-root classification: grants must be all-destinations, never one.

The retired `reports/` grant failed because a caller-directed path did not establish an
authorized destination. These tests pin the fail-closed behaviour now that grants are
actually consulted by classification.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.output_root_classification import output_root_verdict

REGISTRY = "registry/producer_output_roots.json"


def _root(tmp_path: Path, grants: list[dict], roots: dict) -> Path:
    (tmp_path / "registry").mkdir(parents=True)
    (tmp_path / REGISTRY).write_text(
        json.dumps(
            {
                "schema_version": "px.producer-output-roots/1.0",
                "roots": roots,
                "grants": grants,
            }
        ),
        encoding="utf-8",
    )
    return tmp_path


def _grant(producer: str, digest: str = "0" * 64, root: str = "build") -> dict:
    return {
        "producer": producer,
        "root": root,
        "write_class": "default",
        "source_sha256": digest,
        "status": "active",
    }


ROOTS = {
    "build": {
        "owner": "release",
        "granted_by": "owner",
        "granted_at": "2026-11-03",
        "retention": "run-scoped",
        "invocation_model": "caller",
    }
}


def test_no_grants_means_nothing_resolves(tmp_path: Path) -> None:
    root = _root(tmp_path, [], {})
    (tmp_path / "p.py").write_text("from pathlib import Path\nBUILD = 'build'\nPath('build/x').write_text('a')\n")
    assert output_root_verdict(root, "p.py", ("filesystem_mutation",)) is None


def test_a_granted_destination_resolves_the_producer(tmp_path: Path) -> None:
    root = _root(tmp_path, [_grant("p.py")], ROOTS)
    (tmp_path / "p.py").write_text("from pathlib import Path\nPath('build/x').write_text('a')\n")
    verdict = output_root_verdict(root, "p.py", ("filesystem_mutation",))
    assert verdict == {"classification": "exempt", "reason": "authorized_output_root"}


def test_one_granted_destination_does_not_authorize_another(tmp_path: Path) -> None:
    """The decisive B8 rule: a second ungranted destination keeps the producer unresolved."""
    root = _root(tmp_path, [_grant("p.py")], ROOTS)
    (tmp_path / "p.py").write_text(
        "from pathlib import Path\n"
        "Path('build/ok').write_text('a')\n"
        "Path('outside/escape').write_text('b')\n"
    )
    assert output_root_verdict(root, "p.py", ("filesystem_mutation",)) is None


def test_the_root_itself_is_not_contained_in_itself(tmp_path: Path) -> None:
    root = _root(tmp_path, [_grant("p.py")], ROOTS)
    (tmp_path / "p.py").write_text("from pathlib import Path\nPath('build').write_text('a')\n")
    assert output_root_verdict(root, "p.py", ("filesystem_mutation",)) is None


def test_revoked_grants_do_not_resolve(tmp_path: Path) -> None:
    grant = _grant("p.py")
    grant["status"] = "revoked"
    root = _root(tmp_path, [grant], ROOTS)
    (tmp_path / "p.py").write_text("from pathlib import Path\nPath('build/x').write_text('a')\n")
    assert output_root_verdict(root, "p.py", ("filesystem_mutation",)) is None


def test_process_or_network_effects_are_not_covered(tmp_path: Path) -> None:
    root = _root(tmp_path, [_grant("p.py")], ROOTS)
    (tmp_path / "p.py").write_text("from pathlib import Path\nPath('build/x').write_text('a')\n")
    assert output_root_verdict(root, "p.py", ("filesystem_mutation", "process")) is None


def test_and_effect_is_copied_in_classification() -> None:
    """Import the real classifier to prove the wiring exists, not just the helper."""
    import inspect

    from runtime import mutating_producer_registry

    source = inspect.getsource(mutating_producer_registry.default_classification)
    assert "output_root_verdict" in source
    assert "authorized_output_root" in mutating_producer_registry.EXEMPTION_REASONS
