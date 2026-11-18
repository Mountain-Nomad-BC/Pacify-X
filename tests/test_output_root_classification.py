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


def _observe(tmp_path: Path, producer: str = "p.py", *, confined: bool = True, escapes: list | None = None) -> None:
    """Record a sandbox observation for `producer`, as the evidence harness would."""
    import hashlib

    evidence = tmp_path / "docs/repair/evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    document = {
        "cases": [
            {
                "producer": producer,
                "observed_confined": confined,
                "escaping_paths": escapes or [],
                "observed_source_sha256": hashlib.sha256(
                    (tmp_path / producer).read_bytes()
                ).hexdigest(),
            }
        ]
    }
    (evidence / "px-os-1067-sandbox-evidence.json").write_text(
        json.dumps(document), encoding="utf-8"
    )


def test_a_granted_destination_resolves_the_producer(tmp_path: Path) -> None:
    root = _root(tmp_path, [_grant("p.py")], ROOTS)
    (tmp_path / "p.py").write_text("from pathlib import Path\nPath('build/x').write_text('a')\n")
    _observe(tmp_path)
    verdict = output_root_verdict(root, "p.py", ("filesystem_mutation",))
    assert verdict == {"classification": "exempt", "reason": "authorized_output_root"}


def test_without_an_observation_a_grant_alone_never_resolves(tmp_path: Path) -> None:
    """A grant says where a producer may write; an observation says where it did."""
    root = _root(tmp_path, [_grant("p.py")], ROOTS)
    (tmp_path / "p.py").write_text("from pathlib import Path\nPath('build/x').write_text('a')\n")
    assert output_root_verdict(root, "p.py", ("filesystem_mutation",)) is None


def test_an_observation_of_other_bytes_does_not_vouch(tmp_path: Path) -> None:
    root = _root(tmp_path, [_grant("p.py")], ROOTS)
    (tmp_path / "p.py").write_text("from pathlib import Path\nPath('build/x').write_text('a')\n")
    _observe(tmp_path)
    (tmp_path / "p.py").write_text("from pathlib import Path\nPath('build/y').write_text('b')\n")
    assert output_root_verdict(root, "p.py", ("filesystem_mutation",)) is None


def test_an_observation_that_escaped_does_not_vouch(tmp_path: Path) -> None:
    root = _root(tmp_path, [_grant("p.py")], ROOTS)
    (tmp_path / "p.py").write_text("from pathlib import Path\nPath('build/x').write_text('a')\n")
    _observe(tmp_path, escapes=["../escape.json"])
    assert output_root_verdict(root, "p.py", ("filesystem_mutation",)) is None


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


def test_a_local_publisher_named_publish_json_is_not_the_confinement_helper(tmp_path: Path) -> None:
    """Session 7 regression: `publish_json` in the source text is not proof of confinement.

    The destination emitter treated *any* file containing the token `publish_json` as fully
    confined, so a module that defines its own publisher of that name was credited with a
    guarantee it does not have. Only a real call to the canonical helper may do that.
    """
    from runtime.output_root_classification import produced_destinations

    producer = tmp_path / "producer.py"
    producer.write_text(
        "import json\n\n"
        "def publish_json(path, payload):\n"
        "    path.write_text(json.dumps(payload))\n\n"
        "def main():\n"
        "    publish_json(somewhere_else, {})\n",
        encoding="utf-8",
    )
    assert produced_destinations(tmp_path, "producer.py") != [
        "CONFINED_REPOSITORY_ROOT_DESTINATION"
    ]


def test_the_canonical_helper_is_still_recognised(tmp_path: Path) -> None:
    from runtime.output_root_classification import produced_destinations

    (tmp_path / "producer.py").write_text(
        "from runtime.confined_output import publish_json\n\n"
        "def main(argv):\n"
        "    publish_json(ROOT, argv[1], {})\n",
        encoding="utf-8",
    )
    assert produced_destinations(tmp_path, "producer.py") == [
        "CONFINED_REPOSITORY_ROOT_DESTINATION"
    ]


def test_a_read_only_handle_is_not_a_write_destination(tmp_path: Path) -> None:
    """`f = open('p','rb')` names no destination; only the write through it does."""
    from runtime.output_root_classification import produced_destinations

    (tmp_path / "producer.py").write_text(
        "def read(path):\n"
        "    f = open('p', 'rb')\n"
        "    return f.read()\n",
        encoding="utf-8",
    )
    assert produced_destinations(tmp_path, "producer.py") == []


def test_importing_the_helper_does_not_confine_every_destination(tmp_path):
    """Defect 5: importing `publish_json` was treated as routing every destination through it.

    A producer that imports the canonical publisher *and* performs an unrelated direct write
    publishes only through the helper; the direct write still names its own, unreviewed
    destination. Confinement is per call, never per import.
    """
    from runtime.output_root_classification import produced_destinations

    (tmp_path / "producer.py").write_text(
        "from runtime.confined_output import publish_json\n"
        "def run(root, caller_destination, stale_path):\n"
        "    publish_json(root, caller_destination, {})\n"
        "    stale_path.write_text('direct, unconfined')\n",
        encoding="utf-8",
    )
    destinations = produced_destinations(tmp_path, "producer.py")
    # The helper call is confined; the direct write is reported as its own, unresolvable
    # destination. Reading the rows first is deliberate: the direct write's *kind* is
    # UNRESOLVED_RELATIVE_TO_PROCESS_CWD because `stale_path` is a parameter, and what
    # matters here is that it is not credited as confined.
    assert "UNRESOLVED_RELATIVE_TO_PROCESS_CWD" in destinations
    assert destinations != ["CONFINED_REPOSITORY_ROOT_DESTINATION"]


def test_unused_canonical_import_does_not_confine_an_independent_write(tmp_path):
    from runtime.output_root_classification import produced_destinations
    (tmp_path / 'producer.py').write_text(
        "from runtime.confined_output import publish_json\n"
        "def run(destination):\n    destination.write_text('unconfined')\n", encoding='utf-8')
    destinations = produced_destinations(tmp_path, 'producer.py')
    assert destinations and 'CONFINED_REPOSITORY_ROOT_DESTINATION' not in destinations
