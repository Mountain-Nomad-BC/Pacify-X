"""Adapt an exact installed-VSIX smoke into narrowly scoped control-stage evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

try:
    from scripts.assemble_operational_control_evidence import MATRIX, STAGES, current_source_manifest
except ModuleNotFoundError:  # Direct `python scripts/...` execution.
    from assemble_operational_control_evidence import MATRIX, STAGES, current_source_manifest


STUDIO_RUNTIME_STAGES = {
    "authorization",
    "backend_dispatch",
    "runtime_effect",
    "result_acknowledgement",
    "persistence",
    "reload_reopen",
}
STUDIO_LIFECYCLE_STAGES = STUDIO_RUNTIME_STAGES | {"progress_reporting"}
SIDEBAR_STAGES = {
    "open_load",
    "display",
    "authorization",
    "backend_dispatch",
    "runtime_effect",
    "result_acknowledgement",
}


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("installed-host receipt must be an object")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _stages(
    requirement: dict[str, Any], present: set[str], claim: str
) -> dict[str, dict[str, Any]]:
    result = {}
    for stage in STAGES:
        policy = requirement["stage_policy"][stage]
        if policy == "not_applicable_with_evidence":
            result[stage] = {
                "state": "not_applicable",
                "detail": "Canonical proof matrix marks this stage not applicable.",
                "evidence": ["proof-matrix"],
            }
        elif stage in present:
            result[stage] = {
                "state": "present",
                "detail": claim,
                "evidence": ["exact-installed-host-smoke"],
            }
        else:
            result[stage] = {
                "state": "missing",
                "detail": f"The installed-host smoke did not directly prove required stage {stage} for this exact control.",
                "evidence": [],
            }
    return result


def build(root: Path, receipt_path: Path, vsix_path: Path) -> dict[str, Any]:
    root = root.resolve(strict=True)
    receipt_path = receipt_path.resolve(strict=True)
    vsix_path = vsix_path.resolve(strict=True)
    receipt = _load(receipt_path)
    if receipt.get("schema_version") != "px.installed-vsix-certification/1.1":
        raise ValueError("installed-host receipt schema is invalid")
    artifact = receipt.get("artifact", {})
    digest = _sha256(vsix_path)
    if (
        not artifact.get("unchanged")
        or artifact.get("sha256_before") != digest
        or artifact.get("sha256_after") != digest
    ):
        raise ValueError(
            "installed-host receipt is not bound to the exact retained VSIX"
        )
    matrix = _load(root / MATRIX)
    source_manifest = current_source_manifest(root, matrix)
    identity_path = root / "registry" / "engine_identity.json"
    identity = _load(identity_path)
    receipt_identity = receipt.get("engine_identity")
    identity_records = {
        str(item.get("path")): item
        for item in identity.get("records", [])
        if isinstance(item, dict)
    }
    control_sources_current = all(
        isinstance(identity_records.get(item["path"]), dict)
        and identity_records[item["path"]].get("sha256") == item["sha256"]
        and identity_records[item["path"]].get("bytes") == item["bytes"]
        for item in source_manifest["files"]
    )
    if (
        not isinstance(receipt_identity, dict)
        or receipt_identity.get("manifest_sha256") != _sha256(identity_path)
        or receipt_identity.get("tree_sha256") != identity.get("tree_sha256")
        or receipt_identity.get("file_total") != identity.get("file_total")
        or not control_sources_current
    ):
        raise ValueError("installed-host receipt engine identity is absent or stale")
    lifecycle = receipt.get("process_lifecycle", {})
    if not all(
        (
            receipt.get("engine_connected"),
            lifecycle.get("worker_exit_verified"),
            lifecycle.get("process_tree_closed_verified"),
            lifecycle.get("exit_code") == 0,
        )
    ):
        raise ValueError("installed host or owned process lifecycle is incomplete")
    host = receipt.get("host", {})
    studio = host.get("exact_studio_round_trips", {})
    sidebar = host.get("live_sidebar", {}).get("provider", {})
    if not studio.get("setup_ready"):
        raise ValueError("installed host lacks exact Studio readiness")
    requirements = {item["control_id"]: item for item in matrix["controls"]}
    specs: list[tuple[str, set[str], str, bool]] = []
    for surface, kind in (
        ("agent-studio", "agent"),
        ("agents", "agent"),
        ("workflow-studio", "workflow"),
        ("workflows", "workflow"),
    ):
        details = studio.get(kind, {})
        if details.get("admission") != "admitted" or not details.get(
            "reopen_authenticated"
        ):
            raise ValueError(
                f"installed host lacks exact {kind} admission/reopen evidence"
            )
        for semantic in ("persistence", "reload_reopen"):
            specs.append(
                (
                    f"pxui.{surface}.{semantic}.authoritativeState",
                    STUDIO_RUNTIME_STAGES,
                    f"Exact installed {kind} round trip admitted, executed, persisted, and authenticated its reopen.",
                    False,
                )
            )
    agent = studio.get("agent", {})
    workflow = studio.get("workflow", {})
    if (
        agent.get("run_outcome") != "succeeded"
        or workflow.get("run_state") != "succeeded"
    ):
        raise ValueError("installed Studio run outcomes are incomplete")
    specs.extend(
        (
            (
                "pxui.studio-lifecycle.lifecycle.path.1",
                STUDIO_LIFECYCLE_STAGES,
                "Exact installed Agent lifecycle reached admitted run success and authenticated reopen.",
                False,
            ),
            (
                "pxui.studio-lifecycle.lifecycle.path.2",
                STUDIO_LIFECYCLE_STAGES,
                "Exact installed Workflow lifecycle reached admitted run success and authenticated reopen.",
                False,
            ),
        )
    )
    skill = studio.get("skill", {})
    if skill.get("save_status") == "created" and skill.get("content_bound") is True:
        specs.append(
            (
                "pxui.skill-studio.persistence.authoritativeState",
                STUDIO_RUNTIME_STAGES - {"reload_reopen"},
                "Exact installed Skill Studio save created a content-bound project-studio package.",
                False,
            )
        )
    if not all(
        (
            sidebar.get("resolved"),
            sidebar.get("visible"),
            sidebar.get("html_assigned"),
            sidebar.get("ready_count", 0) > 0,
            sidebar.get("render_ack_count", 0) > 0,
            sidebar.get("contract_rejection_count") == 0,
            sidebar.get("operation_error_count") == 0,
        )
    ):
        raise ValueError("installed sidebar acknowledgement chain is incomplete")
    specs.append(
        (
            "pxui.sidebar.acknowledgement.surface",
            SIDEBAR_STAGES,
            "Exact installed contributed sidebar resolved visibly and returned its typed rendered acknowledgement without contract or operation errors.",
            True,
        )
    )
    records = []
    for control_id, present, claim, rendered in specs:
        requirement = requirements.get(control_id)
        if requirement is None:
            raise ValueError(
                f"installed-host adapter references an unknown control: {control_id}"
            )
        records.append(
            {
                "control_id": control_id,
                "attempted": True,
                "rendered": rendered,
                "observed": True,
                "stages": _stages(requirement, present, claim),
            }
        )
    return {
        "schema_version": "px.operational-control-stage-evidence/1.0",
        "evidence_kind": "direct_installed_host_measurement",
        "authority": "Exact checksum-bound installed VSIX in an isolated VS Code host; only enumerated observed stages are claimed.",
        "source": {
            "receipt": receipt_path.relative_to(root).as_posix(),
            "receipt_sha256": _sha256(receipt_path),
            "vsix": vsix_path.relative_to(root).as_posix(),
            "vsix_sha256": digest,
            "control_source_manifest": source_manifest,
        },
        "records": sorted(records, key=lambda item: item["control_id"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--vsix", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    def resolve(value: Path) -> Path:
        if value.is_absolute():
            return value.resolve(strict=True)
        return (root / value).resolve(strict=True)

    result = build(root, resolve(args.receipt), resolve(args.vsix))
    output = (
        (root / args.output).resolve()
        if not args.output.is_absolute()
        else args.output.resolve()
    )
    output.relative_to(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    print(
        json.dumps(
            {"output": str(output), "record_count": len(result["records"])}, indent=2
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
