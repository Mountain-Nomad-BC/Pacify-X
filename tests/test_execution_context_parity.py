"""JS producer / Python consumer execution-context round-trip parity.

The Agent Console produces the canonical execution context in Node; the Python
model bridge consumes it. This test proves the two implementations agree on the
exact field set, the bounded canonical digest, and fail-closed decoding of a
tampered context.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _node_executable() -> str:
    import shutil
    node = shutil.which("node")
    if node is None:
        from pathlib import Path as _P
        candidates = (
            _P("C:/Program Files/nodejs/node.exe"),
            _P.home() / "AppData/Local/Programs/nodejs/node.exe",
        )
        for candidate in candidates:
            if candidate.is_file():
                return str(candidate)
        return "node"
    return node

NODE = _node_executable()

_JS = (
    "const {createExecutionContext}=require("
    "'./extension/src/agentHarness/executionContext');"
    "const ctx=createExecutionContext({run:{runId:process.argv[1],revision:2,epoch:3},"
    "projectId:'project:demo',sessionId:process.argv[1],providerId:'llama.cpp',"
    "authoritySha256:process.argv[2],effectBudgetSha256:process.argv[3],"
    "deadlineMs:600000});"
    "console.log(JSON.stringify(ctx));"
)


def _node_context() -> dict:
    source = subprocess.run(
        [NODE, "-e", _JS, "run-parity", "a" * 64, "b" * 64],
        capture_output=True, text=True, timeout=30, cwd=ROOT,
    )
    assert source.returncode == 0, source.stderr
    return json.loads(source.stdout.strip().splitlines()[-1])


def test_js_produced_context_round_trips_through_the_canonical_python_owner() -> None:
    from runtime.execution_context import ExecutionContext, execution_context_from_dict

    raw = _node_context()
    decoded = execution_context_from_dict(raw)
    assert isinstance(decoded, ExecutionContext)
    assert decoded.execution_id == raw["execution_id"]
    assert decoded.root_execution_id == "run-parity"
    assert decoded.project_id == "project:demo"
    assert decoded.provider_id == "llama.cpp"
    assert decoded.revision == 2 and decoded.epoch == 3
    # The Python owner's canonical digest reproduces the Node digest exactly.
    assert decoded.context_sha256 == raw["context_sha256"]
    assert decoded.assert_current(
        project_id=decoded.project_id, session_id=decoded.session_id,
        epoch=decoded.epoch, generation_vector_sha256=None,
    ) is None


def test_tampered_js_context_fails_closed_in_python() -> None:
    from runtime.execution_context import execution_context_from_dict

    raw = _node_context()
    tampered = {**raw, "actor_id": "someone-else"}
    try:
        execution_context_from_dict(tampered)
    except Exception as error:
        assert "digest" in str(error).casefold() or "mismatch" in str(error).casefold()
    else:
        raise AssertionError("a tampered context was accepted by the Python owner")
