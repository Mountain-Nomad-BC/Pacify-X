"""Build and check the inactive external-candidate skill registry projection."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from runtime.json_io import load_json_object  # noqa: E402
from runtime.evidence_portability import rewrite_reference_literals  # noqa: E402

ACTIVE_ID = "govern-external-capability-intake"
EVIDENCE = "tests/test_external_capability_provider.py"


def _render(value: object) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"


def _tags(identifier: str, candidates: list[dict[str, object]]) -> list[str]:
    categories = {
        str(candidate.get("category", ""))
        for candidate in candidates
        if candidate.get("bundle") == identifier and candidate.get("category")
    }
    return sorted(set(identifier.split("-")) | categories | {"external-candidate"})


def _candidate_manifest(
    root: Path, bundle: dict[str, object], candidates: list[dict[str, object]]
) -> dict[str, object]:
    body = str(bundle["body"])
    return {
        "id": bundle["id"],
        "version": bundle["version"],
        "status": "mapped_deferred",
        "body": body,
        "body_sha256": hashlib.sha256((root / body).read_bytes()).hexdigest(),
        "references": sorted(map(str, bundle.get("references", ()))),
        "capability_tags": _tags(str(bundle["id"]), candidates),
        "effects": sorted(map(str, bundle.get("effects", ()))),
        "provenance": {
            "type": "inactive_external_candidate_wrapper",
            "basis": [
                "registry/external_capability_candidates.json",
                "registry/external_capability_licenses.json",
            ],
            "canonical_owner": bundle["owner"],
            "source_licenses": bundle.get("source_licenses", []),
            "candidate_capabilities": bundle.get("candidate_capabilities", []),
        },
        "clean_room": "hyperlearning-clean-room" in bundle.get("source_licenses", []),
        "tests": EVIDENCE,
        "evidence": EVIDENCE,
        "validation_freshness": "current",
        "context_budget_bytes": 24_576,
    }


def _active_manifest(root: Path) -> dict[str, object]:
    body = f".px/skills/{ACTIVE_ID}/SKILL.md"
    return {
        "id": ACTIVE_ID,
        "version": "1.0.0",
        "status": "active",
        "body": body,
        "body_sha256": hashlib.sha256((root / body).read_bytes()).hexdigest(),
        "references": [f".px/skills/{ACTIVE_ID}/references/runtime-contract.md"],
        "capability_tags": [
            "admission",
            "external-candidates",
            "hooks",
            "routing",
            "session-fabric",
            "staging",
        ],
        "effects": ["read_local", "write_workspace"],
        "provenance": {
            "type": "sanitized_clean_room_integration",
            "basis": [
                "registry/external_capability_catalog.json",
                "contracts/external_capabilities/selective-stage-plan.schema.json",
                EVIDENCE,
            ],
            "canonical_owner": "runtime/external_capability_provider.py",
        },
        "clean_room": True,
        "tests": EVIDENCE,
        "evidence": EVIDENCE,
        "validation_freshness": "current",
        "context_budget_bytes": 24_576,
    }


def build(root: Path) -> dict[str, object]:
    root = root.resolve(strict=True)
    bundle_document = load_json_object(root / "registry/external_skill_bundles.json")
    candidate_document = load_json_object(
        root / "registry/external_capability_candidates.json"
    )
    bundles = list(bundle_document["packages"])
    candidates = list(candidate_document["capabilities"])
    skill_catalog = tomllib.loads(
        (root / "registry/skill_catalog.toml").read_text(encoding="utf-8")
    )
    active_catalog_ids = {
        str(skill["id"])
        for skill in skill_catalog.get("skills", ())
        if skill.get("status") in {"active", "admitted"}
    }
    bundle_ids = {str(bundle["id"]) for bundle in bundles}
    promoted = active_catalog_ids & bundle_ids
    manifests = {
        str(bundle["id"]): _candidate_manifest(root, bundle, candidates)
        for bundle in bundles
        if str(bundle["id"]) not in promoted
    }
    manifests[ACTIVE_ID] = _active_manifest(root)
    return {"manifests": manifests, "bundles": bundles, "promoted": promoted}


def reconcile(root: Path, *, check: bool) -> dict[str, object]:
    projection = build(root)
    manifests = projection["manifests"]
    promoted = projection["promoted"]
    drift: list[str] = []
    catalog_path = root / "registry/external_capability_catalog.json"
    catalog = load_json_object(catalog_path)
    portable_catalog = rewrite_reference_literals(
        catalog,
        {"../common/": "source-reference:common/"},
    )
    rendered_catalog = _render(portable_catalog)
    if catalog_path.read_text(encoding="utf-8") != rendered_catalog:
        drift.append(catalog_path.relative_to(root).as_posix())
        if not check:
            catalog_path.write_text(rendered_catalog, encoding="utf-8", newline="\n")
    for identifier, manifest in manifests.items():
        path = root / "registry/skill_packages" / f"{identifier}.json"
        rendered = _render(manifest)
        if not path.is_file() or path.read_text(encoding="utf-8") != rendered:
            drift.append(path.relative_to(root).as_posix())
            if not check:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(rendered, encoding="utf-8", newline="\n")

    ledger_path = root / "registry/admission_ledger.json"
    ledger = load_json_object(ledger_path)
    by_id = {str(item["id"]): item for item in ledger["records"]}
    desired_ledger: dict[str, dict[str, object]] = {}
    for identifier, manifest in manifests.items():
        active = identifier == ACTIVE_ID
        desired_ledger[identifier] = {
            "effects": manifest["effects"],
            "id": identifier,
            "implementation": "clean_room" if active else "candidate_wrapper",
            "notes": (
                "Canonical metadata-first intake control with behavioral validation."
                if active
                else "Inactive external candidate; admission and project-local review are required before hydration."
            ),
            "source_disposition": "merge" if active else "reference_only",
            "status": "active" if active else "mapped_deferred",
            "validation": {"failed": 0, "passed": 8},
        }
    if any(
        by_id.get(identifier) != record for identifier, record in desired_ledger.items()
    ):
        drift.append("registry/admission_ledger.json")
        if not check:
            by_id.update(desired_ledger)
            ledger["records"] = [by_id[key] for key in sorted(by_id)]
            ledger_path.write_text(_render(ledger), encoding="utf-8", newline="\n")

    catalog_path = root / "registry/skill_catalog.toml"
    catalog = catalog_path.read_text(encoding="utf-8")
    additions: list[str] = []
    for identifier, manifest in sorted(manifests.items()):
        marker = f'id = "{identifier}"'
        if marker in catalog:
            continue
        tags = ", ".join(json.dumps(tag) for tag in manifest["capability_tags"])
        additions.append(
            "\n[[skills]]\n"
            f'id = "{identifier}"\n'
            f'version = "{manifest["version"]}"\n'
            f'status = "{manifest["status"]}"\n'
            f'body = "{manifest["body"]}"\n'
            f'contract = "registry/skill_packages/{identifier}.json"\n'
            f'admission_record = "{identifier}"\n'
            f"tags = [{tags}]\n"
        )
    if additions:
        drift.append("registry/skill_catalog.toml")
        if not check:
            catalog_path.write_text(
                catalog.rstrip() + "\n" + "".join(additions),
                encoding="utf-8",
                newline="\n",
            )

    return {
        "valid": not drift,
        "checked_manifest_count": len(manifests),
        "candidate_manifest_count": len(manifests) - 1,
        "active_control_count": 1,
        "promoted_bundle_count": len(promoted),
        "drift": sorted(set(drift)),
        "changed": [] if check else sorted(set(drift)),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    result = reconcile(args.root.resolve(), check=args.check)
    print(_render(result), end="")
    raise SystemExit(0 if (result["valid"] or not args.check) else 1)
