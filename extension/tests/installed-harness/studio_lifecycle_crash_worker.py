from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

RUNTIME_ROOT = Path(os.environ.get("PX_OWNED_ENGINE_ROOT", Path(__file__).resolve().parents[3])).resolve()
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

import runtime.skill_studio as skill_studio_module
from runtime.native_skills import build_skill_index
from runtime.skill_studio import SkillStudio, _tree_attestation
from runtime.studio_models import SkillPackage


CRASH_EXIT = 91


def _source(root: Path, name: str, version: str) -> Path:
    target = root / name
    for relative in ("contracts", "agents", "tests", "resources"):
        (target / relative).mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": "px.native-skill-package/1.0",
        "id": "installed-crash",
        "version": version,
        "domain": "px-standard",
    }
    encoded = json.dumps(manifest, indent=2) + "\n"
    (target / "SKILL.md").write_text(f"# Installed crash {version}\n", encoding="utf-8")
    (target / "capability.json").write_text(encoded, encoding="utf-8")
    (target / "skill.yaml").write_text(encoded, encoding="utf-8")
    (target / "agents/openai.yaml").write_text(
        'interface:\n  display_name: "Installed crash"\n  short_description: "Owned lifecycle crash fixture"\n',
        encoding="utf-8",
    )
    (target / "contracts/manifest.json").write_text(
        json.dumps({"schema_version": "px.skill-contract-links/1.0", "contracts": []}) + "\n",
        encoding="utf-8",
    )
    (target / "tests/validation.json").write_text(
        json.dumps({
            "schema_version": "px.skill-test/1.1",
            "cases": [{"name": "required", "assertion": {"kind": "required-files", "paths": ["SKILL.md", "capability.json", "skill.yaml"]}}],
        }) + "\n",
        encoding="utf-8",
    )
    (target / "resources/index.json").write_text(
        json.dumps({
            "schema_version": "px.skill-resources/1.0",
            "resources": ["agents/openai.yaml", "capability.json", "contracts/manifest.json", "SKILL.md", "skill.yaml", "tests/validation.json"],
        }) + "\n",
        encoding="utf-8",
    )
    return target


def _package(version: str) -> SkillPackage:
    return SkillPackage(
        "skill:installed-crash", version, "px-owned-walker", ("verify lifecycle",),
        ("unrelated",), ("read",), ("read",), ("resources/index.json",),
        ("contracts/manifest.json",), ("tests/validation.json",),
        {"source": "owned-installed-harness", "license": "Apache-2.0"},
    )


def _scaffold(root: Path) -> None:
    (root / "registry/skill_packages").mkdir(parents=True, exist_ok=True)
    (root / "registry/admission_ledger.json").write_text(json.dumps({
        "schema_version": "1.0", "allowed_dispositions": ["adopt"],
        "promotion_requirements": [], "records": [],
    }), encoding="utf-8")
    (root / "registry/skill_catalog.toml").write_text('schema_version = "1.0"\n', encoding="utf-8")
    (root / ".px").mkdir(exist_ok=True)
    (root / ".px/skill-index.json").write_text(json.dumps(build_skill_index([])), encoding="utf-8")


def _stage(studio: SkillStudio, root: Path, version: str, name: str) -> tuple[SkillPackage, dict[str, object]]:
    package = _package(version)
    source = _source(root, name, version)
    token = studio.admit_source(source, approved_by="px-owned-walker")
    studio.stage_draft(package, source, source_token=token)
    assert studio.validate(package)["passed"] is True
    assert studio.admit(package, approved=True, approver="px-owned-walker")["decision"] == "admitted"
    return package, {"source": str(source)}


def _terminate_on_first_projection(root: Path) -> None:
    original = skill_studio_module._atomic_bytes
    fired = False

    def terminate(path: Path, payload: bytes) -> None:
        nonlocal fired
        if not fired and path == root / ".px/skill-index.json":
            fired = True
            os._exit(CRASH_EXIT)
        original(path, payload)

    skill_studio_module._atomic_bytes = terminate


def crash_promotion(root: Path) -> None:
    _scaffold(root)
    studio = SkillStudio(root)
    package, _ = _stage(studio, root, "1.0.0", "promotion-source")
    _terminate_on_first_projection(root)
    studio.promote(package, approved=True)
    raise RuntimeError("promotion crash boundary was not reached")


def crash_rollback(root: Path) -> None:
    _scaffold(root)
    studio = SkillStudio(root)
    first, _ = _stage(studio, root, "1.0.0", "rollback-first")
    studio.promote(first, approved=True)
    second, _ = _stage(studio, root, "1.1.0", "rollback-second")
    studio.promote(second, approved=True)
    promotion_receipt = next((root / ".engineering-bootstrap/studios/skills").glob("*/revisions/1.1.0/promotion-receipt.json"))
    _terminate_on_first_projection(root)
    studio.rollback(promotion_receipt, approved=True, approver="px-owned-walker")
    raise RuntimeError("rollback crash boundary was not reached")


def recover(root: Path, operation: str) -> None:
    studio = SkillStudio(root)
    recovery = studio.recover_lifecycle_transactions()
    canonical = root / ".px/skills/installed-crash"
    version = "1.0.0" if operation == "promotion" else "1.0.0"
    receipt_name = "promotion-receipt.json" if operation == "promotion" else "rollback-receipt.json"
    receipt = next((root / ".engineering-bootstrap/studios/skills").glob(f"*/revisions/{'1.0.0' if operation == 'promotion' else '1.1.0'}/{receipt_name}"))
    verified = studio.authority.verify_receipt(json.loads(receipt.read_text(encoding="utf-8")))
    print(json.dumps({
        "schema_version": "px.installed-studio-lifecycle-crash/1.0",
        "operation": operation,
        "crash_exit": CRASH_EXIT,
        "canonical_exists": canonical.is_dir(),
        "canonical_tree_sha256": _tree_attestation(canonical)[1],
        "receipt_relative": receipt.relative_to(root).as_posix(),
        "receipt_version": verified["version"],
        "expected_canonical_version": version,
        "recovery": recovery,
    }, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--operation", choices=("promotion", "rollback"), required=True)
    parser.add_argument("--recover", action="store_true")
    args = parser.parse_args()
    args.root = args.root.resolve()
    args.root.mkdir(parents=True, exist_ok=True)
    if args.recover:
        recover(args.root, args.operation)
    elif args.operation == "promotion":
        crash_promotion(args.root)
    else:
        crash_rollback(args.root)


if __name__ == "__main__":
    main()
