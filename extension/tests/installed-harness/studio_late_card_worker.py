from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import struct
import sys


RUNTIME_ROOT = Path(os.environ.get("PX_OWNED_ENGINE_ROOT", Path(__file__).resolve().parents[3])).resolve()
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

import runtime.studio_models as studio_models
from runtime.native_skills import build_skill_index
from runtime.skill_studio import SkillStudio, _tree_attestation
from runtime.studio_models import (
    AgentSpec,
    SkillPackage,
    StudioVersionConflict,
    allocate_studio_version,
    require_initial_studio_identity,
    studio_identity_absence,
    studio_revision_root,
    write_versioned_record,
)


def _agent(identity: str, version: str = "1.0.0", owner: str = "px-owned-walker") -> AgentSpec:
    return AgentSpec(
        identity,
        version,
        "project:px-owned",
        owner,
        "harness:px",
        "a" * 64,
        ("binding:owned",),
        ("grant:owned",),
        ("identity",),
    )


def _write_agent(root: Path, identity: str, version: str = "1.0.0") -> Path:
    return write_versioned_record(root, "agent", identity, version, _agent(identity, version))


def _conflict_reason(operation, expected: str) -> bool:
    try:
        operation()
    except StudioVersionConflict as error:
        return error.reason == expected
    return False


def _symlink_or_junction(link: Path, target: Path) -> bool:
    try:
        link.symlink_to(target, target_is_directory=True)
        return True
    except OSError:
        if os.name != "nt":
            return False
    completed = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    return completed.returncode == 0 and link.exists()


def _physical_allocation_profile(root: Path) -> dict[str, bool]:
    checks: dict[str, bool] = {}

    file_identity = "agent:occupied-file"
    _write_agent(root, file_identity)
    file_revisions = studio_revision_root(root, "agent", file_identity)
    (file_revisions / "1.0.1").write_text("occupied", encoding="utf-8")
    file_allocation = allocate_studio_version(root, "agent", file_identity, "1.0.0")
    checks["canonical_file_occupied"] = file_allocation["candidate_version"] == "1.0.2"

    directory_identity = "agent:occupied-directory"
    _write_agent(root, directory_identity)
    directory_revisions = studio_revision_root(root, "agent", directory_identity)
    (directory_revisions / "1.0.1").mkdir()
    directory_allocation = allocate_studio_version(root, "agent", directory_identity, "1.0.0")
    checks["canonical_directory_occupied"] = directory_allocation["candidate_version"] == "1.0.2"

    alias_identity = "agent:noncanonical-alias"
    _write_agent(root, alias_identity)
    alias_revisions = studio_revision_root(root, "agent", alias_identity)
    (alias_revisions / " 1.0.1").write_text("not canonical occupancy", encoding="utf-8")
    (alias_revisions / "1.0.1-RC.1").mkdir()
    alias_allocation = allocate_studio_version(root, "agent", alias_identity, "1.0.0")
    checks["noncanonical_alias_ignored"] = alias_allocation["candidate_version"] == "1.0.1"

    dangling_identity = "agent:dangling-link"
    dangling_root = studio_revision_root(root, "agent", dangling_identity)
    dangling_root.parent.mkdir(parents=True, exist_ok=True)
    link_created = _symlink_or_junction(dangling_root, root / "absent-dangling-target")
    checks["dangling_link_blocked"] = link_created and _conflict_reason(
        lambda: studio_identity_absence(root, "agent", dangling_identity),
        "source-revision-invalid",
    )

    denied_identity = "agent:inspection-denied"
    _write_agent(root, denied_identity)
    denied_revisions = studio_revision_root(root, "agent", denied_identity)
    (denied_revisions / "1.0.1").write_text("racing entry", encoding="utf-8")
    original = studio_models._is_link_or_reparse

    def deny_candidate(path: Path) -> bool:
        if path.name == "1.0.1":
            raise PermissionError("owned inspection denial")
        return original(path)

    studio_models._is_link_or_reparse = deny_candidate
    try:
        checks["inspection_denial_blocked"] = _conflict_reason(
            lambda: allocate_studio_version(root, "agent", denied_identity, "1.0.0"),
            "source-revision-invalid",
        )
    finally:
        studio_models._is_link_or_reparse = original

    checks["no_revision_published"] = all(
        not (studio_revision_root(root, "agent", identity) / candidate).exists()
        for identity, candidate in (
            (file_identity, file_allocation["candidate_version"]),
            (directory_identity, directory_allocation["candidate_version"]),
            (alias_identity, alias_allocation["candidate_version"]),
        )
    )
    external = allocate_studio_version(
        root,
        "skill",
        "skill:owned-external",
        "1.0.0",
        source_scope="external-authenticated",
        source_revision_sha256="d" * 64,
        source_content_sha256="e" * 64,
    )
    external_root = studio_revision_root(root, "skill", "skill:owned-external")
    external_root.mkdir(parents=True, exist_ok=True)
    (external_root / external["candidate_version"]).mkdir()
    checks["external_skill_conflict"] = _conflict_reason(
        lambda: studio_models.revalidate_studio_version_allocation(
            root,
            "skill",
            "skill:owned-external",
            external["candidate_version"],
            external,
        ),
        "allocation-stale",
    )
    return checks


