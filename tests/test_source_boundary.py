from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

"""PX-GAP-0007: the governed authored / generated / vendored source boundary.

These tests pin the machine-testable definition of the source boundary:
every classified generated artifact names an existing generator; no authored
source is misclassified; generated, vendored and evidence bytes are excluded
from the authored census; runtime-required generated artifacts stay functional;
engine identity is provably independent of the generated atlas; unbuilt rules
are deterministic and machine-readable; and repeated censuses are identical.
"""

from runtime.source_boundary import (
    ARTIFACT_SCHEMA,
    AUTHORED,
    EVIDENCE,
    GENERATED,
    GENERATED_ARTIFACTS,
    PACKAGING_GENERATED,
    RUNTIME_STATE,
    SourceBoundaryError,
    VENDORED,
    authored_paths,
    census,
    classify_path,
    unbuilt_profile,
    validate_artifacts,
    write_boundary,
    assert_generated_never_canonical_authority,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("kind,prefix", [("skill", ".px/skills"), ("workflow", "orchestration/workflows")])
def test_actual_experience_writer_does_not_change_authored_identity(tmp_path, kind, prefix):
    from runtime.engine_identity import build_engine_identity
    from runtime.semantic_surfaces import collect_corpus_snapshot
    from runtime.usage_memory import record_observation, read_stats, rebuild_stats

    definition = tmp_path / prefix / "actual-subject" / "definition.md"
    definition.parent.mkdir(parents=True)
    definition.write_text("# Actual subject\n", encoding="utf-8")
    before_identity = build_engine_identity(tmp_path)["tree_sha256"]
    before_binding = collect_corpus_snapshot(tmp_path).report()["source_binding_sha256"]
    record_observation(tmp_path, kind, "actual-subject", {"outcome": "success"})
    assert read_stats(tmp_path, kind, "actual-subject")["record_count"] == 1
    rebuild_stats(tmp_path, kind, "actual-subject")
    assert build_engine_identity(tmp_path)["tree_sha256"] == before_identity
    assert collect_corpus_snapshot(tmp_path).report()["source_binding_sha256"] == before_binding
    record_observation(tmp_path, kind, "actual-subject", {"outcome": "failure"})
    assert read_stats(tmp_path, kind, "actual-subject")["record_count"] == 2
    assert build_engine_identity(tmp_path)["tree_sha256"] == before_identity
    definition.write_text("# Changed definition\n", encoding="utf-8")
    assert build_engine_identity(tmp_path)["tree_sha256"] != before_identity
    assert collect_corpus_snapshot(tmp_path).report()["source_binding_sha256"] != before_binding


@pytest.mark.parametrize("relative", [
    "docs/memory/usage.jsonl", "orchestration/workflows/x/memory/notes.md",
    "orchestration/workflows/x/nested/memory/stats.json",
    "orchestration/workflows/INVALID/memory/usage.jsonl",
    ".px/skills/x/memory/.stats.json.invalid.prepared",
    "providers/agency_agents/agents/unknown/memory/usage.jsonl",
])
def test_unknown_experience_shaped_material_remains_authored(relative):
    assert classify_path(relative)["classification"] == AUTHORED


def test_owned_prepared_rollup_has_exact_writer_shape():
    relative = "orchestration/workflows/x/memory/.stats.json." + "a" * 32 + ".prepared"
    assert classify_path(relative)["classification"] == RUNTIME_STATE


def test_registered_agent_experience_ownership_uses_current_body_parent(tmp_path):
    from runtime.engine_identity import build_engine_identity
    from runtime.semantic_surfaces import collect_corpus_snapshot
    from runtime.usage_memory import record_observation

    body = tmp_path / "providers/agency_agents/agents/testing/actual.md"
    body.parent.mkdir(parents=True)
    body.write_text("# Actual agent\n", encoding="utf-8")
    registry = tmp_path / "registry/agency_agent_registry.json"
    registry.parent.mkdir()
    registry.write_text(json.dumps({"provider_id": "agency-agents", "agent_count": 1,
        "agents": [{"agent_id": "agency.testing.actual", "path": body.relative_to(tmp_path).as_posix()}]}))
    before = build_engine_identity(tmp_path)["tree_sha256"]
    binding = collect_corpus_snapshot(tmp_path).report()["source_binding_sha256"]
    record_observation(tmp_path, "agent", "agency.testing.actual", {"outcome": "success"})
    assert build_engine_identity(tmp_path)["tree_sha256"] == before
    report = collect_corpus_snapshot(tmp_path).report()
    assert report["source_binding_sha256"] == binding
    row = next(x for x in report["files"] if x["path"].endswith("memory/agency.testing.actual/usage.jsonl"))
    assert row["classification"] == RUNTIME_STATE
    unknown = tmp_path / "providers/agency_agents/agents/unknown/memory/usage.jsonl"
    unknown.parent.mkdir(parents=True)
    unknown.write_text("{}\n")
    assert build_engine_identity(tmp_path)["tree_sha256"] != before
    assert collect_corpus_snapshot(tmp_path).report()["source_binding_sha256"] != binding


@pytest.mark.parametrize("path", ["../outside.md", "providers/agency_agents/agents/../outside.md",
    "providers/agency_agents/agents/missing.md", "providers/agency_agents/agents/x.json"])
def test_invalid_registered_agent_path_excludes_no_experience(tmp_path, path):
    from runtime.source_boundary import agent_experience_directories
    registry = tmp_path / "registry/agency_agent_registry.json"
    registry.parent.mkdir()
    registry.write_text(json.dumps({"provider_id": "agency-agents", "agent_count": 1,
        "agents": [{"agent_id": "agency.test.actual", "path": path}]}))
    assert agent_experience_directories(tmp_path) == frozenset()


def test_duplicate_registry_keys_cannot_hide_experience(tmp_path):
    from runtime.source_boundary import agent_experience_directories
    registry = tmp_path / "registry/agency_agent_registry.json"
    registry.parent.mkdir()
    registry.write_text('{"provider_id":"agency-agents","agents":[],"agents":[],"agent_count":0}')
    assert agent_experience_directories(tmp_path) == frozenset()


@pytest.mark.parametrize("relative, expected", [
    ("registry/.operational-gap-ledger.lock", RUNTIME_STATE),
    ("extension/.engineering-bootstrap/resource-lifecycle/ledger.json.lock", RUNTIME_STATE),
    ("engineering_loop_bootstrap.egg-info/PKG-INFO", PACKAGING_GENERATED),
    ("extension/tests/generated/plugin-lifecycle/px-owned.fixture-1.0.0.vsix", GENERATED),
])
def test_traced_current_outputs_are_not_authored_source(relative, expected):
    assert classify_path(relative)["classification"] == expected


def test_ownership_corrections_do_not_hide_similarly_named_authored_material():
    for relative in ["registry/customer.lock", "docs/other.egg-info/notes.md",
                     "extension/tests/fixtures/plugin-lifecycle/package.json",
                     "extension/tests/generated/custom-authored.md"]:
        assert classify_path(relative)["classification"] == AUTHORED


def test_traced_output_changes_do_not_change_source_engine_identity(tmp_path):
    from runtime.engine_identity import build_engine_identity

    source = tmp_path / "runtime/owner.py"
    source.parent.mkdir(parents=True)
    source.write_text("owner = 1\n", encoding="utf-8")
    baseline = build_engine_identity(tmp_path)
    for relative in [
        "registry/.operational-gap-ledger.lock",
        "extension/.engineering-bootstrap/resource-lifecycle/ledger.json.lock",
        "engineering_loop_bootstrap.egg-info/PKG-INFO",
        "extension/tests/generated/plugin-lifecycle/receipt.json",
    ]:
        output = tmp_path / relative
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"current generated or mutable output")
    assert build_engine_identity(tmp_path) == baseline
    authored = tmp_path / "extension/tests/generated/custom-authored.md"
    authored.parent.mkdir(parents=True, exist_ok=True)
    authored.write_text("authored material", encoding="utf-8")
    assert build_engine_identity(tmp_path)["tree_sha256"] != baseline["tree_sha256"]


