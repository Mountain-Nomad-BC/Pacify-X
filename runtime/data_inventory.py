"""Data inventory, classification and retention support (punch cards ASSURE-001..005, W7).

Erasure cannot be proven against a store nobody enumerated. This owner builds a
*bounded, honest inventory* of the real data stores Pacify-X creates, classifies
each one, and records its retention/legal-hold posture. It performs no deletion:
it is the map a human-approved erasure or retention operation must consult, and
the evidence that an erasure actually covered every reconstructable copy.

It deliberately does NOT decide law. ``retention_policy`` and ``lawful_basis`` are
supplied by a human owner; this owner records and enforces the *mechanics* of
whatever policy is declared, and refuses to invent one.

Data stores are discovered from their canonical owners, not hard-coded paths:
memory vaults/snapshots, task snapshots, T.I.E. experience logs, indexes, caches,
transcripts, exports, backups and telemetry.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping
import hashlib

from .archive_io import portable_member_name, reject_path_links
from .json_io import bounded_canonical_json_bytes

SCHEMA_VERSION = "px.data-inventory/1.1"

#: Data classes. ``personal`` and ``sensitive`` are the classes an erasure request
#: must cover; ``operational`` and ``evidence`` carry retention/legal-hold
#: obligations and must NOT be destroyed by a routine erasure.
DATA_CLASSES = ("personal", "sensitive", "operational", "evidence", "derived", "public")

#: Store families the inventory must consider. A family with no live store is
#: reported ``absent`` rather than omitted, so a missing store is visible.
STORE_FAMILIES = (
    "memory_vault",
    "task_snapshot",
    "tie_experience",
    "index",
    "cache",
    "transcript",
    "export",
    "backup",
    "telemetry",
)


class DataInventoryError(ValueError):
    """Raised when an inventory or retention request is invalid."""


@dataclass(frozen=True, slots=True)
class DataStore:
    store_id: str
    family: str
    owner: str
    relative_root: str
    data_class: str
    retention_days: int | None
    legal_hold: bool
    erasable: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "store_id": self.store_id,
            "family": self.family,
            "owner": self.owner,
            "relative_root": self.relative_root,
            "data_class": self.data_class,
            "retention_days": self.retention_days,
            "legal_hold": self.legal_hold,
            "erasable": self.erasable,
            "authority_granted": False,
        }


#: The declared, real store families and their canonical owners. Paths are the
#: roots the corresponding owner actually writes to. Adding a store is a reviewed
#: edit, not a runtime guess.
DECLARED_STORES: tuple[dict[str, object], ...] = (
    {"store_id": "remote-provider-configuration", "family": "task_snapshot", "owner": "runtime.remote_provider_profiles",
     "relative_root": ".agentic_engineering_os_px/runtime-core/remote-models",
     "data_class": "evidence", "erasable": False},
    {"store_id": "remote-provider-operation-events", "family": "transcript", "owner": "runtime.operational_event_bus",
     "relative_root": ".agentic_engineering_os_px/runtime-core/remote-models/gateway/events",
     "data_class": "evidence", "erasable": False},
    {"store_id": "remote-provider-budget-ledger", "family": "telemetry", "owner": "runtime.provider_budget",
     "relative_root": ".agentic_engineering_os_px/runtime-core/remote-models/gateway/budget",
     "data_class": "evidence", "erasable": False},
    {"store_id": "canonical-personal-records", "family": "memory_vault", "owner": "runtime.personal_record_store",
     "relative_root": ".agentic_engineering_os_px/runtime-core/data-controls/personal-records.json",
     "data_class": "personal", "erasable": True},
    {"store_id": "personal-control-namespace", "family": "transcript", "owner": "runtime.personal_record_store",
     "relative_root": ".agentic_engineering_os_px/runtime-core/data-controls",
     "data_class": "evidence", "erasable": False},
    {"store_id": "foundry-retained-candidates", "family": "backup", "owner": "runtime.knowledge_foundry",
     "relative_root": ".agentic_engineering_os_px/runtime-core/knowledge-foundry/candidates",
     "data_class": "evidence", "erasable": False},
    {"store_id": "foundry-resource-custody", "family": "telemetry", "owner": "runtime.resource_lifecycle",
     "relative_root": ".agentic_engineering_os_px/runtime-core/knowledge-foundry/resources.json",
     "data_class": "evidence", "erasable": False},
    {"store_id": "tie-skill", "family": "tie_experience", "owner": "runtime.usage_memory",
     "relative_root": ".px/skills", "data_class": "operational", "erasable": False},
    {"store_id": "tie-agent", "family": "tie_experience", "owner": "runtime.usage_memory",
     "relative_root": "providers/agency_agents/agents", "data_class": "operational", "erasable": False},
    {"store_id": "tie-workflow", "family": "tie_experience", "owner": "runtime.usage_memory",
     "relative_root": "orchestration/workflows", "data_class": "operational", "erasable": False},
    {"store_id": "tie-migration-receipts", "family": "transcript", "owner": "runtime.tie_experience",
     "relative_root": ".agentic_engineering_os_px/runtime-core/tie-migrations/receipts",
     "data_class": "evidence", "erasable": False},
    {"store_id": "studio-revisions", "family": "index", "owner": "runtime.studio_models",
     "relative_root": ".agentic_engineering_os_px/studios", "data_class": "operational", "erasable": False},
    {"store_id": "agent-task-snapshots", "family": "task_snapshot", "owner": "runtime.agent_runtime",
     "relative_root": ".agentic_engineering_os_px/runtime-core/agent-console", "data_class": "operational",
     "erasable": False},
    {"store_id": "effect-intents", "family": "transcript", "owner": "runtime.effect_intent",
     "relative_root": ".agentic_engineering_os_px/runtime-core/effect-intents.json",
     "data_class": "evidence", "erasable": False},
    {"store_id": "mutation-queue", "family": "transcript", "owner": "runtime.mutation_queue",
     "relative_root": ".agentic_engineering_os_px/runtime-core/mutation-queue.json",
     "data_class": "evidence", "erasable": False},
    {"store_id": "scope-leases", "family": "transcript", "owner": "runtime.scope_lease",
     "relative_root": ".agentic_engineering_os_px/runtime-core/scope-leases.json",
     "data_class": "evidence", "erasable": False},
    {"store_id": "semantic-entity-registry", "family": "index", "owner": "runtime.semantic_entity",
     "relative_root": ".agentic_engineering_os_px/runtime-core/semantic", "data_class": "derived",
     "erasable": False},
    {"store_id": "resource-ledgers", "family": "telemetry", "owner": "runtime.resource_lifecycle",
     "relative_root": ".agentic_engineering_os_px/studios", "data_class": "evidence", "erasable": False},
    {"store_id": "host-resource-lifecycle", "family": "telemetry", "owner": "runtime.resource_lifecycle",
     "relative_root": ".agentic_engineering_os_px/resource-lifecycle", "data_class": "evidence",
     "erasable": False},
    {"store_id": "operational-gap-ledger", "family": "transcript", "owner": "runtime.operational_gap_ledger",
     "relative_root": "registry/operational_gap_ledger.jsonl", "data_class": "evidence", "erasable": False},
    {"store_id": "provider-route-scan", "family": "index", "owner": "runtime.provider_gateway",
     "relative_root": "registry/provider_route_scan.json", "data_class": "derived", "erasable": False},
    {"store_id": "workspace-memory-vaults", "family": "memory_vault", "owner": "runtime.workspace_manager",
     "relative_root": "projects_tracking/projects", "data_class": "sensitive", "erasable": False},
    {"store_id": "workspace-checkpoints", "family": "backup", "owner": "runtime.workspace_manager",
     "relative_root": "projects_tracking/checkpoints", "data_class": "sensitive", "erasable": False},
    {"store_id": "workspace-control-history", "family": "backup", "owner": "runtime.workspace_manager",
     "relative_root": "projects_tracking/history", "data_class": "evidence", "erasable": False},
    {"store_id": "evidence-cache", "family": "cache", "owner": "runtime.evidence_cache",
     "relative_root": ".agentic_engineering_os_px/evidence-cache", "data_class": "derived", "erasable": False},
    {"store_id": "model-branch-artifacts", "family": "transcript", "owner": "runtime.model_branch_artifacts",
     "relative_root": ".agentic_engineering_os_px/runtime-core/model-artifacts", "data_class": "evidence", "erasable": False},
    {"store_id": "operation-events-wal", "family": "transcript", "owner": "runtime.operational_event_bus",
     "relative_root": ".agentic_engineering_os_px/operation-bus", "data_class": "evidence", "erasable": False},
    {"store_id": "task-plans", "family": "task_snapshot", "owner": "runtime.task_execution_plan",
     "relative_root": ".agentic_engineering_os_px/task-plans", "data_class": "operational", "erasable": False},
    {"store_id": "semantic-remap-preimages", "family": "backup", "owner": "runtime.semantic_remap_transaction",
     "relative_root": ".agentic_engineering_os_px/runtime-core/semantic-remaps", "data_class": "evidence", "erasable": False},
    {"store_id": "project-map-history", "family": "backup", "owner": "runtime.project_map",
     "relative_root": ".agentic_engineering_os_px/project-map-history", "data_class": "evidence", "erasable": False},
    {"store_id": "project-map-history-archives", "family": "backup", "owner": "runtime.project_map",
     "relative_root": ".agentic_engineering_os_px/project-map-history-archives", "data_class": "evidence", "erasable": False},
    {"store_id": "legacy-campaign-evidence", "family": "backup", "owner": "campaign-preservation",
     "relative_root": ".engineering-bootstrap", "data_class": "evidence", "erasable": False},
)


def _store_present(root: Path, relative: str) -> bool:
    relative = portable_member_name(relative, allow_directory=False, max_bytes=512)
    candidate = root / relative
    reject_path_links(candidate)
    return candidate.exists()


def build_inventory(root: Path, *, retention_policy: Mapping[str, object] | None = None) -> dict[str, object]:
    """Build the bounded data inventory over the real declared stores.

    ``retention_policy`` is the human-declared policy: ``{"default_retention_days": int,
    "legal_hold": ["store_id", ...]}``. Absent it, retention is reported ``unset`` and no
    legal hold is asserted — the inventory never invents a policy.
    """
    reject_path_links(Path(root))
    root = Path(root).resolve(strict=True)
    policy = dict(retention_policy or {})
    if set(policy) - {"default_retention_days", "legal_hold", "store_retention_days"}:
        raise DataInventoryError("unknown retention policy fields")
    default_retention = policy.get("default_retention_days")
    if default_retention is not None and (type(default_retention) is not int or not 0 <= default_retention <= 365000):
        raise DataInventoryError("retention policy default_retention_days must be a non-negative integer")
    holds = policy.get("legal_hold", [])
    if not isinstance(holds, (list, tuple)) or any(type(item) is not str for item in holds):
        raise DataInventoryError("retention policy legal_hold must be a list of store ids")
    known = {str(row["store_id"]) for row in DECLARED_STORES}
    windows = policy.get("store_retention_days", {})
    if (type(windows) is not dict or set(windows) - known or set(holds) - known
            or len(holds) != len(set(holds))
            or any(type(value) is not int or not 0 <= value <= 365000 for value in windows.values())):
        raise DataInventoryError("retention windows/holds must reference exact declared stores")

    stores = []
    for declaration in DECLARED_STORES:
        store_id = str(declaration["store_id"])
        relative = str(declaration["relative_root"])
        present = _store_present(root, relative)
        data_class = str(declaration["data_class"])
        if data_class not in DATA_CLASSES:
            raise DataInventoryError(f"store {store_id} declares an unknown data class")
        hold = store_id in holds
        preservation = data_class == "evidence"
        stores.append(DataStore(
            store_id=store_id,
            family=str(declaration["family"]),
            owner=str(declaration["owner"]),
            relative_root=relative,
            data_class=data_class,
            retention_days=(windows.get(store_id, default_retention) if present else None),
            legal_hold=hold,
            erasable=bool(declaration["erasable"]) and not hold and not preservation,
        ).as_dict() | {"present": present, "preservation_required": preservation,
            "subject_record_resolution_required": True,
            "classification_status": "store_family_declared_record_classification_pending",
            "may_contain_personal_data": True,
            "location_scope": "declared_local_container_not_complete_record_inventory"})

    covered_families = {store["family"] for store in stores if store["present"]}
    body = {
        "schema_version": SCHEMA_VERSION,
        "store_count": len(stores),
        "present_count": sum(1 for store in stores if store["present"]),
        "stores": stores,
        "families_covered": sorted(covered_families),
        "families_absent": sorted(set(STORE_FAMILIES) - covered_families),
        "absence_scope": "No present declared local container; not proof the family has no other copies",
        "coverage_complete": False,
        "unenumerated_surfaces": ["configured external memory repositories", "provider-side transcripts/caches",
            "extension workspaceState/SecretStorage", "OS backups and filesystem snapshots",
            "externally selected transcript/export roots", "in-process semantic document caches",
            "owner-selected data-control request files", "unsaved response documents and VS Code hot-exit backups"],
        "record_control_coverage": [{"store_id": store["store_id"], "owner": store["owner"],
            "control_owner": "runtime.personal_record_store" if store["store_id"] == "canonical-personal-records" else None,
            "status": "native_consumer_implemented_deployment_approval_required" if store["store_id"] == "canonical-personal-records"
                      else "canonical_subject_copy_integration_unresolved",
            "global_erasure_proved": False} for store in stores],
        "preserved_vault_access_owner": {"owner": "runtime.data_subject_records", "canonical_owner": "runtime.memory_vault",
            "subject_binding_required": True, "sealed_erasure": "refused", "global_erasure_proved": False},
        "retention_policy_declared": bool(policy),
        "authority_granted": False,
    }
    import hashlib, json as _json
    body["inventory_sha256"] = hashlib.sha256(
        _json.dumps({k: v for k, v in body.items() if k != "inventory_sha256"},
                    sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return body


def _require_inventory(inventory: Mapping[str, object]) -> None:
    bounded_canonical_json_bytes(dict(inventory), max_bytes=4 * 1024 * 1024)
    if inventory.get("schema_version") != SCHEMA_VERSION:
        raise DataInventoryError("data control requires a current inventory")
    body = {key: value for key, value in inventory.items() if key != "inventory_sha256"}
    import json
    expected = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    if inventory.get("inventory_sha256") != expected:
        raise DataInventoryError("inventory digest differs from its actual body")
    rows = inventory.get("stores")
    if type(rows) is not list or len(rows) != len(DECLARED_STORES):
        raise DataInventoryError("inventory denominator differs from declared stores")
    declared = {row["store_id"]: row for row in DECLARED_STORES}
    if {row.get("store_id") for row in rows if isinstance(row, Mapping)} != set(declared):
        raise DataInventoryError("inventory store identities are missing or unknown")
    for row in rows:
        if any(row.get(key) != declared[row["store_id"]][key]
               for key in ("family", "owner", "relative_root", "data_class")):
            raise DataInventoryError("inventory substituted canonical store ownership")
        if row.get("erasable") is True and not declared[row["store_id"]]["erasable"]:
            raise DataInventoryError("inventory cannot grant erasure capability")
        if (row.get("preservation_required") is not (row["data_class"] == "evidence")
                or row.get("subject_record_resolution_required") is not True):
            raise DataInventoryError("inventory cannot remove native preservation or subject-resolution conditions")


def erasure_plan(inventory: Mapping[str, object], subject_scope: Iterable[str]) -> dict[str, object]:
    """Plan an erasure across every reconstructable copy for a subject scope.

    This is a PLAN, never an execution: it enumerates every store the erasure must
    cover, refuses to touch legal-hold/evidence stores, and lists the derived
    stores that must be *rebuilt* (not merely deleted) so a stale index cannot
    reconstruct erased canonical data. A human-approved executor applies it.
    """
    _require_inventory(inventory)
    from itertools import islice
    if isinstance(subject_scope, (str, bytes)):
        raise DataInventoryError("subject scope must be a sequence of identifiers")
    values = list(islice(subject_scope, 129))
    if len(values) > 128 or any(type(item) is not str or not item.strip()
            or len(item.encode("utf-8")) > 256 or any(ord(c) < 32 for c in item) for item in values):
        raise DataInventoryError("subject scope requires bounded actual identifiers")
    scope = sorted(set(values))
    if not scope:
        raise DataInventoryError("erasure requires a non-empty subject scope")
    erase, rebuild, refused = [], [], []
    for store in inventory["stores"]:
        if not store.get("present"):
            continue
        if store.get("legal_hold"):
            refused.append({"store_id": store["store_id"], "reason": "human_declared_legal_hold"})
            continue
        if store.get("preservation_required"):
            refused.append({"store_id": store["store_id"], "reason": "technical_evidence_preservation"})
            continue
        if store.get("subject_record_resolution_required"):
            refused.append({"store_id": store["store_id"], "reason": "canonical_subject_record_resolution_required"})
            continue
        if store["data_class"] in {"derived"}:
            # A derived index must be rebuilt after erasure, not just deleted, or a
            # later rebuild could reconstruct the erased subject.
            rebuild.append(store["store_id"])
            continue
        if store.get("erasable"):
            erase.append(store["store_id"])
        else:
            refused.append({"store_id": store["store_id"], "reason": "not_declared_erasable"})
    body = {
        "schema_version": SCHEMA_VERSION,
        "subject_scope": scope,
        "inventory_sha256": inventory.get("inventory_sha256"),
        "erase_stores": sorted(erase),
        "rebuild_after_erasure": sorted(rebuild),
        "refused_stores": sorted(refused, key=lambda row: row["store_id"]),
        "executed": False,
        "requires_human_approval": True,
        "scope_resolution_complete": False,
        "coverage_complete": inventory.get("coverage_complete") is True,
        "authority_granted": False,
    }
    import hashlib, json as _json
    body["plan_sha256"] = hashlib.sha256(
        _json.dumps({k: v for k, v in body.items() if k != "plan_sha256"},
                    sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return body


def retention_report(
    inventory: Mapping[str, object],
    now_utc: str,
    *,
    store_last_updated_utc: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Report stores whose evidenced age exceeds their declared retention window.

    This is a *mechanic*: it applies the human-declared retention window to the
    real store inventory and reports overdue stores. It performs no deletion. A
    store under legal hold is never reported as overdue-for-deletion, because a
    hold overrides the retention clock. Store ages are never inferred from
    directory timestamps; an owner must supply an exact last-updated timestamp.
    Without that evidence the store is reported as age-unverified, not overdue.
    """
    _require_inventory(inventory)
    from datetime import datetime, timezone
    try:
        moment = datetime.fromisoformat(str(now_utc).replace("Z", "+00:00"))
    except ValueError as error:
        raise DataInventoryError("retention reporting requires an ISO-8601 timestamp") from error
    if moment.tzinfo is None:
        raise DataInventoryError("retention timestamp requires an offset")
    timestamps = dict(store_last_updated_utc or {})
    known_store_ids = {str(store.get("store_id")) for store in inventory.get("stores", [])}
    unknown_store_ids = set(timestamps) - known_store_ids
    if unknown_store_ids:
        raise DataInventoryError("last-updated evidence references an unknown store")
    overdue, held, no_window, within, age_unverified, preserved = [], [], [], [], [], []
    for store in inventory["stores"]:
        if not store.get("present"):
            continue
        if store.get("legal_hold"):
            held.append(store["store_id"])
            continue
        if store.get("preservation_required"):
            preserved.append(store["store_id"])
            continue
        retention = store.get("retention_days")
        if retention is None:
            no_window.append({"store_id": store["store_id"], "reason": "retention_unset"})
            continue
        last_updated_text = timestamps.get(str(store["store_id"]))
        if last_updated_text is None:
            age_unverified.append({"store_id": store["store_id"], "reason": "last_updated_unavailable"})
            continue
        try:
            last_updated = datetime.fromisoformat(str(last_updated_text).replace("Z", "+00:00"))
        except ValueError as error:
            raise DataInventoryError("last-updated evidence requires an ISO-8601 timestamp") from error
        if last_updated.tzinfo is None or last_updated > moment:
            raise DataInventoryError("last-updated evidence must be timezone-aware and not in the future")
        age_days = (moment - last_updated).total_seconds() / 86400
        row = {"store_id": store["store_id"], "retention_days": retention, "age_days": age_days}
        if age_days > retention:
            overdue.append(row)
        else:
            within.append(row)
    body = {
        "schema_version": SCHEMA_VERSION,
        "evaluated_utc": moment.astimezone(timezone.utc).isoformat(),
        "inventory_sha256": inventory.get("inventory_sha256"),
        "overdue_for_review": sorted(overdue, key=lambda row: row["store_id"]),
        "under_legal_hold": sorted(held),
        "under_technical_preservation": sorted(preserved),
        "within_retention": sorted(within, key=lambda row: row["store_id"]),
        "no_declared_window": sorted(no_window, key=lambda row: row["store_id"]),
        "age_unverified": sorted(age_unverified, key=lambda row: row["store_id"]),
        "executed": False,
        "requires_human_approval": True,
        "authority_granted": False,
    }
    return body
