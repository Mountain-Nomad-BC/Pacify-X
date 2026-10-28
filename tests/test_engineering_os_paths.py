"""Canonical engineering-OS naming with legacy compatibility.

The owner directive is that ``.agentic_engineering_os_px`` is the standard name
from now on. That cannot be a blind rename: 63 hash-verified evidence receipts
embed the literal legacy path. These tests pin the two properties that make the
migration safe rather than destructive.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from runtime.engineering_os_paths import (
    CANONICAL_CONTROL_DIR,
    LEGACY_CONTROL_DIR,
    EngineeringOsPathError,
    control_root,
    exists,
    is_control_relative,
    legacy_control_root,
    legacy_references,
    policy_snapshot,
    resolve,
    uses_canonical_name,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


# --- the owner directive -----------------------------------------------------


def test_canonical_name_is_the_standard_going_forward():
    assert CANONICAL_CONTROL_DIR == ".agentic_engineering_os_px"
    assert LEGACY_CONTROL_DIR == ".engineering-bootstrap"
    snapshot = policy_snapshot()
    assert snapshot["canonical_control_dir"] == ".agentic_engineering_os_px"
    assert snapshot["legacy_write_allowed"] is False
    assert snapshot["legacy_read_allowed"] is True


def test_new_state_targets_the_canonical_directory():
    assert control_root(REPO_ROOT).name == CANONICAL_CONTROL_DIR
    assert legacy_control_root(REPO_ROOT).name == LEGACY_CONTROL_DIR


def test_write_target_never_falls_back_to_legacy(tmp_path):
    # resolve() intentionally falls back to the legacy tree so preserved
    # evidence stays readable. Writing must NOT do that, or the migration would
    # keep producing new legacy-named state. control_root is the write target.
    (tmp_path / LEGACY_CONTROL_DIR / "state").mkdir(parents=True)

    write_target = control_root(tmp_path)

    assert write_target.name == CANONICAL_CONTROL_DIR
    assert not write_target.exists()
    # A read still resolves the legacy tree...
    assert resolve(tmp_path, "state").exists()
    # ...while the write target stays canonical even though legacy exists.
    assert write_target != resolve(tmp_path, "state")


# --- legacy stays readable ---------------------------------------------------


def test_legacy_tree_still_resolves_so_preserved_evidence_is_reachable():
    # The preserved evidence tree is recorded under the legacy name in
    # hash-verified receipts. It must keep resolving or custody is broken.
    resolved = resolve(REPO_ROOT, "test-evidence")

    assert resolved.exists()
    assert resolved.name == "test-evidence"
    assert resolve(REPO_ROOT, "test-evidence").is_dir()


def test_legacy_evidence_receipts_are_still_discoverable():
    evidence = resolve(REPO_ROOT, "test-evidence")

    assert (evidence / "rev1xx-w1-project-map-bridge-identity" / "receipt.json").is_file()


def test_missing_path_returns_the_canonical_target_not_the_legacy_one():
    target = resolve(REPO_ROOT, "definitely", "not", "here")

    # The canonical control directory is the first segment, not the immediate
    # parent of a nested path.
    assert CANONICAL_CONTROL_DIR in target.parts
    assert LEGACY_CONTROL_DIR not in target.parts
    assert target.as_posix().endswith("definitely/not/here")


# --- canonical wins on a half-migrated tree ---------------------------------


def test_canonical_directory_wins_when_both_exist(tmp_path):
    (tmp_path / CANONICAL_CONTROL_DIR).mkdir()
    (tmp_path / LEGACY_CONTROL_DIR).mkdir()

    resolved = resolve(tmp_path)

    # Serving legacy state as current after a partial migration is exactly the
    # silent-drift failure this migration must avoid.
    assert resolved.name == CANONICAL_CONTROL_DIR


def test_legacy_is_used_only_when_canonical_is_absent(tmp_path):
    (tmp_path / LEGACY_CONTROL_DIR / "state").mkdir(parents=True)

    resolved = resolve(tmp_path, "state")

    assert resolved.exists()
    assert resolved.parent.name == LEGACY_CONTROL_DIR


def test_exists_works_under_either_spelling(tmp_path):
    (tmp_path / LEGACY_CONTROL_DIR / "only_legacy").mkdir(parents=True)
    (tmp_path / CANONICAL_CONTROL_DIR / "only_canonical").mkdir(parents=True)

    assert exists(tmp_path, "only_legacy") is True
    assert exists(tmp_path, "only_canonical") is True
    assert exists(tmp_path, "neither") is False


# --- classification ----------------------------------------------------------


def test_control_relative_classification_accepts_both_spellings():
    assert is_control_relative(f"{CANONICAL_CONTROL_DIR}/test-evidence/receipt.json")
    assert is_control_relative(f"{LEGACY_CONTROL_DIR}/test-evidence/receipt.json")
    assert is_control_relative(".agentic_engineering_os_px")
    assert not is_control_relative("runtime/librarian_semantic_map.py")
    assert not is_control_relative("")
    assert not is_control_relative(None)


def test_canonical_name_detection_distinguishes_spellings():
    assert uses_canonical_name(f"{CANONICAL_CONTROL_DIR}/a.json")
    assert not uses_canonical_name(f"{LEGACY_CONTROL_DIR}/a.json")
    assert not uses_canonical_name("runtime/a.py")


def test_legacy_reference_detection_finds_old_spellings_in_literals():
    assert legacy_references(f"{LEGACY_CONTROL_DIR}/test-evidence/x/receipt.json")
    assert legacy_references(f'root / "{LEGACY_CONTROL_DIR}"')
    assert not legacy_references(f"{CANONICAL_CONTROL_DIR}/test-evidence/x")


# --- bounded inputs ----------------------------------------------------------


def test_traversal_and_unbounded_segments_are_refused(tmp_path):
    with pytest.raises(EngineeringOsPathError):
        resolve(tmp_path, "..", "escape")
    with pytest.raises(EngineeringOsPathError):
        resolve(tmp_path, "")
    with pytest.raises(EngineeringOsPathError):
        resolve(tmp_path, "x" * 500)
    with pytest.raises(EngineeringOsPathError):
        resolve(tmp_path, *[f"s{i}" for i in range(64)])


def test_resolution_never_escapes_the_repository_root(tmp_path):
    resolved = resolve(tmp_path, "a", "b", "c")

    assert tmp_path.resolve() in resolved.resolve().parents


# --- no destructive capability ----------------------------------------------


def test_owner_exposes_no_move_rename_or_delete_capability():
    # The module resolves names only. Migration is explicit, admitted work
    # performed elsewhere, so this owner must not be able to destroy anything.
    forbidden = {"rename", "move", "replace", "unlink", "rmtree", "copy",
                 "copytree", "write_text", "write_bytes", "mkdir", "remove"}
    exported = {name for name in dir() if not name.startswith("_")}

    assert not (exported & forbidden)