"""Do the external and canonical owners agree on WHERE experience lives?

Write through the external recorder, then read through the external fuse, then
read the same tree through the canonical fuse. A store mismatch is fatal to a
drop-in port regardless of how good the external code is.
"""
import importlib.util
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, ".")
from runtime import usage_memory as canonical  # noqa: E402

EXTERNAL = Path(r"C:\Users\Ben\Videos\Pacify-X-main\runtime\usage_memory.py")
spec = importlib.util.spec_from_file_location("runtime.usage_memory_ext", EXTERNAL)
ext = importlib.util.module_from_spec(spec)
ext.__package__ = "runtime"
spec.loader.exec_module(ext)

root = Path(tempfile.mkdtemp())
(root / "orchestration" / "workflows" / "wf_probe" / "memory").mkdir(parents=True)
ext.record_observation(root, "workflow", "wf_probe", {
    "outcome": "success", "disposition": "NO_PRODUCT_DEFECT", "run_id": "run-0",
    "correlation_id": "effect-0", "duration_ms": 100, "tokens": 10,
    "success_criteria_met": True, "gap": None,
})

binding = {"kind": "workflow", "identity": "wf_probe", "version": "1.0.0"}
print("--- external fuse reading its own recorder's output ---")
sub = ext.fuse_tie_experience(root, (binding,))["subjects"][0]
print("   state:", sub["state"], "| failure:", sub.get("failure_type"))

print("--- canonical fuse reading the same tree ---")
sub2 = canonical.fuse_tie_experience(root, (binding,))["subjects"][0]
print("   state:", sub2["state"], "| lineage:", sub2["lineage_status"], "| records:", sub2["returned_record_count"])

print("\n--- where each owner reads/writes ---")
print("   canonical _memory_dir:", canonical._memory_dir(root, "workflow", "wf_probe").relative_to(root).as_posix())
try:
    print("   external _studio_memory:", ext._studio_memory(root, "workflow", "wf_probe", "1.0.0").relative_to(root).as_posix())
except Exception as error:  # noqa: BLE001
    print("   external _studio_memory:", type(error).__name__, str(error)[:100])
print("   files present:", sorted(p.relative_to(root).as_posix() for p in root.rglob("*.json*")) or "none")