def test_every_generated_artifact_has_an_attributable_generator() -> None:
    report = validate_artifacts(REPO_ROOT)
    assert report["valid"], report["problems"]
    assert report["attributed"] == report["artifact_count"] == len(GENERATED_ARTIFACTS)
    for artifact in GENERATED_ARTIFACTS:
        assert artifact.generator.strip(), artifact.path
        assert (REPO_ROOT / artifact.generator_path).is_file(), artifact.generator_path


def test_generated_artifact_without_a_generator_fails_closed() -> None:
    """A generated entry with no resolvable generator must never be accepted."""
    import dataclasses

    import runtime.source_boundary as sb

    broken = dataclasses.replace(
        GENERATED_ARTIFACTS[0], generator_path="docs/architecture/tools/does_not_exist.py"
    )
    original = sb.GENERATED_ARTIFACTS
    try:
        sb.GENERATED_ARTIFACTS = (broken, *original[1:])
        report = sb.validate_artifacts(REPO_ROOT)
        assert report["valid"] is False
        assert any("does_not_exist" in problem for problem in report["problems"])
        with pytest.raises(sb.SourceBoundaryError):
            sb.write_boundary(REPO_ROOT)
    finally:
        sb.GENERATED_ARTIFACTS = original


def test_classification_is_correct_for_known_paths() -> None:
    assert classify_path("runtime/engine_identity.py")["classification"] == AUTHORED
    assert classify_path("extension/src/extension.js")["classification"] == AUTHORED
    assert classify_path("docs/architecture/ATLAS_OFFLINE.html")["classification"] == GENERATED
    assert classify_path("docs/architecture/data/complete_graph.json")["classification"] == GENERATED
    assert classify_path("docs/architecture/graph_data.js")["classification"] == GENERATED
    assert classify_path("extension/node_modules/zod/package.json")["classification"] == VENDORED
    assert (
        classify_path("registry/operational_gap_ledger.head.json")["classification"]
        == RUNTIME_STATE
    )
    assert (
        classify_path(".engineering-bootstrap/receipts/x/cleanup-receipt.json")["classification"]
        == EVIDENCE
    )