def _fork_profile(root: Path) -> dict[str, bool]:
    original_identity = "agent:fork-source"
    fork_identity = "agent:fork-target"
    _write_agent(root, original_identity)
    physical = studio_identity_absence(root, original_identity.split(":", 1)[0], original_identity)
    fork_absence = studio_identity_absence(root, "agent", fork_identity)
    require_initial_studio_identity(root, "agent", fork_identity, "1.0.0")
    fork_path = write_versioned_record(root, "agent", fork_identity, "1.0.0", _agent(fork_identity))
    reopened = json.loads(fork_path.read_text(encoding="utf-8"))
    reopened_record = reopened.get("record", {})
    return {
        "physical_identity_absence": physical["absent"] is False,
        "explicit_fork_absence": fork_absence["absent"] is True,
        "fork_reopen_without_lineage": reopened_record.get("agent_id") == fork_identity
        and reopened_record.get("version") == "1.0.0"
        and not any("predecessor" in key or "source_revision" in key for key in reopened_record),
    }


def _skill_source(root: Path, name: str, version: str = "1.0.0", skill_id: str = "late-card") -> Path:
    target = root / name
    for relative in ("contracts", "agents", "tests", "resources"):
        (target / relative).mkdir(parents=True, exist_ok=True)
    manifest = {"schema_version": "px.native-skill-package/1.0", "id": skill_id, "version": version, "domain": "px-standard"}
    encoded = json.dumps(manifest, indent=2) + "\n"
    (target / "SKILL.md").write_text(f"# {skill_id} {version}\n", encoding="utf-8")
    (target / "capability.json").write_text(encoded, encoding="utf-8")
    (target / "skill.yaml").write_text(encoded, encoding="utf-8")
    (target / "agents/openai.yaml").write_text('interface:\n  display_name: "Late card"\n  short_description: "Owned exact lifecycle fixture"\n', encoding="utf-8")
    (target / "contracts/manifest.json").write_text(json.dumps({"schema_version": "px.skill-contract-links/1.0", "contracts": []}) + "\n", encoding="utf-8")
    (target / "tests/validation.json").write_text(json.dumps({"schema_version": "px.skill-test/1.1", "cases": [{"name": "required", "assertion": {"kind": "required-files", "paths": ["SKILL.md", "capability.json", "skill.yaml"]}}]}) + "\n", encoding="utf-8")
    (target / "resources/index.json").write_text(json.dumps({"schema_version": "px.skill-resources/1.0", "resources": ["agents/openai.yaml", "capability.json", "contracts/manifest.json", "SKILL.md", "skill.yaml", "tests/validation.json"]}) + "\n", encoding="utf-8")
    return target


def _projection_scaffold(root: Path) -> None:
    (root / "registry/skill_packages").mkdir(parents=True, exist_ok=True)
    (root / "registry/admission_ledger.json").write_text(json.dumps({"schema_version": "1.0", "allowed_dispositions": ["adopt"], "promotion_requirements": [], "records": []}), encoding="utf-8")
    (root / "registry/skill_catalog.toml").write_text('schema_version = "1.0"\n', encoding="utf-8")
    (root / ".px").mkdir(exist_ok=True)
    (root / ".px/skill-index.json").write_text(json.dumps(build_skill_index([])), encoding="utf-8")


def _skill_package(version: str, provenance: dict[str, object]) -> SkillPackage:
    return SkillPackage(
        "skill:late-card",
        version,
        "px-owned-walker",
        ("verify exact lifecycle",),
        ("unrelated",),
        ("read",),
        ("read",),
        ("resources/index.json",),
        ("contracts/manifest.json",),
        ("tests/validation.json",),
        provenance,
    )


def _independent_framed_tree_hash(root: Path) -> str:
    """Compute the public tree commitment without calling the runtime oracle."""

    materialized: list[tuple[str, bytes]] = []
    for directory, names, files in os.walk(root):
        names.sort(key=lambda value: value.encode("utf-8"))
        files.sort(key=lambda value: value.encode("utf-8"))
        current = Path(directory)
        for name in files:
            path = current / name
            materialized.append((path.relative_to(root).as_posix(), path.read_bytes()))
    materialized.sort(key=lambda item: item[0].encode("utf-8"))
    digest = hashlib.sha256()
    digest.update(b"px.skill-tree/2\0")
    digest.update(struct.pack(">Q", len(materialized)))
    for relative, data in materialized:
        encoded = relative.encode("utf-8")
        digest.update(struct.pack(">Q", len(encoded)))
        digest.update(encoded)
        digest.update(struct.pack(">Q", len(data)))
        digest.update(data)
    return digest.hexdigest()


