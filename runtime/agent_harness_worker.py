"""Owned local worker adapter for authenticated Studio task envelopes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

from .studio_authority import StudioAuthorityStore
from .studio_models import digest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--task", type=Path, required=True)
    args = parser.parse_args()
    authority = StudioAuthorityStore(args.project_root)
    task = args.task.resolve(strict=True)
    payload = json.loads(task.read_text(encoding="utf-8"))
    payload = authority.verify_receipt(payload)
    required = {
        "schema_version",
        "agent_id",
        "agent_revision_sha256",
        "task_sha256",
        "task",
        "harness_id",
        "binding_ids",
        "effect_grant_ids",
        "authority_record_hashes",
        "created_utc",
        "nonce",
    }
    if (
        set(payload) != required
        or payload["schema_version"] != "px.agent-harness-task/1.2"
    ):
        raise ValueError("agent harness task contract is invalid")
    if (
        not isinstance(payload["task"], dict)
        or digest(payload["task"]) != payload["task_sha256"]
    ):
        raise ValueError("agent task body does not match its content identity")
    if payload["harness_id"] != "harness:px":
        raise ValueError("agent harness adapter is not admitted")
    objective_present = "objective" in payload["task"]
    if objective_present:
        objective = str(payload["task"].get("objective")).strip()
        if not objective:
            raise ValueError("agent task requires a bounded objective when provided")
    else:
        objective = ""
    capabilities = set()
    for binding_id in payload["binding_ids"]:
        binding, _ = authority.resolve_binding(
            str(binding_id),
            subject_kind="agent",
            subject_id=str(payload["agent_id"]),
        )
        capabilities.add(str(binding["capability_id"]))
    tool_calls = payload["task"].get("tool_calls", [])
    if not isinstance(tool_calls, list) or len(tool_calls) > 8:
        raise ValueError("agent task tool calls exceed the closed bound")
    if tool_calls and "capability:local-worker" not in capabilities:
        raise PermissionError("agent task lacks the admitted local-worker capability")
    tool_receipts = []
    for index, call in enumerate(tool_calls):
        if not isinstance(call, dict) or set(call) != {"tool", "input"}:
            raise ValueError("agent tool call contract is invalid")
        tool = str(call["tool"])
        # Keep the owned-process idle watchdog informed without exposing tool
        # inputs or results. The controller consumes only the final JSON line.
        print(
            json.dumps(
                {
                    "schema_version": "px.agent-harness-progress/1.0",
                    "status": "running",
                    "tool_index": index,
                    "tool": tool,
                },
                sort_keys=True,
            ),
            flush=True,
        )
        if tool == "sha256":
            result = {"input_sha256": digest(call["input"])}
        elif tool == "json-keys" and isinstance(call["input"], dict):
            result = {"keys": sorted(str(key) for key in call["input"])}
        elif (
            tool == "delay"
            and isinstance(call["input"], (int, float))
            and not isinstance(call["input"], bool)
            and 0 <= float(call["input"]) <= 1.5
        ):
            # A bounded local delay is useful for exercising real lifecycle
            # cancellation.  It cannot access data, network, or host authority.
            time.sleep(float(call["input"]))
            result = {"delayed_seconds": float(call["input"])}
        else:
            raise ValueError("agent tool is not in the closed local registry")
        tool_receipts.append(
            {
                "index": index,
                "tool": tool,
                "input_sha256": digest(call["input"]),
                "result": result,
            }
        )
    # This local adapter is intentionally deterministic and non-billable.  It is a
    # real worker boundary, not a claim that an external language model ran.
    print(
        json.dumps(
            {
                "schema_version": "px.agent-harness-result/1.1",
                "status": "completed",
                "execution_mode": "deterministic-local-worker",
                "adapter": "px-local-worker-v1",
                "task_sha256": payload["task_sha256"],
                "result": {
                    "objective_received": objective_present,
                    "objective_sha256": digest(objective),
                },
                "worker_invoked": True,
                "model_invoked": False,
                "tools_dispatched": tool_receipts,
                "content_retained": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