def test_dotted_directories_are_not_stripped_by_the_classifier() -> None:
    """Regression: str.lstrip('./') would eat the leading dot of a dotted dir."""
    assert classify_path(".engineering-bootstrap/receipts/a.json")["classification"] == EVIDENCE
    assert classify_path("./runtime/cli.py")["classification"] == AUTHORED


def test_generated_artifacts_are_excluded_from_the_authored_census() -> None:
    report = census(REPO_ROOT)
    assert report["by_classification"][GENERATED]["files"] > 0
    authored = set(authored_paths(REPO_ROOT))
    for artifact in GENERATED_ARTIFACTS:
        if artifact.classification == AUTHORED:
            continue
        prefix = artifact.path.split("#", 1)[0].rstrip("/")
        assert not any(path.startswith(prefix.rstrip("/") + "/") for path in authored), artifact.path


def test_authored_census_is_strictly_smaller_than_physical() -> None:
    """Physical and governed authored censuses must never be conflated again."""
    report = census(REPO_ROOT)
    assert report["governed_authored"]["bytes"] < report["physical"]["bytes"]
    assert report["governed_authored"]["files"] < report["physical"]["files"]
    assert (
        report["governed_authored"]["bytes"] + report["non_authored"]["bytes"]
        == report["physical"]["bytes"]
    )


def test_no_authored_source_is_incorrectly_excluded() -> None:
    """Core authored modules must remain authored, not swept up by a broad rule."""
    for path in (
        "runtime/engine_identity.py",
        "runtime/cli.py",
        "runtime/operational_gap_ledger.py",
        "runtime/source_boundary.py",
        "runtime/vscode_model_bridge.py",
        "extension/src/extension.js",
        "extension/package.json",
        "pyproject.toml",
        "tests/test_operational_gap_ledger.py",
    ):
        assert classify_path(path)["classification"] == AUTHORED, path


