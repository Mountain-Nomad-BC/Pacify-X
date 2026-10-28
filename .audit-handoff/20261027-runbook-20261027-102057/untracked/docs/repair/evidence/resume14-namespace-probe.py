"""Causal probe: do tool-intake and lifecycle routing agree on one state authority?

Commissions a project in a temp dir, records tool intake through the real owner,
then asks the real lifecycle router where it thinks the state lives. If the
canonical control directory holds the state and the legacy one does not, a
hardcoded legacy path in the router would silently report the wrong stage.
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, ".")
from runtime.commissioning import commission  # noqa: E402
from runtime.engineering_lifecycle import lifecycle_status  # noqa: E402
from runtime.tool_intake import record_tool_intake  # noqa: E402

ROOT = Path(".").resolve()
tmp = Path(tempfile.mkdtemp())
project = tmp / "project"
commission(project, "new", apply=True, source_root=ROOT)
result = record_tool_intake(project, ROOT, apply=True)

legacy_state = project / ".engineering-bootstrap/project-management/state.json"
canonical_state = project / ".agentic_engineering_os_px/project-management/state.json"
print("tools admitted:", result["applied"], result["decision"])
print("legacy state exists:", legacy_state.is_file())
print("canonical state exists:", canonical_state.is_file())
print("recorded evidence:", json.loads(legacy_state.read_text(encoding="utf-8"))["evidence"].get("tool_intake_records") if legacy_state.is_file() else None)

status = lifecycle_status(ROOT, project)
checks = {check["stage"]: check["complete"] for check in status["checks"]}
print("tool-and-package-admission complete:", checks.get("tool-and-package-admission"))
print("next_stage:", status["next_stage"])
