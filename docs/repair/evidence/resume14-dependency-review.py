"""R01 dependency review: the 12 DEPENDENCY_REVIEW_REQUIRED adjudication records.

Read-only. For each record determines, against the live tree and the reference
worktree, whether the contract is present, whether its declared owner and tests
exist, whether the owner is reachable from anything in this checkout, and
whether the owner's own intra-repo imports resolve here.

Verdicts:
  TARGET_PRESENT        contract already reconciled into this checkout
  REFERENCE_ONLY_*      contract absent here; owner/test situation as printed
"""
import ast
import json
import re
from pathlib import Path

ADJ = Path("docs/repair/evidence/resume10-contract-adjudication.json")
REF = Path(r"C:\Users\Ben\Music\Pacify-X-rollout-20261024")
RECORD = Path("docs/repair/evidence/resume14-dependency-review.json")

records = json.loads(ADJ.read_text(encoding="utf-8"))["records"]
rows = [r for r in records if r.get("state") == "DEPENDENCY_REVIEW_REQUIRED"]

sources = [p for base in ("runtime", "scripts", "tests") for p in Path(base).rglob("*.py")]


def importers_of(module_leaf: str) -> list[str]:
    found = []
    for path in sources:
        if path.stem == module_leaf:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            full = []
            if isinstance(node, ast.ImportFrom) and node.module:
                full = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
            elif isinstance(node, ast.Import):
                full = [a.name for a in node.names]
            if any(f == f"runtime.{module_leaf}" or f.startswith(f"runtime.{module_leaf}.") for f in full):
                found.append(path.as_posix())
                break
    return sorted(set(found))


def resolve_local(module: str) -> bool:
    parts = module.split(".")
    if parts[0] != "runtime":
        return Path(*parts).with_suffix(".py").is_file()
    base = Path("runtime")
    rest = parts[1:]
    for size in range(len(rest), 0, -1):
        candidate = base.joinpath(*rest[:size])
        if candidate.with_suffix(".py").is_file() or (candidate / "__init__.py").is_file():
            return True
    return False


result = []
for record in rows:
    rel = record["path"]
    here, ref = Path(rel), REF / rel
    entry = record["ownership"].get("reference") or {}
    owner = entry.get("declared_owner")
    owner_here = bool(owner) and Path(owner).is_file()
    tests = entry.get("tests") or []
    missing_tests = [t for t in tests if not Path(t).is_file()]
    item = {
        "contract": rel,
        "contract_here": here.is_file(),
        "contract_in_reference": ref.is_file(),
        "owner": owner,
        "owner_here": owner_here,
        "missing_tests": missing_tests,
    }
    if owner_here:
        leaf = Path(owner).stem
        item["importers"] = importers_of(leaf)
        tree = ast.parse(Path(owner).read_text(encoding="utf-8"))
        local = {
            n.module
            for n in ast.walk(tree)
            if isinstance(n, ast.ImportFrom) and n.module and n.module.split(".")[0] == "runtime"
        }
        item["unresolved_imports"] = sorted(m for m in local if not resolve_local(m))
    if here.is_file():
        item["verdict"] = "TARGET_PRESENT"
    elif not owner_here:
        item["verdict"] = "REFERENCE_ONLY_OWNER_ABSENT"
    elif item["unresolved_imports"]:
        item["verdict"] = "REFERENCE_ONLY_OWNER_BLOCKED_BY_MISSING_DEPS"
    elif not item["importers"]:
        item["verdict"] = "REFERENCE_ONLY_OWNER_UNREACHABLE_HERE"
    else:
        item["verdict"] = "REFERENCE_ONLY_PORT_CANDIDATE"
    result.append(item)

summary = {}
for item in result:
    summary[item["verdict"]] = summary.get(item["verdict"], 0) + 1

for item in result:
    print(f"{item['verdict']:<44} {item['contract']}")
    print(f"    owner={item['owner']} owner_here={item['owner_here']} "
          f"importers={item.get('importers', 'n/a')} "
          f"unresolved={item.get('unresolved_imports', 'n/a')} "
          f"missing_tests={item['missing_tests']}")
print()
print("SUMMARY", json.dumps(summary, indent=1))

RECORD.write_text(
    json.dumps(
        {
            "schema_version": "px.repair-dependency-review/1.0",
            "generated_by": "docs/repair/evidence/resume14-dependency-review.py",
            "source_adjudication": ADJ.as_posix(),
            "record_count": len(result),
            "summary": summary,
            "records": result,
            "note": (
                "Read-only review. A REFERENCE_ONLY verdict is not a port decision: "
                "porting requires the owner's behaviour, callers and tests to be "
                "reconciled against this checkout, and unreachable owners add no "
                "operating behaviour."
            ),
        },
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)
print("wrote", RECORD)