def test_pyproject_generated_block_is_classified_without_marking_whole_file_generated() -> None:
    """Only the data-files block is generated; pyproject.toml itself is authored."""
    assert classify_path("pyproject.toml")["classification"] == AUTHORED
    artifact = next(
        item
        for item in GENERATED_ARTIFACTS
        if item.path.startswith("pyproject.toml#")
    )
    assert artifact.classification == PACKAGING_GENERATED
    assert artifact.generator_path == "scripts/migration/sync_skill_packaging.py"
    assert (REPO_ROOT / artifact.generator_path).is_file()


def test_engine_identity_is_independent_of_the_generated_atlas(tmp_path: Path) -> None:
    """Generated atlas removal cannot change identity; authored changes must."""
    from runtime.engine_identity import build_engine_identity

    owner = tmp_path / "runtime" / "owner.py"
    owner.parent.mkdir(parents=True)
    owner.write_text("VALUE = 1\n", encoding="utf-8")
    outputs = (
        "docs/architecture/ATLAS_OFFLINE.html",
        "docs/architecture/graph_data.js",
        "docs/architecture/data/graph.json",
    )
    for relative in outputs:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("generated", encoding="utf-8")
    before = build_engine_identity(tmp_path)
    for relative in outputs:
        (tmp_path / relative).unlink()
    after = build_engine_identity(tmp_path)
    assert after["tree_sha256"] == before["tree_sha256"]
    assert after["file_total"] == before["file_total"] == 1
    owner.write_text("VALUE = 2\n", encoding="utf-8")
    assert build_engine_identity(tmp_path)["tree_sha256"] != before["tree_sha256"]


def test_generated_artifacts_are_declared_excluded_from_canonical_identity() -> None:
    report = assert_generated_never_canonical_authority(REPO_ROOT)
    assert report["valid"], report["problems"]


def test_unbuilt_profile_is_machine_testable_and_deterministic() -> None:
    first = unbuilt_profile(REPO_ROOT)
    second = unbuilt_profile(REPO_ROOT)
    assert first == second
    assert first["schema_version"] == "px.unbuilt-profile/1.0"
    assert any(
        "ATLAS_OFFLINE.html" in item for item in first["absent_by_definition_in_unbuilt"]
    )
    assert any("node_modules" in item for item in first["absent_by_definition_in_unbuilt"])


def test_repeated_census_is_deterministic(tmp_path: Path) -> None:
    # A census includes mutable evidence byte totals: use a stable input tree,
    # rather than asserting that concurrently written live outputs never change.
    for relative in ("runtime/owner.py", "extension/build/generated.js",
                     ".agentic_engineering_os_px/validation/focused.txt"):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture", encoding="utf-8")
    first = census(tmp_path)
    second = census(tmp_path)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert authored_paths(tmp_path) == authored_paths(tmp_path) == ["runtime/owner.py"]


def test_published_boundary_is_digest_bound_and_validates() -> None:
    target = REPO_ROOT / "registry" / "source_boundary.json"
    if not target.is_file():
        write_boundary(REPO_ROOT)
    published = json.loads(target.read_text(encoding="utf-8"))
    assert published["schema_version"] == "px.source-boundary/1.0"
    assert published["validation"]["valid"] is True
    assert published["canonical_authority_check"]["valid"] is True
    body = {key: value for key, value in published.items() if key != "boundary_sha256"}
    import hashlib

    expected = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    assert published["boundary_sha256"] == expected


def test_runtime_required_generated_artifacts_are_not_deleted() -> None:
    """A generated artifact may be absent in an unbuilt checkout, never deleted here."""
    assert (REPO_ROOT / "docs" / "architecture" / "ATLAS_OFFLINE.html").is_file()
    assert (REPO_ROOT / "docs" / "architecture" / "data" / "complete_graph.json").is_file()
    profile = unbuilt_profile(REPO_ROOT)
    assert profile["absent_by_definition_in_unbuilt"]


