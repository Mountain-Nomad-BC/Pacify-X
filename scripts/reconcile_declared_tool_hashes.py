"""Reconcile exact-tool target hashes and their lazy reference indexes."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _render(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def expected(root: Path) -> dict[str, bytes]:
    registry_path = root / "registry/declared_suite_authoritative_tools.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    outputs: dict[str, bytes] = {}
    owner_refs: dict[str, list[tuple[str, Path]]] = {}
    for record in registry["admitted"]:
        target = root / record["target"]
        record["source_sha256"] = _sha(target)
        parts = Path(record["target"]).parts
        owner = parts[2]
        reference = root / ".agents/skills" / owner / "references/scripts" / f"{record['id']}.json"
        contract = json.loads(reference.read_text(encoding="utf-8"))
        contract["authoritative_source_sha256"] = record["source_sha256"]
        relative = reference.relative_to(root).as_posix()
        outputs[relative] = _render(contract)
        owner_refs.setdefault(owner, []).append((record["id"], reference))
    outputs[registry_path.relative_to(root).as_posix()] = _render(registry)
    for owner, references in owner_refs.items():
        index_path = root / ".agents/skills" / owner / "references/scripts-index.json"
        index = json.loads(index_path.read_text(encoding="utf-8"))
        by_id = {item["id"]: item for item in index["records"]}
        for identifier, reference in references:
            relative = reference.relative_to(root).as_posix()
            by_id[identifier]["sha256"] = hashlib.sha256(outputs[relative]).hexdigest()
        outputs[index_path.relative_to(root).as_posix()] = _render(index)
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    outputs = expected(ROOT)
    stale = [relative for relative, payload in outputs.items() if not (ROOT / relative).is_file() or (ROOT / relative).read_bytes() != payload]
    if args.check:
        print(json.dumps({"valid": not stale, "files": len(outputs), "stale": stale}))
        return 0 if not stale else 1
    for relative, payload in outputs.items():
        (ROOT / relative).write_bytes(payload)
    print(json.dumps({"valid": True, "files": len(outputs), "updated": stale}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
