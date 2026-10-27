"""Retained Windows operational reproduction; never a certification substitute."""
from __future__ import annotations

import dataclasses
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from runtime.process_supervisor import ProcessSupervisor
from runtime.resource_lifecycle import ResourceManager
from runtime.gremlin.host_enforcement_backend import ProcessSupervisorEnforcementBackend


def run_probe() -> dict:
    if os.name != "nt":
        raise OSError("This probe requires a real Windows host")
    owned = ROOT / ".tmp/owned-host-probes"
    owned.mkdir(parents=True, exist_ok=True)
    manager = ResourceManager(owned / "resources.json")
    record = manager.create_workspace(owned, project_id="native-job-probe", run_id="native-job",
        lane_id="operating-proof", creator="codex", retention_required=True)
    workspace = Path(record.path)
    child = workspace / "heartbeat.py"
    child.write_text("import pathlib,sys,time\np=pathlib.Path(sys.argv[1])\ni=0\n"
        "while True:\n i+=1\n p.write_text(str(i))\n time.sleep(.03)\n", encoding="utf-8")
    workload = workspace / "workload.py"
    workload.write_text("import json,os,pathlib,subprocess,sys,time\n"
        "root=pathlib.Path.cwd()\n"
        "children=[subprocess.Popen([sys.executable,str(root/'heartbeat.py'),str(root/f'beat-{i}.txt')]) for i in range(67)]\n"
        "(root/'ready.json').write_text(json.dumps([os.getpid()]+[p.pid for p in children]))\n"
        "print('ready',flush=True)\n"
        "while True: time.sleep(.1)\n", encoding="utf-8")
    budget = dict(startup_timeout_seconds=45, idle_timeout_seconds=120,
        total_timeout_seconds=150, graceful_shutdown_seconds=1,
        force_shutdown_seconds=10, stdout_limit_bytes=4096, stderr_limit_bytes=4096)
    action = dict(action_id="native-job-proof", effects=["process"],
        allowed_effects=["process"], target_paths=[str(workspace)], owned_paths=[str(workspace)],
        budget=budget, limits=budget, approval=True, policy_override_requested=False)
    supervisor = ProcessSupervisor(manager)
    result = {}
    cancel = threading.Event()

    def run():
        try:
            value = supervisor.run([sys._base_executable, str(workload)], cwd=workspace,
                action=action, project_id="native-job-probe", run_id="native-job", lane_id="operating-proof",
                creator="codex", cancel_event=cancel)
            result["process_result"] = dataclasses.asdict(value)
        except BaseException:
            result["process_error"] = traceback.format_exc()

    thread = threading.Thread(target=run, name="owned-native-probe")
    thread.start()
    job = None
    proof = {"schema_version":"px.native-job-operating-proof/1.0", "workspace":str(workspace),
        "certification":False, "passed":False, "observations":{}, "source_sha256":{
            path:hashlib.sha256((ROOT/path).read_bytes()).hexdigest() for path in (
                "runtime/process_supervisor.py", "runtime/resource_lifecycle.py",
                "runtime/gremlin/host_enforcement_backend.py", "scripts/probe_native_job_containment.py")}}
    try:
        deadline = time.monotonic()+65
        while time.monotonic()<deadline:
            if (workspace/"ready.json").exists() and len(list(workspace.glob("beat-*.txt")))==67:
                break
            if not thread.is_alive():
                raise RuntimeError("supervisor exited before workload readiness: "+str(result))
            time.sleep(.05)
        expected = set(json.loads((workspace/"ready.json").read_text()))
        if len(expected)!=68:
            raise AssertionError("workload must create 68 distinct processes")
        entries = list(manager._process_jobs.items())
        if len(entries)!=1:
            raise AssertionError("expected one retained native Job")
        resource_id, job = entries[0]
        backend = ProcessSupervisorEnforcementBackend(supervisor_lookup=lambda key: job if key==job.custody_id else None)
        actual = set(backend._job_process_pids(job.handle))
        if actual!=expected:
            raise AssertionError(f"kernel membership mismatch {actual ^ expected}")
        root_pid = manager._processes[resource_id].pid
        custody = manager.verify_owned_job(resource_id)
        child_pid = next(pid for pid in expected if pid!=root_pid)
        member = manager.verify_job_member(resource_id, child_pid)
        rejected = backend.freeze({"job_object_id":job.custody_id,"pid":os.getpid()})
        if rejected.get("frozen") is not False:
            raise AssertionError("outside-Job controller PID was accepted")
        beats = sorted(workspace.glob("beat-*.txt"))
        def image():
            return {p.name:p.read_bytes() for p in beats}
        first = image()
        time.sleep(.2)
        if not all(first[p.name]!=p.read_bytes() for p in beats):
            raise AssertionError("not all 67 heartbeat processes are operating")
        frozen = backend.freeze({"job_object_id":job.custody_id,"pid":root_pid})
        if frozen.get("frozen") is not True:
            raise AssertionError("native freeze not confirmed: "+str(frozen))
        proof["observations"]["freeze"] = frozen
        # Suspend completion does not drain already-issued kernel file I/O.
        # Observe a bounded settling interval, then require two stable windows.
        immediate = image()
        time.sleep(.2)
        first = image()
        proof["observations"]["post_suspend_io_settled"] = immediate != first
        time.sleep(.3)
        if first!=image():
            raise AssertionError("heartbeat advanced after confirmed freeze")
        time.sleep(.5)
        if first != image():
            raise AssertionError("heartbeat advanced in second frozen observation window")
        terminated = backend.terminate_tree({"job_object_id":job.custody_id,"pid":root_pid})
        if terminated.get("terminated") is not True:
            raise AssertionError("Job termination not confirmed: "+str(terminated))
        thread.join(20)
        if thread.is_alive() or result.get("process_error") or result.get("process_result",{}).get("tree_closed") is not True:
            raise AssertionError("native supervisor failed closure: "+str(result))
        settled = manager.ledger.get(resource_id)
        if settled.active or resource_id in manager._process_jobs or resource_id in manager._processes:
            raise AssertionError("native resource custody remains active")
        proof["observations"].update(kernel_pids=sorted(actual), child_count=67,
            root_custody=dataclasses.asdict(custody), child_membership=dataclasses.asdict(member),
            outside_job_rejection=rejected, freeze=frozen, stable_heartbeat_count=67,
            termination=terminated, settled_resource=dataclasses.asdict(settled))
        proof["passed"] = True
    except BaseException:
        proof["error"] = traceback.format_exc()
    finally:
        cancel.set()
        if job is not None and job.handle:
            try:
                job.terminate(137)
            except BaseException:
                proof["cleanup_error"] = traceback.format_exc()
                proof["passed"] = False
        thread.join(25)
        proof["supervisor_thread_closed"] = not thread.is_alive()
        proof.update(result)
        if thread.is_alive():
            proof["passed"] = False
        destination = workspace / "operating-proof.json"
        proof["evidence_path"] = str(destination)
        with destination.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(proof, stream, indent=2, default=str)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    return proof


def main() -> int:
    proof = run_probe()
    print(json.dumps({"passed":proof["passed"],"evidence":proof["evidence_path"],
                      "workspace":proof["workspace"]}))
    return 0 if proof["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
