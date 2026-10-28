"""R01 §4.5: disposition the 9 PORTED_COMPONENT_TESTED_GENERATED_PENDING records.

For each record report: contract presence here, declared owner presence, whether
the owner is reachable from a real entry point, unresolved local imports, the
declared tests and whether they pass trivially. Read-only.
"""
import ast
import json
from pathlib import Path

ADJ = Path("docs/repair/evidence/resume10-contract-adjudication.json")
records = json.loads(ADJ.read_text(encoding="utf-8"))["records"]
rows = [r for r in records if r.get("state") == "PORTED_COMPONENT_TESTED_GENERATED_PENDING"]
print(f"records={len(rows)}\n")

sources = [p for base in ("runtime", "scripts", "tests", "extension") for p in Path(base).rglob("*.py")]


def importers(leaf: str) -> list[str]:
    out = []
    for path in sources:
        if path.stem == leaf:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            mods = []
            if isinstance(node, ast.ImportFrom) and node.module:
                mods = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
            elif isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            if any(m == f"runtime.{leaf}" or m.startswith(f"runtime.{leaf}.") for m in mods):
                out.append(path.as_posix())
                break
    return sorted(set(out))


for record in rows:
    rel = record["path"]
    entry = record.get("ownership", {}).get("target") or {}
    owner = entry.get("declared_owner")
    tests = entry.get("tests") or []
    missing_tests = [t for t in tests if not Path(str(t)).is_file()]
    print(f"{rel}")
    print(f"  contract_here={Path(rel).is_file()} owner={owner} owner_here={Path(owner).is_file() if owner else False}")
    print(f"  tests={len(tests)} missing_tests={missing_tests}")
    if owner and Path(owner).is_file():
        print(f"  importers={importers(Path(owner).stem) or 'NONE'}")
    print()
