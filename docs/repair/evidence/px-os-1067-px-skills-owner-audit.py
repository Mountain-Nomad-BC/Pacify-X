"""PX-OS-1067 Priority 5 — `.px/skills` producer ownership architecture evidence.

Read-only. Establishes, from source and repository state, what the 11 unresolved
`.px/skills` producers actually are: how they are invoked, where they write, and
whether they own durable state. It creates no classification, grant, or approval.

Run:  .venv-repair\\Scripts\\python.exe docs\\repair\\evidence\\px-os-1067-px-skills-owner-audit.py
"""
from __future__ import annotations

import ast
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from runtime.effect_surface import _call_name, discover_effect_surfaces  # noqa: E402

OUTPUT = Path(__file__).with_name("px-os-1067-px-skills-owner-audit.json")
CENSUS = Path(__file__).with_name("px-os-1067-census-2026-11-03.json")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def provenance(relative: str) -> dict[str, object]:
    """Installation provenance from packaging metadata, never from the folder name."""
    skill = relative.split("/")[1]
    manifest_path = ROOT / ".px/skills" / skill / "capability.json"
    front = ROOT / ".px/skills" / skill / "SKILL.md"
    record: dict[str, object] = {
        "skill": skill,
        "capability_json": manifest_path.exists(),
        "skill_md": front.exists(),
        "tracked_by_git": (ROOT / relative).exists()
        and bool(
            __import__("subprocess").run(
                ["git", "ls-files", "--error-unmatch", relative],
                cwd=ROOT,
                capture_output=True,
            ).returncode
            == 0
        ),
    }
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        record["manifest_keys"] = sorted(manifest)
        for key in ("id", "version", "status", "body", "contract", "native", "lazy", "entrypoint"):
            if key in manifest:
                record[key] = manifest[key]
    return record


def callers(relative: str) -> list[str]:
    """Tracked references to this producer outside its own skill folder.

    Packaging, catalog, contract, and test references are what make a script an
    installed asset rather than a free-standing tool.
    """
    result = __import__("subprocess").run(
        ["git", "grep", "-l", "-F", relative.split("/")[-1], "--", "registry", "scripts", "runtime", "tests", "docs"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode not in (0, 1):
        return []
    return sorted(line for line in result.stdout.splitlines() if line)


def direct_effects(records: list[dict], relative: str) -> list[dict]:
    effects = []
    for record in records:
        if record["path"] != relative:
            continue
        effects.append(
            {
                "id": record["id"],
                "line": record["line"],
                "call": record["call"],
                "effect": record["effect"],
                "destructive": record["destructive"],
                "policy": record["policy"],
            }
        )
    return sorted(effects, key=lambda item: item["line"])


def destination_shape(relative: str) -> dict[str, object]:
    """Static facts about argument handling; not an ownership decision."""
    tree = ast.parse((ROOT / relative).read_text(encoding="utf-8-sig"))
    flags = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _call_name(node) in {"argparse.ArgumentParser"}:
            flags.add("argparse")
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in {"--out", "--output", "--json-out", "--report"}:
            flags.add(f"option:{node.value}")
    has_main = any(
        isinstance(node, ast.If)
        and "__main__" in ast.unparse(node.test)
        for node in ast.walk(tree)
    )
    if has_main:
        flags.add("script_entrypoint")
    return {"static_signals": sorted(flags)}


def main() -> int:
    census = json.loads(CENSUS.read_text(encoding="utf-8"))
    targets = [path for path in census["unresolved_paths"] if path.startswith(".px/skills/")]
    records = discover_effect_surfaces(ROOT)
    producers = []
    for relative in targets:
        effects = direct_effects(records, relative)
        producers.append(
            {
                "path": relative,
                "source_sha256": sha(ROOT / relative),
                "provenance": provenance(relative),
                "external_references": callers(relative),
                "direct_effects": effects,
                "effect_kinds": sorted({item["effect"] for item in effects}),
                "destructive_effects": [item for item in effects if item["destructive"]],
                "destination": destination_shape(relative),
                "disposition": "unresolved",
                "reason_unresolved": (
                    "No permitted destination root grant and no reviewed control-custody "
                    "entry covers this skill script. Its output class is caller-selected "
                    "or generated publication; neither establishes write authority."
                ),
            }
        )
    document = {
        "schema_version": "px.px-skills-owner-audit/1.0",
        "gap_id": "PX-OS-1067",
        "priority": 5,
        "measurement": "read-only source and repository inventory",
        "census_source": CENSUS.name,
        "population": len(producers),
        "population_reconciles": len(producers) == census["unresolved_by_family"].get(".px"),
        "role_categories_used": [
            "runtime implementation",
            "packaged asset",
            "generated projection",
            "installation artifact",
            "development fixture",
            "persistent state",
        ],
        "role_categories_status": "investigation categories only — none is an approved classification",
        "producers": producers,
        "summary": {
            "with_capability_manifest": sum(1 for p in producers if p["provenance"]["capability_json"]),
            "tracked": sum(1 for p in producers if p["provenance"]["tracked_by_git"]),
            "with_external_references": sum(1 for p in producers if p["external_references"]),
            "destructive_producers": [p["path"] for p in producers if p["destructive_effects"]],
            "resolved": 0,
        },
        "decision_register": {
            "outstanding": "Architectural role and ownership model per skill script.",
            "authority": "Requires governed approval; this report proposes nothing as approved.",
        },
    }
    OUTPUT.write_text(json.dumps(document, indent=1, sort_keys=True), encoding="utf-8")
    print(json.dumps(document["summary"], indent=1))
    print(f"population_reconciles={document['population_reconciles']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