def _preserved_and_projection_profile(root: Path) -> dict[str, bool]:
    _projection_scaffold(root)
    preserved = _skill_source(root / ".px/preserved-skills/initial", "workspace-original")
    tree_sha256 = _tree_attestation(preserved)[1]
    body_sha256 = hashlib.sha256((preserved / "SKILL.md").read_bytes()).hexdigest()
    exact = {
        "schema_version": "px.preserved-skill-provenance/1.0",
        "skill_id": "skill:late-card",
        "source_version": "1.0.0",
        "origin": "workspace-agents-original",
        "package_relative": preserved.relative_to(root).as_posix(),
        "tree_sha256": tree_sha256,
        "body_sha256": body_sha256,
        "file_count": len(_tree_attestation(preserved)[0]),
    }
    provenance = {
        "source": "owned-installed-harness",
        "license": "Apache-2.0",
        **{f"preserved_original_{key}": str(value) for key, value in exact.items() if key != "file_count"},
        "preserved_original_file_count": str(exact["file_count"]),
    }
    package = _skill_package("1.0.0", provenance)
    candidate = _skill_source(root, "candidate-one")
    studio = SkillStudio(root)
    token = studio.admit_source(candidate, approved_by="px-owned-walker")
    draft = studio.stage_draft(package, candidate, source_token=token)
    validation = studio.validate(package)
    admission = studio.admit(package, approved=True, approver="px-owned-walker")
    promotion = studio.promote(package, approved=True)
    projected = json.loads((root / "registry/skill_packages/late-card.json").read_text(encoding="utf-8"))
    index = json.loads((root / ".px/skill-index.json").read_text(encoding="utf-8"))
    indexed = next(row for row in index["records"] if row["id"] == "late-card")
    canonical = root / promotion["target_relative"]
    promotion_tree = _tree_attestation(canonical)[1]
    projection_paths = tuple(root / relative for relative in promotion["projection_updates"])
    first_projection_bytes = {path: path.read_bytes() for path in projection_paths}

    package_two = replace(package, version="1.1.0")
    candidate_two = _skill_source(root, "candidate-two", version="1.1.0")
    (candidate_two / "SKILL.md").write_text("# late-card 1.1.0\n", encoding="utf-8")
    token_two = studio.admit_source(candidate_two, approved_by="px-owned-walker")
    studio.stage_draft(package_two, candidate_two, source_token=token_two)
    assert studio.validate(package_two)["passed"] is True
    assert studio.admit(package_two, approved=True, approver="px-owned-walker")["decision"] == "admitted"
    promotion_two = studio.promote(package_two, approved=True)
    promotion_receipt = next((root / ".engineering-bootstrap/studios/skills").glob("*/revisions/1.1.0/promotion-receipt.json"))
    rollback = studio.rollback(promotion_receipt, approved=True, approver="px-owned-walker", expected_skill_id=package_two.skill_id, expected_version=package_two.version)
    restored_tree = _tree_attestation(canonical)[1]
    manifest_path = root / promotion_two["lifecycle_transaction_relative"] / "manifest.json"
    authenticated_manifest = studio.authority.verify_receipt(json.loads(manifest_path.read_text(encoding="utf-8")))

    return {
        "preserved_original_selected": draft.get("preserved_original") == exact,
        "provenance_bound_editor": draft.get("preserved_original") == exact,
        "provenance_bound_candidate": validation.get("preserved_original") == exact and admission.get("preserved_original") == exact,
        "provenance_bound_promotion": promotion.get("preserved_original") == exact,
        "projected_backup_exact": projected.get("preserved_original") == exact and indexed.get("backup") == exact["package_relative"],
        "framed_tree_hash_exact": promotion_tree
        == _independent_framed_tree_hash(canonical),
        "promotion_projection_authenticated": authenticated_manifest.get("state") == "committed" and bool(promotion_two.get("projection_transaction_relative")),
        "rollback_projection_authenticated": set(rollback.get("projection_restorations", [])) == {path.relative_to(root).as_posix() for path in projection_paths},
        "immediate_catalog_refresh": restored_tree == promotion_tree and all(path.read_bytes() == first_projection_bytes[path] for path in projection_paths),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    physical_root = root / "physical"
    fork_root = root / "fork"
    skill_root = root / "skill"
    for target in (physical_root, fork_root, skill_root):
        target.mkdir(parents=True, exist_ok=True)
    result = {
        "schema_version": "px.installed-studio-late-card-worker/1.0",
        "runtime_root": str(RUNTIME_ROOT),
        "physical": _physical_allocation_profile(physical_root),
        "fork": _fork_profile(fork_root),
        "skill": _preserved_and_projection_profile(skill_root),
    }
    result["completed"] = all(value is True for group in (result["physical"], result["fork"], result["skill"]) for value in group.values())
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
