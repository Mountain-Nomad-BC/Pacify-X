"""One-time, recoverable migration from workspace skills to PX-native packages."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import sys
import tomllib
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from runtime.native_skills import (  # noqa: E402
    BACKUP_SCHEMA,
    PACKAGE_SCHEMA,
    build_skill_index,
    copy_verified,
    inventory_tree,
    tree_hash,
    validate_skill_index,
    verify_backup,
)


MIGRATION_SCHEMA = "px.skill-first-initialization/2.0"


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    prepared = path.with_name(f".{path.name}.{uuid4().hex}.prepared")
    prepared.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    prepared.replace(path)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bytes_sha(payload: bytes | None) -> str | None:
    return hashlib.sha256(payload).hexdigest() if payload is not None else None


def _recover_publication_transactions(root: Path) -> None:
    transactions = root / ".px" / "skill-publication-transactions"
    if not transactions.is_dir():
        return
    for transaction in sorted(transactions.iterdir(), key=lambda item: item.name):
        if transaction.name.startswith(".") and transaction.name.endswith(".prepared"):
            continue
        manifest_path = transaction / "manifest.json"
        if not transaction.is_dir() or not manifest_path.is_file():
            raise RuntimeError("invalid skill publication transaction custody")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("state") == "committed":
            continue
        if manifest.get("state") not in {"prepared", "applying"}:
            raise RuntimeError("unknown skill publication transaction state")
        manifest["state"] = "applying"
        _write_json(manifest_path, manifest)
        for item in manifest.get("artifacts", ()):
            relative = Path(str(item["path"]))
            if relative.is_absolute() or ".." in relative.parts:
                raise RuntimeError("skill publication target escapes project root")
            target = root / relative
            after = (transaction / str(item["after_image"])).read_bytes()
            if _bytes_sha(after) != item.get("after_sha256"):
                raise RuntimeError("skill publication after-image changed")
            current = target.read_bytes() if target.is_file() else None
            current_hash = _bytes_sha(current)
            if current_hash == item.get("after_sha256"):
                continue
            if current_hash != item.get("before_sha256"):
                raise RuntimeError(
                    f"skill publication target changed outside transaction: {relative.as_posix()}"
                )
            target.parent.mkdir(parents=True, exist_ok=True)
            prepared = target.with_name(f".{target.name}.{uuid4().hex}.prepared")
            prepared.write_bytes(after)
            prepared.replace(target)
        manifest["state"] = "committed"
        _write_json(manifest_path, manifest)


def _commit_publication(
    root: Path, updates: dict[Path, bytes], *, operation: str
) -> None:
    _recover_publication_transactions(root)
    transactions = root / ".px" / "skill-publication-transactions"
    transaction_id = f"{operation}-{uuid4().hex}"
    prepared_transaction = transactions / f".{transaction_id}.prepared"
    transaction = transactions / transaction_id
    prepared_transaction.mkdir(parents=True)
    artifacts = []
    for index, (target, after) in enumerate(
        sorted(updates.items(), key=lambda item: item[0].as_posix())
    ):
        resolved = target.resolve()
        if root != resolved and root not in resolved.parents:
            raise RuntimeError("skill publication target escapes project root")
        before = target.read_bytes() if target.is_file() else None
        image = f"after-{index}.bin"
        (prepared_transaction / image).write_bytes(after)
        artifacts.append(
            {
                "path": target.relative_to(root).as_posix(),
                "before_sha256": _bytes_sha(before),
                "after_sha256": _bytes_sha(after),
                "after_image": image,
            }
        )
    manifest = {
        "schema_version": "px.skill-publication-transaction/1.0",
        "operation": operation,
        "state": "prepared",
        "artifacts": artifacts,
    }
    _write_json(prepared_transaction / "manifest.json", manifest)
    prepared_transaction.replace(transaction)
    _recover_publication_transactions(root)


def _description(body: Path) -> str:
    match = re.search(r"(?m)^description:\s*[\"']?(.*?)[\"']?\s*$", body.read_text(encoding="utf-8"))
    return match.group(1).strip() if match else ""


def _native_record(target: Path, skill: dict[str, object]) -> dict[str, object]:
    skill_id = str(skill["id"])
    capability = json.loads((target / "capability.json").read_text(encoding="utf-8"))
    body = target / "SKILL.md"
    body_sha = _sha(body)
    if capability.get("id") != skill_id or capability.get("body_sha256") != body_sha:
        raise RuntimeError(f"native package identity drift: {skill_id}")
    return {
        "id": skill_id, "version": capability["version"], "status": capability["status"], "description": capability["description"],
        "tags": capability["tags"], "domain": "px-standard", "origin": "workspace-agents-original", "native": True,
        "adapted": False, "default_eligible": capability["isolation"]["default_eligible"], "body_available": True,
        "package_root": f".px/skills/{skill_id}", "body": f".px/skills/{skill_id}/SKILL.md", "body_sha256": body_sha,
        "backup": f".px/preserved-skills/initial/workspace-original/{skill_id}", "admission": capability["status"]
    }


def _native_package(
    root: Path,
    source: Path,
    skill: dict[str, object],
    *,
    target_root: Path | None = None,
) -> dict[str, object]:
    skill_id = str(skill["id"])
    target = (target_root or (root / ".px" / "skills")) / skill_id
    if target.exists():
        return _native_record(target, skill)
    shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache", ".ruff_cache"))
    body = target / "SKILL.md"
    body_sha = _sha(body)
    package_contract = root / str(skill.get("contract", ""))
    contract_sha = _sha(package_contract) if package_contract.is_file() else None
    contract_record = {"source": str(skill.get("contract", "")), "sha256": contract_sha, "available": bool(contract_sha)}
    _write_json(target / "contracts" / "manifest.json", {"schema_version": "px.skill-contract-links/1.0", "contracts": [contract_record]})
    _write_json(target / "tests" / "validation.json", {"schema_version": "px.skill-validation-links/1.0", "checks": ["native-package-schema", "body-hash", "domain-policy", "bounded-hydration"], "shared_suite": "tests/test_native_skills.py"})
    resources = [path.relative_to(target).as_posix() for path in sorted(target.rglob("*")) if path.is_file() and path.name not in {"capability.json", "skill.yaml"}]
    capability = {
        "schema_version": PACKAGE_SCHEMA, "id": skill_id, "version": str(skill.get("version", "0.1.0")),
        "domain": "px-standard", "origin": "workspace-agents-original", "native": True,
        "lazy": True, "status": str(skill.get("status", "candidate")), "entrypoint": "SKILL.md",
        "body_sha256": body_sha, "description": _description(body), "tags": [str(value) for value in skill.get("tags", ())],
        "contract": contract_record, "admission_record": skill.get("admission_record"),
        "selection": {"metadata_visible": True, "body_hydration": "exactly-one-after-selection", "maximum_candidates": 3},
        "isolation": {"default_eligible": str(skill.get("status", "candidate")) in {"active", "admitted"}, "cross_domain_requires_explicit_intent_and_policy": True},
        "provenance": {"source": f".px/preserved-skills/initial/workspace-original/{skill_id}", "adapted": False}
    }
    _write_json(target / "capability.json", capability)
    (target / "skill.yaml").write_text(json.dumps(capability, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _write_json(target / "resources" / "index.json", {"schema_version": "px.skill-resources/1.0", "resources": resources})
    return _native_record(target, skill)


def _preserved_records(root: Path, source: Path, relative_backup: str) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for body in sorted(source.rglob("SKILL.md")):
        relative = body.parent.relative_to(source).as_posix()
        microsoft = "microsoft" in relative.casefold() or "foundry" in relative.casefold()
        domain = "microsoft-vendor" if microsoft else "user-preserved"
        skill_id = f"{domain}/{relative}".replace("_", "-").casefold()
        records.append({
            "id": skill_id, "version": "preserved", "status": "preserved-not-admitted", "description": _description(body), "tags": [],
            "domain": domain, "origin": "user-global-agents", "native": False, "adapted": False, "default_eligible": False,
            "body_available": True, "package_root": f"{relative_backup}/{relative}", "body": f"{relative_backup}/{relative}/SKILL.md",
            "body_sha256": _sha(body), "backup": f"{relative_backup}/{relative}", "admission": "preserved-not-admitted"
        })
    return records


def _snapshot_record(source: Path, snapshot_id: str) -> dict[str, object]:
    records = inventory_tree(source)
    return {
        "schema_version": "px.skill-tree-snapshot/1.0",
        "snapshot_id": snapshot_id,
        "source": str(source.resolve()),
        "file_count": len(records),
        "size_bytes": sum(int(row["size_bytes"]) for row in records),
        "tree_sha256": tree_hash(records),
        "files": records,
    }


def _journal_write(path: Path, journal: dict[str, object], state: str) -> None:
    journal["state"] = state
    _write_json(path, journal)


def _verify_journal_evidence(
    control: Path, snapshot: Path, journal: dict[str, object]
) -> None:
    first = json.loads(
        (control / str(journal["snapshot_a"])).read_text(encoding="utf-8")
    )
    second = json.loads(
        (control / str(journal["snapshot_b"])).read_text(encoding="utf-8")
    )
    expected = str(journal["workspace_tree_sha256"])
    if first.get("files") != second.get("files"):
        raise RuntimeError("journaled full-tree snapshots no longer agree")
    if first.get("tree_sha256") != expected or second.get("tree_sha256") != expected:
        raise RuntimeError("journaled snapshot hash differs from migration custody")
    if journal.get("state") == "committed":
        if journal.get("pre_move_tree_sha256") != expected:
            raise RuntimeError("committed migration lacks immediate pre-move equality")
        for relative in ("workspace-original", "workspace-verified-copy"):
            if tree_hash(inventory_tree(snapshot / relative)) != expected:
                raise RuntimeError(f"immutable migration custody changed: {relative}")


def _migration_result(
    index: dict[str, object], backup: dict[str, object], journal: dict[str, object]
) -> dict[str, object]:
    return {
        "mode": "first-initialization" if journal.get("state") == "committed" else "recovery",
        "state": journal.get("state"),
        "native_packages": index["counts"]["px-standard"],
        "index_records": index["record_count"],
        "counts": index["counts"],
        "backup": backup,
        "workspace_tree_sha256": journal["workspace_tree_sha256"],
        "user_tree_sha256": journal["user_tree_sha256"],
        "incremental_owner": "runtime.skill_studio.SkillStudio",
    }


def migrate(
    root: Path,
    user_skills: Path,
    *,
    _stop_after_state: str | None = None,
) -> dict[str, object]:
    """Run or recover the one-time custody migration.

    The live source is moved only after two identical full inventories, a
    verified immutable backup, and an immediate third equality check.  Every
    phase is journaled so a restart can reconcile forward without overwriting
    either original custody tree.
    """
    root = root.resolve()
    user_skills = user_skills.resolve()
    source = root / ".agents" / "skills"
    px = root / ".px"
    snapshot = px / "preserved-skills" / "initial"
    control = px / "skill-first-initialization"
    journal_path = control / "journal.json"
    prepared_skills = control / "prepared-skills"
    skills = px / "skills"
    relocated = snapshot / "workspace-original"
    verified_copy = snapshot / "workspace-verified-copy"

    if journal_path.is_file():
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
        if journal.get("schema_version") != MIGRATION_SCHEMA:
            raise ValueError("unsupported skill migration journal")
        _verify_journal_evidence(control, snapshot, journal)
        if journal.get("state") == "committed":
            index = json.loads((px / "skill-index.json").read_text(encoding="utf-8"))
            validate_skill_index(index, require_derived=True)
            backup = verify_backup(snapshot)
            if not backup["valid"]:
                raise RuntimeError(f"backup verification failed: {backup['errors']}")
            result = _migration_result(index, backup, journal)
            result["mode"] = "incremental-only"
            return result
    elif snapshot.exists() or skills.exists():
        raise FileExistsError(
            "legacy PX skill migration exists without a v2 journal; refusing to fabricate pre-move evidence"
        )
    else:
        first = _snapshot_record(source, "workspace-a")
        _write_json(control / "workspace-snapshot-a.json", first)
        second = _snapshot_record(source, "workspace-b")
        _write_json(control / "workspace-snapshot-b.json", second)
        if first["files"] != second["files"]:
            raise RuntimeError("workspace skill tree changed between required snapshots")
        workspace_copy = copy_verified(source, verified_copy)
        user_copy = copy_verified(user_skills, snapshot / "user-original")
        if workspace_copy["tree_sha256"] != first["tree_sha256"]:
            raise RuntimeError("verified workspace backup differs from matching snapshots")
        journal = {
            "schema_version": MIGRATION_SCHEMA,
            "state": "created",
            "source": str(source),
            "workspace_tree_sha256": first["tree_sha256"],
            "workspace_file_count": first["file_count"],
            "user_tree_sha256": user_copy["tree_sha256"],
            "snapshot_a": "workspace-snapshot-a.json",
            "snapshot_b": "workspace-snapshot-b.json",
            "pre_move_tree_sha256": None,
            "original_custody": ".px/preserved-skills/initial/workspace-original",
            "backup_custody": ".px/preserved-skills/initial/workspace-verified-copy",
            "retention": "immutable; never auto-purge",
        }
        _journal_write(journal_path, journal, "snapshots-verified")
        if _stop_after_state == "snapshots-verified":
            raise RuntimeError("injected migration stop after snapshots-verified")

    expected_hash = str(journal["workspace_tree_sha256"])
    catalog = tomllib.loads(
        (root / "registry" / "skill_catalog.toml").read_text(encoding="utf-8")
    )
    source_for_packages = relocated if relocated.is_dir() else source

    if not skills.exists() and not prepared_skills.exists():
        prepared_skills.mkdir(parents=True, exist_ok=False)
        for skill in catalog.get("skills", ()):
            _native_package(
                root,
                source_for_packages / str(skill["id"]),
                skill,
                target_root=prepared_skills,
            )
        _journal_write(journal_path, journal, "packages-prepared")
        if _stop_after_state == "packages-prepared":
            raise RuntimeError("injected migration stop after packages-prepared")

    if not relocated.exists():
        immediate = _snapshot_record(source, "workspace-pre-move")
        if immediate["tree_sha256"] != expected_hash:
            _journal_write(journal_path, journal, "blocked-source-drift")
            raise RuntimeError("workspace skill tree changed immediately before relocation")
        journal["pre_move_tree_sha256"] = immediate["tree_sha256"]
        journal["pre_move_file_count"] = immediate["file_count"]
        _journal_write(journal_path, journal, "pre-move-verified")
        source.replace(relocated)
        _journal_write(journal_path, journal, "source-relocated")
        if _stop_after_state == "source-relocated":
            raise RuntimeError("injected migration stop after source-relocated")
    elif tree_hash(inventory_tree(relocated)) != expected_hash:
        raise RuntimeError("immutable workspace-original custody changed")

    if not source.exists():
        source.mkdir(parents=True, exist_ok=False)
    if not skills.exists():
        if not prepared_skills.is_dir():
            raise RuntimeError("prepared native skill packages are missing")
        prepared_skills.replace(skills)
    _journal_write(journal_path, journal, "skills-published")

    native_records = [
        _native_package(root, relocated / str(skill["id"]), skill)
        for skill in catalog.get("skills", ())
    ]
    relocated_records = inventory_tree(relocated)
    workspace_copy_records = inventory_tree(verified_copy)
    user_copy_records = inventory_tree(snapshot / "user-original")
    if tree_hash(relocated_records) != tree_hash(workspace_copy_records):
        raise RuntimeError("immutable original and verified backup custody disagree")
    sources = [
        {"id": "workspace-original", "original_path": str(source), "relative_backup": "workspace-original", "file_count": len(relocated_records), "size_bytes": sum(int(row["size_bytes"]) for row in relocated_records), "tree_sha256": tree_hash(relocated_records), "ownership": "user-owned-evidence", "auto_purge": "never"},
        {"id": "workspace-verified-copy", "original_path": str(source), "relative_backup": "workspace-verified-copy", "file_count": len(workspace_copy_records), "size_bytes": sum(int(row["size_bytes"]) for row in workspace_copy_records), "tree_sha256": tree_hash(workspace_copy_records), "ownership": "user-owned-evidence", "auto_purge": "never"},
        {"id": "user-original", "original_path": str(user_skills), "relative_backup": "user-original", "file_count": len(user_copy_records), "size_bytes": sum(int(row["size_bytes"]) for row in user_copy_records), "tree_sha256": tree_hash(user_copy_records), "ownership": "user-owned-evidence", "auto_purge": "never"},
    ]
    manifest = {
        "schema_version": BACKUP_SCHEMA,
        "retention": "permanent-until-explicit-user-authorized-export-or-removal",
        "migration_journal": ".px/skill-first-initialization/journal.json",
        "matching_snapshots": [
            ".px/skill-first-initialization/workspace-snapshot-a.json",
            ".px/skill-first-initialization/workspace-snapshot-b.json",
        ],
        "sources": sources,
    }
    if not (snapshot / "manifest.json").exists():
        _write_json(snapshot / "manifest.json", manifest)
    preserved = _preserved_records(
        root, snapshot / "user-original", ".px/preserved-skills/initial/user-original"
    )
    enterprise = json.loads(
        (root / "registry" / "ms_enterprise_catalog.json").read_text(encoding="utf-8")
    )
    enterprise_records = [{
        "id": str(row["id"]), "version": "catalog", "status": str(row.get("status", "metadata-only")), "description": str(row.get("summary", "")),
        "tags": [str(row.get("pack", ""))], "domain": "enterprise-restricted", "origin": "px-enterprise-catalog", "native": False,
        "adapted": False, "default_eligible": False, "body_available": False, "package_root": None, "body": None, "body_sha256": None,
        "backup": None, "admission": str(row.get("status", "metadata-only"))
    } for row in enterprise.get("skills", ())]
    index = build_skill_index([*native_records, *preserved, *enterprise_records])
    _validate_projection_sets(root, index)
    _write_json(px / "skill-index.json", index)
    backup_validation = verify_backup(snapshot)
    if not backup_validation["valid"]:
        raise RuntimeError(f"backup verification failed: {backup_validation['errors']}")
    _regenerate_skill_projection(root)
    _journal_write(journal_path, journal, "committed")
    return _migration_result(index, backup_validation, journal)


def rewrite_catalog(root: Path) -> dict[str, object]:
    path = root.resolve() / "registry" / "skill_catalog.toml"
    before = path.read_text(encoding="utf-8")
    after = before.replace('body = ".agents/skills/', 'body = ".px/skills/')
    replacements = before.count('body = ".agents/skills/')
    if replacements == 0:
        return {"rewritten": 0, "path": path.as_posix()}
    path.write_text(after, encoding="utf-8")
    return {"rewritten": replacements, "path": path.as_posix()}


def _validate_projection_sets(root: Path, index: dict[str, object]) -> None:
    record_ids = {
        str(row["id"])
        for row in index["records"]
        if row.get("domain") == "px-standard" and row.get("native")
    }
    catalog = tomllib.loads(
        (root / "registry" / "skill_catalog.toml").read_text(encoding="utf-8")
    )
    catalog_ids = {str(row["id"]) for row in catalog.get("skills", ())}
    package_ids = {
        path.name for path in (root / ".px" / "skills").iterdir() if path.is_dir()
    }
    if not (record_ids == catalog_ids == package_ids):
        raise RuntimeError(
            "skill record/catalog/package denominators disagree: "
            f"records={len(record_ids)} catalog={len(catalog_ids)} packages={len(package_ids)}"
        )


def refresh_eligibility(root: Path) -> dict[str, object]:
    root = root.resolve()
    _recover_publication_transactions(root)
    index_path = root / ".px" / "skill-index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    validate_skill_index(index, require_derived=True)
    updates: dict[Path, bytes] = {}
    changed = 0
    for row in index.get("records", ()):
        if row.get("domain") != "px-standard":
            continue
        eligible = str(row.get("admission") or row.get("status")) in {"active", "admitted"}
        if row.get("default_eligible") != eligible:
            row["default_eligible"] = eligible
            changed += 1
        package_root = row.get("package_root")
        if package_root:
            manifest_path = root / str(package_root) / "capability.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest.setdefault("isolation", {})["default_eligible"] = eligible
            rendered_manifest = (
                json.dumps(manifest, indent=2, sort_keys=True) + "\n"
            ).encode("utf-8")
            updates[manifest_path] = rendered_manifest
            updates[manifest_path.parent / "skill.yaml"] = rendered_manifest
    records = index.get("records", ())
    rebuilt = build_skill_index(records, template=index)
    _validate_projection_sets(root, rebuilt)
    updates[index_path] = (
        json.dumps(rebuilt, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    project = root / "pyproject.toml"
    updates[project] = _render_skill_projection(root).encode("utf-8")
    _commit_publication(root, updates, operation="refresh-eligibility")
    return {"changed": changed, "records": len(records)}


def rewrite_operational_paths(root: Path) -> dict[str, object]:
    root = root.resolve()
    files = [root / "pyproject.toml"]
    for directory in (root / "runtime", root / "tests", root / "scripts"):
        files.extend(directory.rglob("*.py"))
    files.extend((root / "registry" / "skill_packages").glob("*.json"))
    for name in (
        "build_claims.json", "assurance_capabilities.json", "declared_suite_authoritative_tools.json",
        "contract_ownership.json", "effect_surface_ownership.json", "engineering_reasoning_expansion.json",
        "incomplete_finding_reviews.json", "knowledge_sources.json", "operational_capabilities.json",
        "planning_card_coverage.json", "external_skill_bundles.json",
        "corrective_release_ledger.json", "declared_suite_reconstruction.json",
        "external_capability_catalog.json", "root_intake_admission.json",
    ):
        files.append(root / "registry" / name)
    intentional_agent_paths = {"migrate_px_skills.py", "sync_skill_packaging.py"}
    files = sorted({path for path in files if path.name not in intentional_agent_paths})
    changed_files = 0
    replacements = 0
    for path in files:
        text = path.read_text(encoding="utf-8")
        count = text.count(".agents/skills")
        if not count:
            continue
        path.write_text(text.replace(".agents/skills", ".px/skills"), encoding="utf-8")
        changed_files += 1
        replacements += count
    _regenerate_skill_projection(root)
    return {"changed_files": changed_files, "replacements": replacements, "facades": len(list((root / ".agents" / "skills").iterdir())), "native_packages": len(list((root / ".px" / "skills").iterdir()))}


def seal_backup_inventories(root: Path) -> dict[str, object]:
    snapshot = root.resolve() / ".px" / "preserved-skills" / "initial"
    manifest_path = snapshot / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    total = 0
    for source in manifest.get("sources", ()):
        records = inventory_tree(snapshot / str(source["relative_backup"]))
        inventory = {"schema_version": "px.skill-file-inventory/1.0", "source_id": source["id"], "file_count": len(records), "tree_sha256": tree_hash(records), "files": records}
        relative = f"inventories/{source['id']}.json"
        inventory_path = snapshot / relative
        _write_json(inventory_path, inventory)
        source["inventory"] = relative
        source["inventory_sha256"] = _sha(inventory_path)
        total += len(records)
    _write_json(manifest_path, manifest)
    verification = verify_backup(snapshot)
    if not verification["valid"]:
        raise RuntimeError(f"sealed backup verification failed: {verification['errors']}")
    return {"valid": True, "sources": len(manifest.get("sources", ())), "file_records": total}


def repair_pyproject_projection(root: Path) -> dict[str, object]:
    root = root.resolve()
    path = root / "pyproject.toml"
    before = path.read_text(encoding="utf-8")
    index = json.loads((root / ".px" / "skill-index.json").read_text(encoding="utf-8"))
    validate_skill_index(index, require_derived=True)
    _validate_projection_sets(root, index)
    rendered = _regenerate_skill_projection(root)
    return {
        "valid": True,
        "changed": rendered != before,
        "canonical_generator": "scripts/migration/sync_skill_packaging.py",
    }


def _regenerate_skill_projection(root: Path) -> str:
    """Use the single packaging generator and refuse an invalid TOML result."""
    rendered = _render_skill_projection(root)
    project = root / "pyproject.toml"
    prepared = project.with_name(f".{project.name}.{uuid4().hex}.prepared")
    prepared.write_text(rendered, encoding="utf-8", newline="\n")
    prepared.replace(project)
    return rendered


def _render_skill_projection(root: Path) -> str:
    script = root / "scripts" / "migration" / "sync_skill_packaging.py"
    if not script.is_file():
        script = PROJECT_ROOT / "scripts" / "migration" / "sync_skill_packaging.py"
    spec = importlib.util.spec_from_file_location("px_sync_skill_packaging", script)
    if not spec or not spec.loader:
        raise RuntimeError("canonical skill packaging generator is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    project = root / "pyproject.toml"
    rendered = module.render(project.read_text(encoding="utf-8"), root)
    import tomllib

    tomllib.loads(rendered)
    return rendered


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--user-skills", type=Path, required=True)
    parser.add_argument("--rewrite-catalog-only", action="store_true")
    parser.add_argument("--refresh-eligibility", action="store_true")
    parser.add_argument("--rewrite-operational-paths", action="store_true")
    parser.add_argument("--seal-backup-inventories", action="store_true")
    parser.add_argument("--repair-pyproject-projection", action="store_true")
    args = parser.parse_args()
    result = repair_pyproject_projection(args.root) if args.repair_pyproject_projection else seal_backup_inventories(args.root) if args.seal_backup_inventories else rewrite_operational_paths(args.root) if args.rewrite_operational_paths else refresh_eligibility(args.root) if args.refresh_eligibility else rewrite_catalog(args.root) if args.rewrite_catalog_only else migrate(args.root, args.user_skills)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
