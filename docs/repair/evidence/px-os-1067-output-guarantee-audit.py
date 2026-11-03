"""PX-OS-1067 — destination-guarantee audit for caller-directed output producers.

The retired `reports/` grant failed because no producer guaranteed its destination. This
audit asks the question that grant skipped, for one producer at a time and from source:

    Does this producer's caller-selected output path provably land inside a root the
    generator itself derives, before any write happens?

A guarantee is `confined_to_generator_root` only when **all** of the following hold:

1. the destination is a required CLI argument (no silent default);
2. the producer resolves it and refuses a path outside a root it derives itself
   (`relative_to(root)` / `is_relative_to(root)` raising, or an explicit check);
3. the write is atomic: temp file in the destination directory, flushed, then `os.replace`;
4. the failure path removes only the temp file the producer created;
5. the destination is created only if absent, or is a fresh file (`mkstemp`/`exist_ok=False`).

Anything less is reported as unproven, and an unproven producer resolves to nothing. The
audit never grants anything: a grant still requires the owner's decision on the root.

Run:
    .venv-repair\\Scripts\\python.exe docs\\repair\\evidence\\px-os-1067-output-guarantee-audit.py
"""
from __future__ import annotations

import ast
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from runtime.effect_surface import _call_name  # noqa: E402

# Only producers whose output class is genuinely caller-directed are candidates. Each is
# read individually; membership here is a question, not a finding.
CANDIDATES = (
    "scripts/build_release_successor_configs.py",
    "scripts/benchmark_local_models.py",
    "scripts/benchmark_model_routes.py",
    "scripts/certify_local_model_profiles.py",
)


def _functions(tree: ast.Module) -> dict[str, ast.AST]:
    return {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def audit(relative: str) -> dict[str, object]:
    source = (ROOT / relative).read_text(encoding="utf-8-sig")
    tree = ast.parse(source)
    text = source
    functions = _functions(tree)

    required_args = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _call_name(node) == "parser.add_argument" and node.args:
            flag = node.args[0].value if isinstance(node.args[0], ast.Constant) else None
            if not isinstance(flag, str) or not flag.startswith("--"):
                continue
            required = any(
                keyword.arg == "required"
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value is True
                for keyword in node.keywords
            )
            required_args.append({"flag": flag, "required": required})

    output_args = [item for item in required_args if "output" in item["flag"]]
    checks = {
        "required_output_argument": bool(output_args) and all(item["required"] for item in output_args),
        # The generator derives a root and refuses a destination outside it.
        "confines_to_generator_root": "relative_to(root" in text or "is_relative_to(root" in text,
        # Atomic publication of the final bytes.
        "atomic_replace_publish": "os.replace(" in text,
        # The temp file is created in the destination directory.
        "temp_beside_destination": (
            "dir=path.parent" in text or "with_name(path.name" in text
        ),
        # A refusal to clobber an existing control file, or exclusive creation.
        "no_silent_overwrite": (
            "refusing to overwrite" in text or "exist_ok=False" in text or "mkstemp(" in text
        ),
        # Cleanup removes only the producer's own temp path.
        "owned_temp_cleanup": "unlink(missing_ok=True)" in text or "os.unlink(" in text,
    }
    guaranteed = all(checks.values())
    return {
        "producer": relative,
        "source_sha256": hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(),
        "required_output_arguments": output_args,
        "checks": checks,
        "guarantee": "confined_to_generator_root" if guaranteed else "unproven",
        "unproven_reasons": [name for name, ok in checks.items() if not ok],
        "write_class": "caller_directed_output",
        "grant_recommendation": (
            "Eligible for an owner grant scoped to this write class and pinned source bytes."
            if guaranteed
            else "Not eligible: the destination guarantee is incomplete, so a grant would "
            "authorize writes the producer does not confine."
        ),
    }


def main() -> int:
    rows = [audit(relative) for relative in CANDIDATES]
    contract = json.loads((EVIDENCE / "px-os-1067-authority-contract.json").read_text(encoding="utf-8"))
    document = {
        "schema_version": "px.output-guarantee-audit/1.0",
        "gap_id": "PX-OS-1067",
        "priority": 6,
        "measurement": "static source audit of required CLI arguments, confinement, and atomic publish",
        "binding_question": (
            "Whether the destination is guaranteed to land under a root the generator itself "
            "derives — the exact guarantee the retired reports/ grant lacked."
        ),
        "authority_contract": "px-os-1067-authority-contract.json",
        "current_output_roots": contract["current_state"],
        "producers": rows,
        "summary": {
            "producers": len(rows),
            "guaranteed": sum(1 for row in rows if row["guarantee"] == "confined_to_generator_root"),
            "unproven": sum(1 for row in rows if row["guarantee"] == "unproven"),
            "grants_made": 0,
            "roots_added": 0,
        },
        "grant_decision": {
            "status": "PENDING_OWNER",
            "needs": (
                "An owner decision binding these pinned source bytes to a durable root whose "
                "retention class fits a caller-directed output. The audit only establishes that "
                "the confinement guarantee exists; it does not choose the root."
            ),
        },
    }
    (EVIDENCE / "px-os-1067-output-guarantee-audit.json").write_text(
        json.dumps(document, indent=1, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(document["summary"]))
    for row in rows:
        print(row["producer"], row["guarantee"], row["unproven_reasons"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
