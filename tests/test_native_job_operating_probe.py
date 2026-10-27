"""Required native operating gate; workload custody belongs to the process owner."""
import hashlib
import json
from pathlib import Path
import sys

import pytest
from scripts import probe_native_job_containment as probe

ROOT = Path(__file__).resolve().parents[1]


def assert_complete_proof(proof):
    assert type(proof) is dict, "operating proof object required"
    assert proof.get("schema_version") == "px.native-job-operating-proof/1.0", "operating proof schema required"
    assert proof.get("passed") is True, "operating proof failed"
    assert proof.get("certification") is False, "operating proof is not certification"
    assert proof.get("supervisor_thread_closed") is True, "supervisor thread not closed"
    assert not any(proof.get(key) for key in ("error", "process_error", "cleanup_error")), "operating errors retained"
    observed = proof.get("observations", {})
    pids = observed.get("kernel_pids", [])
    assert type(pids) is list and len(pids) == 68 and len(set(pids)) == 68, "68 distinct kernel Job members required"
    assert all(type(pid) is int and pid > 0 for pid in pids), "invalid kernel PID"
    assert observed.get("child_count") == observed.get("stable_heartbeat_count") == 67, "67 operating children required"
    assert type(observed.get("post_suspend_io_settled")) is bool, "settling observation required"
    freeze = observed.get("freeze", {})
    assert freeze.get("frozen") is True and freeze.get("failed_pids") == [], "complete freeze required"
    for key in ("pids", "expected_pids", "observed_pids"):
        assert sorted(freeze.get(key, [])) == sorted(pids), "freeze membership differs"
    assert observed.get("outside_job_rejection", {}).get("frozen") is False, "outside-Job denial required"
    termination = observed.get("termination", {})
    assert termination.get("terminated") is True and termination.get("remaining_pids") == [], "kernel-empty termination required"
    result = proof.get("process_result", {})
    settled = observed.get("settled_resource", {})
    assert result.get("tree_closed") is True, "supervisor tree closure required"
    assert settled.get("active") is False and settled.get("resource_id") == result.get("resource_id"), "exact settled custody required"
    custody = observed.get("root_custody", {})
    child = observed.get("child_membership", {})
    assert custody.get("parent_resource_id") == child.get("parent_resource_id") == result.get("resource_id"), "membership owner differs"
    assert custody.get("job_object_id") == child.get("job_object_id") and custody.get("job_object_id"), "Job custody differs"
    assert custody.get("member_pid") in pids and child.get("member_pid") in pids, "membership absent from kernel Job"
    assert custody["member_pid"] != child["member_pid"], "distinct child membership required"
    hashes = proof.get("source_sha256", {})
    assert set(hashes) == {"runtime/process_supervisor.py", "runtime/resource_lifecycle.py",
        "runtime/gremlin/host_enforcement_backend.py", "scripts/probe_native_job_containment.py"}, "exact source denominator required"
    for relative, expected in hashes.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected, "operating source changed"
    workspace = Path(proof["workspace"]).resolve(strict=True)
    workspace.relative_to((ROOT / ".tmp/owned-host-probes").resolve(strict=True))
    evidence = Path(proof["evidence_path"])
    assert evidence == workspace / "operating-proof.json", "proof escaped retained workspace"
    assert json.loads(evidence.read_text(encoding="utf-8")) == proof, "retained proof differs"


def test_native_job_containment_operating_probe():
    if sys.platform != "win32":
        pytest.fail("Required Windows Job operating proof is unavailable on this host", pytrace=False)
    # The governed pytest process already has process custody. Invoke the owner
    # directly rather than launching an unregistered intermediate subprocess.
    assert_complete_proof(probe.run_probe())
