"""Closed, owned workflow executor adapters."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

from .studio_authority import StudioAuthorityStore


def _matches(value: object, data_type: str) -> bool:
    return {
        "json": True,
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
    }.get(data_type, False)


def _evaluate_validation(
    config: object,
    inputs: dict[str, object],
    outputs: dict[str, object],
) -> dict[str, object]:
    if not isinstance(config, dict) or set(config) != {"checks"} or not isinstance(
        config.get("checks"), list
    ) or not config["checks"]:
        raise ValueError("validation node has no admitted declarative checks")
    rows: list[dict[str, object]] = []
    for check in config["checks"]:
        if not isinstance(check, dict):
            raise ValueError("validation check contract is invalid")
        source_name = str(check.get("source", ""))
        namespace = inputs if source_name == "inputs" else outputs if source_name == "outputs" else None
        if namespace is None:
            raise ValueError("validation check source is invalid")
        port = str(check.get("port", ""))
        operator = str(check.get("operator", ""))
        present = port in namespace
        value = namespace.get(port)
        expected = check.get("expected")
        passed = False
        if operator == "exists":
            passed = present
        elif operator == "truthy":
            passed = present and bool(value)
        elif operator == "falsy":
            passed = present and not bool(value)
        elif operator == "equals":
            passed = present and value == expected
        elif operator == "not-equals":
            passed = present and value != expected
        elif operator == "type":
            passed = present and isinstance(expected, str) and _matches(value, expected)
        elif operator in {"greater-than-or-equal", "less-than-or-equal"}:
            numeric = (
                present
                and isinstance(value, (int, float))
                and not isinstance(value, bool)
                and isinstance(expected, (int, float))
                and not isinstance(expected, bool)
            )
            if numeric:
                passed = value >= expected if operator == "greater-than-or-equal" else value <= expected
        elif operator == "contains":
            if present and isinstance(value, (str, list, dict)):
                try:
                    passed = expected in value
                except TypeError:
                    passed = False
        else:
            raise ValueError("validation check operator is not admitted")
        rows.append(
            {
                "id": str(check.get("id", "")),
                "source": source_name,
                "port": port,
                "operator": operator,
                "passed": passed,
            }
        )
    failed = [str(row["id"]) for row in rows if not row["passed"]]
    if failed:
        raise ValueError("workflow validation failed: " + ", ".join(failed))
    return {"passed": True, "check_count": len(rows), "checks": rows}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--task", type=Path, required=True)
    args = parser.parse_args()
    authority = StudioAuthorityStore(args.project_root)
    task = authority.verify_receipt(json.loads(args.task.read_text(encoding="utf-8")))
    if task.get("schema_version") != "px.workflow-node-task/1.0" or not isinstance(
        task.get("inputs"), dict
    ):
        raise ValueError("workflow node task contract is invalid")
    adapter = task.get("adapter_id")
    binding_id = str(task.get("executor_binding_id", ""))
    executor, executor_sha256 = authority.resolve_executor(binding_id)
    if (
        executor.get("adapter_id") != adapter
        or task.get("authority_record_hashes", {}).get(f"executor:{binding_id}")
        != executor_sha256
    ):
        raise PermissionError("workflow task executor admission changed")
    binding, binding_sha256 = authority.resolve_binding(
        binding_id,
        subject_kind="workflow",
        subject_id=str(task.get("workflow_id", "")),
    )
    authority_hashes = task.get("authority_record_hashes")
    if not isinstance(authority_hashes, dict) or authority_hashes.get(
        f"binding:{binding_id}"
    ) != binding_sha256:
        raise PermissionError("workflow task binding admission changed")
    grant_ids = tuple(map(str, task.get("effect_grant_ids", ())))
    if set(grant_ids) != set(map(str, binding.get("effect_grant_ids", ()))):
        raise PermissionError("workflow task grant binding changed")
    for grant_id in grant_ids:
        _, grant_sha256 = authority.resolve_grant(
            grant_id, subject_id=str(task.get("workflow_id", ""))
        )
        if authority_hashes.get(f"grant:{grant_id}") != grant_sha256:
            raise PermissionError("workflow task grant admission changed")
    inputs = dict(task["inputs"])
    print(
        json.dumps(
            {
                "schema_version": "px.workflow-node-liveness/1.0",
                "status": "started",
                "node_id": task["node_id"],
                "attempt": task["attempt"],
            },
            sort_keys=True,
        ),
        flush=True,
    )
    if adapter == "identity":
        outputs = inputs
    elif adapter == "increment":
        outputs = {"value": inputs["value"] + 1}
    elif adapter == "double":
        outputs = {"result": inputs["value"] * 2}
    elif adapter == "fail":
        raise RuntimeError("admitted failure adapter requested")
    elif adapter == "sleep":
        time.sleep(float(inputs["seconds"]))
        outputs = {"seconds": inputs["seconds"]}
    else:
        raise ValueError("workflow executor adapter is not admitted")
    node_kind = str(task.get("node_kind", "task"))
    if node_kind not in {"task", "validation", "approval", "branch", "join"}:
        raise ValueError("workflow node kind is not admitted")
    if node_kind != "validation" and task.get("node_config") != {}:
        raise ValueError("workflow node config is not admitted for this node kind")
    validation = (
        _evaluate_validation(task.get("node_config"), inputs, outputs)
        if node_kind == "validation"
        else {"passed": True, "check_count": 0, "checks": []}
    )
    approval_execution = task.get("approval_execution")
    if node_kind == "approval" or task.get("approval_required") is True:
        if not isinstance(approval_execution, dict) or approval_execution.get(
            "host_consumed"
        ) is not True:
            raise PermissionError("workflow approval was not consumed by the host boundary")
    print(
        json.dumps(
            {
                "schema_version": "px.workflow-node-result/1.0",
                "status": "completed",
                "outputs": outputs,
                "node_kind": node_kind,
                "adapter_id": adapter,
                "adapter_admitted": True,
                "validation": validation,
                "approval_execution": approval_execution,
                "declared_effect_grants": task["effect_grant_ids"],
                "attempted_effects": [],
                "completed_effects": [],
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
