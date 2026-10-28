"""End-to-end: record real experience through the native owner, then fuse it."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, ".")
from runtime import usage_memory as um  # noqa: E402

root = Path(tempfile.mkdtemp())
(root / "orchestration" / "workflows").mkdir(parents=True)

for index in range(3):
    um.record_observation(
        root,
        "workflow", "wf_probe",
        {
            "outcome": "success" if index else "partial",
            "disposition": "NO_PRODUCT_DEFECT",
            "run_id": f"run-{index}",
            "correlation_id": f"effect-{index}",
            "duration_ms": 100 + index,
            "tokens": 10 * index,
            "success_criteria_met": True,
            "gap": None if index else "first attempt missed a boundary",
        },
    )

binding = {"kind": "workflow", "identity": "wf_probe", "version": "1.0.0"}
fused = um.fuse_tie_experience(root, (binding,))
first = fused["subjects"][0]
second = um.fuse_tie_experience(root, (binding,))

print("state:", first["state"])
print("lineage:", first["lineage_status"])
print("records returned:", first["returned_record_count"], "of", first["record_count"])
print("authority_granted:", fused["authority_granted"], "| propagated:", fused["propagated"])
print("digest deterministic:", fused["fusion_sha256"] == second["fusion_sha256"])
print("run ids retained:", all(row.get("run_id") for row in first["records"]))
print("read-only, one log only:", len(list(root.rglob("usage.jsonl"))) == 1)