def test_a_fabricated_path_cannot_claim_generated_status() -> None:
    """No 'it seems generated' classification: unregistered paths are authored."""
    assert (
        classify_path("extension/media/graph_data.js")["classification"] == AUTHORED
    ), "extension/media/graph_data.js does not exist and must not be registered as generated"
    assert classify_path("docs/architecture/tools/build_atlas.py")["classification"] == AUTHORED
# ---------------------------------------------------------------------------
# Control-directory naming equivalence at the governed source boundary.
#
# The control directory was renamed to ".agentic_engineering_os_px". Every rule
# in runtime/source_boundary.py is still spelled with the legacy name, because
# all preserved evidence and all 63 recorded receipt references live there.
#
# The hazard this guards: renaming the rule prefixes alone would make a
# canonical-named control path stop classifying as RUNTIME_STATE/EVIDENCE and
# fall through to AUTHORED, silently pulling control state into the authored
# source digest mid-migration.
# ---------------------------------------------------------------------------

from runtime.engineering_os_paths import CANONICAL_CONTROL_DIR, LEGACY_CONTROL_DIR
from runtime.source_boundary import classify_path


CONTROL_TAILS = (
    "test-evidence/x/receipt.json",
    "project-map/m.json",
    "tmp_work/a.py",
    "runtime-state/ops.jsonl",
    "registry/ops.jsonl",
    "runtime/a.py",
    "contracts/c.json",
    "skills/s.md",
)


def _both(tail):
    legacy = classify_path(f"{LEGACY_CONTROL_DIR}/{tail}")
    canonical = classify_path(f"{CANONICAL_CONTROL_DIR}/{tail}")
    return legacy, canonical


def test_canonical_and_legacy_control_paths_classify_identically():
    for tail in CONTROL_TAILS:
        legacy, canonical = _both(tail)
        assert legacy["classification"] == canonical["classification"], tail
        assert legacy["owner"] == canonical["owner"], tail


def test_evidence_and_runtime_state_are_not_demoted_to_authored():
    # The specific regression: control state must not become authored source.
    legacy, canonical = _both("test-evidence/x/receipt.json")
    assert legacy["classification"] == "evidence"
    assert canonical["classification"] == "evidence"

    legacy, canonical = _both("project-map/m.json")
    assert legacy["classification"] == canonical["classification"] == "runtime_state"


def test_bare_control_directory_classifies_identically():
    legacy = classify_path(LEGACY_CONTROL_DIR)
    canonical = classify_path(CANONICAL_CONTROL_DIR)

    assert legacy["classification"] == canonical["classification"]


def test_only_the_leading_segment_is_rewritten():
    # An interior directory that merely shares the name is not a control path
    # and must not be folded onto the legacy spelling.
    interior = classify_path(f"src/{CANONICAL_CONTROL_DIR}/a.py")
    same = classify_path(f"src/{LEGACY_CONTROL_DIR}/a.py")

    assert interior["classification"] == same["classification"] == "authored"


def test_ordinary_source_is_unaffected_by_the_migration():
    for relative in ("runtime/a.py", "contracts/c.json", "src/x.py", "README.md"):
        assert classify_path(relative)["classification"] == "authored"


def test_normalization_is_deterministic_and_side_effect_free():
    first = classify_path(f"{CANONICAL_CONTROL_DIR}/project-map/m.json")
    second = classify_path(f"{CANONICAL_CONTROL_DIR}/project-map/m.json")

    assert first == second

def test_validation_evidence_and_unregistered_locks_have_distinct_custody():
    for namespace in (".engineering-bootstrap", ".agentic_engineering_os_px"):
        assert classify_path(namespace + "/validation/focused.txt")["classification"] == EVIDENCE
    assert classify_path("registry/customer.lock")["classification"] == AUTHORED
    assert classify_path("registry/.operational-gap-ledger.lock")["classification"] == RUNTIME_STATE


def test_registered_directory_boundary_matches_directory_and_children() -> None:
    for directory in ("extension/build", "extension/dist", "extension/evidence"):
        assert classify_path(directory)["classification"] != AUTHORED
        assert classify_path(directory + "/owned.json")["classification"] != AUTHORED
        assert classify_path(directory + "-authored/owned.json")["classification"] == AUTHORED
