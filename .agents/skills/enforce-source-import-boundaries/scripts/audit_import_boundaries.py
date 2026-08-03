#!/usr/bin/env python3
"""Audit declared import boundaries and mirrored-contract parity without mutation."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
from pathlib import Path

EXCLUDES = {".git", ".venv", "node_modules", "vendor", "dist", "build", "quarantine"}
JS_IMPORT = re.compile(r"(?m)^\s*(?:import|export)\b[^\n]*?from\s*['\"]([^'\"]+)['\"]|\brequire\(\s*['\"]([^'\"]+)['\"]\s*\)")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _imports(path: Path) -> list[tuple[int, str]]:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".py":
        tree = ast.parse(text, filename=str(path))
        found: list[tuple[int, str]] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found.extend((node.lineno, alias.name) for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                found.append((node.lineno, "." * node.level + (node.module or "")))
        return found
    return [(text.count("\n", 0, match.start()) + 1, match.group(1) or match.group(2)) for match in JS_IMPORT.finditer(text)]


def audit(root: Path, policy_path: Path) -> dict:
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    forbidden = [re.compile(item) for item in policy.get("forbidden_import_patterns", [])]
    findings: list[dict] = []
    scanned = 0
    for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d.casefold() not in EXCLUDES)
        for name in sorted(files, key=str.casefold):
            path = Path(current, name)
            if path.suffix.lower() not in {".py", ".js", ".jsx", ".ts", ".tsx"} or path.is_symlink():
                continue
            scanned += 1
            rel = path.relative_to(root).as_posix()
            try:
                imports = _imports(path)
            except (OSError, UnicodeError, SyntaxError) as exc:
                findings.append({"path": rel, "line": 0, "rule": "unscannable-source", "detail": type(exc).__name__})
                continue
            for line, target in imports:
                if any(pattern.search(target) for pattern in forbidden):
                    findings.append({"path": rel, "line": line, "rule": "forbidden-import", "target": target})
                if target.startswith("..."):
                    findings.append({"path": rel, "line": line, "rule": "package-relative-escape", "target": target})
    for pair in policy.get("mirrored_contracts", []):
        left, right = root / pair["canonical"], root / pair["mirror"]
        if not left.is_file() or not right.is_file():
            findings.append({"path": pair.get("mirror", "unknown"), "line": 0, "rule": "mirror-missing"})
        elif _sha(left) != _sha(right):
            findings.append({"path": pair["mirror"], "line": 0, "rule": "mirror-hash-mismatch"})
    findings.sort(key=lambda item: (item["path"], item["line"], item["rule"]))
    return {"schema_version": "1.0", "complete": True, "files_scanned": scanned, "findings": findings}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--policy", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = audit(args.root.resolve(), args.policy.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"files_scanned": result["files_scanned"], "findings": len(result["findings"])}))
    return 0 if not result["findings"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
