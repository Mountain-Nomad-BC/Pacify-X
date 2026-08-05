#!/usr/bin/env python3
"""Run a declared domain helper through the fail-closed shared runtime."""

import argparse
import json
from pathlib import Path
import sys

try:
    from engineering_bootstrap.declared_suite import run_script_outcome
    from engineering_bootstrap.paths import framework_root
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
    from runtime.declared_suite import run_script_outcome
    from runtime.paths import framework_root

p = argparse.ArgumentParser()
p.add_argument("outcome")
p.add_argument("--input", type=Path, required=True)
a = p.parse_args()
payload = json.loads(a.input.read_text(encoding="utf-8"))
result = run_script_outcome(framework_root(), a.outcome, payload)
print(json.dumps(result, indent=2))
raise SystemExit(0 if result.get("valid") else 1)
