"""Exact effect-scope leases (punch card EXE-005).

A signed effect grant says what an actor MAY do. A lease says what an actor is
doing RIGHT NOW, over which exact scope, until when, and it makes two concurrent
holders of the same scope mutually exclusive.

This owner is intentionally narrow:

* it holds leases for exact ``(effect, scope)`` pairs under a native file lock;
* a lease names the owning execution id, so a stale holder cannot renew or
  release another execution's lease;
* acquisition is refused when a live, unexpired lease already covers an
  overlapping scope for the same effect;
* a native process quarantine excludes overlapping effects beyond lease expiry;
* an ordinary expired lease is reclaimable, and reclamation records the exact prior
  holder so an interrupted run is recoverable rather than silently stolen.

It grants no authority of its own: a caller must already hold the signed effect
grant before acquiring a lease.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .archive_io import reject_path_links
from .file_lock import FileLock
from .json_io import bounded_canonical_json_bytes, read_bounded_bytes

SCHEMA_VERSION = "px.scope-lease/1.0"
LEDGER_SCHEMA_VERSION = "px.scope-lease-ledger/1.0"
MAX_LEDGER_BYTES = 8 * 1024 * 1024
MAX_LEASES = 10_000
LEASE_RELATIVE = ".agentic_engineering_os_px/runtime-core/scope-leases.json"


class ScopeLeaseError(ValueError):
    """Raised when a lease request is invalid or conflicts with a live lease."""


@dataclass(frozen=True, slots=True)
class ScopeLease:
    lease_id: str
    execution_id: str
    effect: str
    scopes: tuple[str, ...]
    acquired_utc: str
    expires_utc: str
    reason: str

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "lease_id": self.lease_id,
            "execution_id": self.execution_id,
            "effect": self.effect,
            "scopes": list(self.scopes),
            "acquired_utc": self.acquired_utc,
            "expires_utc": self.expires_utc,
            "reason": self.reason,
            "authority_granted": False,
        }


def _parse(value: str) -> datetime:
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as error:
        raise ScopeLeaseError("lease timestamps must be ISO-8601") from error
    if moment.tzinfo is None:
        raise ScopeLeaseError("lease timestamps require an offset")
    return moment.astimezone(timezone.utc)


def _normalize_scopes(scopes: Iterable[str]) -> tuple[str, ...]:
    values = sorted({str(scope).strip().replace("\\", "/") for scope in scopes})
    if not values or any(not value or len(value) > 512 for value in values):
        raise ScopeLeaseError("lease scope must be a non-empty bounded set")
    return tuple(values)


def _overlaps(left: tuple[str, ...], right: tuple[str, ...]) -> bool:
    for a in left:
        for b in right:
            if a == b or a.startswith(b + "/") or b.startswith(a + "/"):
                return True
    return False


class ScopeLeaseStore:
    """Durable exact-scope lease ledger under a native file lock."""

    def __init__(self, root: Path) -> None:
        reject_path_links(Path(root))
        self.root = Path(root).resolve(strict=True)
        self.path = self.root / LEASE_RELATIVE
        self.lock_path = self.path.parent / ".scope-leases.lock"

    def _load(self) -> list[dict[str, object]]:
        if not self.path.is_file():
            return []
        raw = bytes(read_bounded_bytes(self.path, max_bytes=MAX_LEDGER_BYTES))
        try:
            document = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeError) as error:
            raise ScopeLeaseError("scope lease ledger is corrupt") from error
        if not isinstance(document, dict) or document.get("schema_version") != LEDGER_SCHEMA_VERSION:
            raise ScopeLeaseError("scope lease ledger schema is unsupported")
        leases = document.get("leases")
        if not isinstance(leases, list) or len(leases) > MAX_LEASES:
            raise ScopeLeaseError("scope lease ledger record budget is invalid")
        from .studio_models import digest
        for row in leases:
            quarantine = row.get("quarantine")
            if quarantine is None:
                continue
            if (type(quarantine) is not dict or quarantine.get("schema_version") != "px.scope-quarantine/1.0"
                    or quarantine.get("state") not in {"held", "resolved"}
                    or type(quarantine.get("binding")) is not dict
                    or quarantine.get("quarantine_id") != "scope-quarantine:"+digest(quarantine["binding"])
                    or any(quarantine["binding"].get(key) != row.get(key)
                           for key in ("lease_id", "execution_id", "effect", "scopes"))):
                raise ScopeLeaseError("scope quarantine identity is corrupt")
            binding = quarantine["binding"]
            if set(binding) != {"lease_id","execution_id","effect","scopes","execution_context","custody"}:
                raise ScopeLeaseError("scope quarantine binding fields differ")
            context = binding["execution_context"]
            custody = binding["custody"]
            if custody is not None:
                from .execution_context import execution_context_from_dict
                typed = execution_context_from_dict(context)
                if (type(custody) is not dict or custody.get("run_id") != typed.root_execution_id
                        or custody.get("project_id") != typed.project_id or custody.get("creator") != typed.actor_id):
                    raise ScopeLeaseError("scope quarantine context and custody differ")
            elif (type(context) is not dict or context.get("schema_version") != "px.unresolved-workflow-effect-context/1.0"):
                raise ScopeLeaseError("scope quarantine unresolved context is invalid")
            if quarantine["state"] == "resolved":
                sha = quarantine.get("closure_receipt_sha256")
                if type(sha) is not str or len(sha)!=64 or any(c not in "0123456789abcdef" for c in sha):
                    raise ScopeLeaseError("scope quarantine closure evidence is missing or invalid")
        return leases

    def _store(self, leases: list[dict[str, object]]) -> None:
        if len(leases) > MAX_LEASES:
            raise ScopeLeaseError("scope lease/quarantine record budget exhausted")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        reject_path_links(self.path.parent)
        image = bounded_canonical_json_bytes(
            {"schema_version": LEDGER_SCHEMA_VERSION, "leases": leases}, max_bytes=MAX_LEDGER_BYTES
        )
        prepared = self.path.parent / f".scope-leases-{os.getpid()}.prepared"
        with prepared.open("wb") as stream:
            stream.write(image)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(prepared, self.path)

    def active(self, *, effect: str, now_utc: str | None = None) -> tuple[ScopeLease, ...]:
        """Return live, unexpired leases for one effect."""
        moment = _parse(now_utc) if now_utc else datetime.now(timezone.utc)
        result = []
        for row in self._load():
            if row.get("effect") != effect or (row.get("quarantine") or {}).get("state") == "resolved":
                continue
            if _parse(str(row["expires_utc"])) <= moment:
                continue
            result.append(ScopeLease(
                str(row["lease_id"]), str(row["execution_id"]), str(row["effect"]),
                tuple(row["scopes"]), str(row["acquired_utc"]), str(row["expires_utc"]),
                str(row.get("reason", "")),
            ))
        return tuple(result)

    def quarantines(self, *, effect: str | None = None) -> tuple[dict, ...]:
        """Observe durable exclusions; TTL never resolves physical uncertainty."""
        return tuple(json.loads(json.dumps(row["quarantine"])) for row in self._load()
            if (row.get("quarantine") or {}).get("state") == "held"
            and (effect is None or row.get("effect") == effect))

    def quarantine(self, *, lease_id: str, execution_id: str, execution_context,
                   manager, resource_id: str) -> str:
        """Arm exact scope exclusion while native supervisor custody is still live.

        The caller cannot assert containment: the ResourceManager re-proves its
        retained Job/process identity and registers independent closure tracking.
        """
        from .execution_context import ExecutionContext, execution_context_from_dict
        from .resource_lifecycle import ResourceManager
        if type(manager) is not ResourceManager or type(execution_context) is not ExecutionContext:
            raise ScopeLeaseError("quarantine requires native resource manager and typed execution context")
        context = execution_context_from_dict(execution_context.as_dict())
        custody = manager.track_physical_process_tree_closure(resource_id, project_root=self.root)
        if (custody["run_id"] != context.root_execution_id or custody["project_id"] != context.project_id
                or custody["creator"] != context.actor_id):
            raise ScopeLeaseError("quarantine custody differs from its execution context")
        return self._quarantine(lease_id=lease_id, execution_id=execution_id,
            context=context.as_dict(), custody=custody)

    def quarantine_unresolved(self, *, lease_id: str, execution_id: str, run_id: str,
                              node_id: str, authority_reference_sha256: str, attempt: int) -> str:
        """Retain an unbound unknown failure, never invent physical custody proof.

        This conservative exclusion cannot be cleared as a bound closure receipt.
        Native owner reconciliation must recover the actual missing launch identity.
        """
        if (any(type(value) is not str or not value or len(value)>512
                for value in (run_id,node_id,authority_reference_sha256))
                or len(authority_reference_sha256) != 64 or type(attempt) is not int or attempt < 1):
            raise ScopeLeaseError("unresolved quarantine execution binding is invalid")
        context = {"schema_version":"px.unresolved-workflow-effect-context/1.0", "run_id":run_id,
            "node_id":node_id,"authority_reference_sha256":authority_reference_sha256,"attempt":attempt}
        return self._quarantine(lease_id=lease_id, execution_id=execution_id, context=context, custody=None)

    def _quarantine(self, *, lease_id, execution_id, context, custody):
        from .studio_models import digest
        with FileLock(self.lock_path, timeout_seconds=10):
            leases = self._load()
            target = next((row for row in leases if row.get("lease_id") == lease_id), None)
            if target is None or target.get("execution_id") != execution_id:
                raise ScopeLeaseError("quarantine requires the exact retained lease owner")
            binding = {key:target[key] for key in ("lease_id","execution_id","effect","scopes")}
            binding.update(execution_context=context, custody=custody)
            quarantine_id = "scope-quarantine:"+digest(binding)
            prior = target.get("quarantine")
            if prior is not None:
                if prior["quarantine_id"] != quarantine_id or prior["state"] != "held":
                    raise ScopeLeaseError("quarantine cannot be rebound or reopened")
                return quarantine_id
            target["quarantine"] = {"schema_version":"px.scope-quarantine/1.0", "state":"held",
                "quarantine_id":quarantine_id,"binding":binding,"armed_utc":datetime.now(timezone.utc).isoformat()}
            self._store(leases)
            return quarantine_id

    def resolve_quarantine(self, *, lease_id: str, execution_id: str, manager) -> str:
        """Release exclusion only from retained independent native physical closure."""
        from .resource_lifecycle import ResourceManager
        if type(manager) is not ResourceManager:
            raise ScopeLeaseError("quarantine resolution requires the native resource owner")
        with FileLock(self.lock_path, timeout_seconds=10):
            leases = self._load()
            target = next((row for row in leases if row.get("lease_id") == lease_id), None)
            if target is None or target.get("execution_id") != execution_id:
                raise ScopeLeaseError("quarantine resolution lease identity differs")
            quarantine = target.get("quarantine")
            if quarantine is None or quarantine["binding"].get("custody") is None:
                raise ScopeLeaseError("quarantine has no independently bound physical custody")
            custody = quarantine["binding"]["custody"]
            proof = manager.reconcile_physical_process_tree_closure(custody["resource_id"],
                project_root=self.root, job_object_id=custody["job_object_id"])
            if proof["identity"] != custody:
                raise ScopeLeaseError("physical closure receipt differs from quarantine custody")
            if quarantine["state"] == "resolved":
                if quarantine["closure_receipt_sha256"] != proof["receipt_sha256"]:
                    raise ScopeLeaseError("quarantine resolution proof cannot be rewritten")
                return proof["receipt_sha256"]
            quarantine.update(state="resolved",closure_receipt_sha256=proof["receipt_sha256"],
                resolved_utc=datetime.now(timezone.utc).isoformat())
            self._store(leases)
            return proof["receipt_sha256"]

    def _verify_resolved_quarantine(self, quarantine):
        # A stored resolved flag is not independent physical evidence. Recheck
        # the exact retained native receipt before admitting overlap.
        from .resource_lifecycle import ResourceManager
        custody = quarantine["binding"].get("custody")
        if custody is None:
            raise ScopeLeaseError("resolved quarantine has no native physical closure custody")
        state_path = Path(str(custody.get("manager_state_path", "")))
        if (state_path.is_absolute() or ".." in state_path.parts
                or not state_path.as_posix().startswith(".agentic_engineering_os_px/")):
            raise ScopeLeaseError("resolved quarantine native state path differs")
        manager = ResourceManager(self.root/state_path)
        proof = manager.read_physical_process_tree_closure(custody["resource_id"],
            project_root=self.root,job_object_id=custody["job_object_id"])
        if proof["identity"] != custody or proof["receipt_sha256"] != quarantine["closure_receipt_sha256"]:
            raise ScopeLeaseError("resolved quarantine native closure proof differs")

    def acquire(self, *, lease_id: str, execution_id: str, effect: str, scopes: Iterable[str],
                reason: str, expires_utc: str, now_utc: str | None = None) -> ScopeLease:
        """Acquire an exclusive lease over an exact scope, or refuse on conflict."""
        for name, value in (("lease_id", lease_id), ("execution_id", execution_id), ("effect", effect)):
            if type(value) is not str or not value.strip() or len(value) > 512:
                raise ScopeLeaseError(f"{name} must be bounded nonempty text")
        if type(reason) is not str or not reason.strip() or len(reason) > 512:
            raise ScopeLeaseError("lease reason must be bounded nonempty text")
        normalized = _normalize_scopes(scopes)
        moment = _parse(now_utc) if now_utc else datetime.now(timezone.utc)
        expiry = _parse(expires_utc)
        if expiry <= moment:
            raise ScopeLeaseError("lease expiration must be in the future")
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(self.lock_path, timeout_seconds=10):
            leases = self._load()
            # Expired leases are reclaimed in place; the exact prior holder is
            # retained in `reclaimed_from` so an interrupted run is recoverable.
            live: list[dict[str, object]] = []
            for row in leases:
                quarantine = row.get("quarantine")
                if quarantine is not None:
                    if row.get("effect") == effect and _overlaps(tuple(row["scopes"]), normalized):
                        if quarantine["state"] == "held":
                            raise ScopeLeaseError("scope quarantined pending native physical closure: "+quarantine["quarantine_id"])
                        self._verify_resolved_quarantine(quarantine)
                    live.append(row)
                    continue
                if _parse(str(row["expires_utc"])) <= moment:
                    continue
                if row.get("effect") == effect and _overlaps(tuple(row["scopes"]), normalized):
                    if row.get("execution_id") != execution_id:
                        raise ScopeLeaseError(
                            "scope lease conflict with live holder " + str(row.get("execution_id"))
                        )
                live.append(row)
            if any(row.get("lease_id") == lease_id for row in live):
                raise ScopeLeaseError("lease id already held by a live lease")
            lease = ScopeLease(lease_id, execution_id, effect, normalized,
                               moment.isoformat(), expiry.isoformat(), reason)
            live.append(lease.as_dict())
            self._store(live)
            return lease

    def release(self, *, lease_id: str, execution_id: str) -> bool:
        """Release a lease owned by the exact execution. Refuses another owner's."""
        with FileLock(self.lock_path, timeout_seconds=10):
            leases = self._load()
            target = next((row for row in leases if row.get("lease_id") == lease_id), None)
            if target is None:
                return False
            if target.get("execution_id") != execution_id:
                raise ScopeLeaseError("lease is owned by a different execution")
            quarantine = target.get("quarantine")
            if quarantine is not None:
                if quarantine["state"] != "resolved":
                    raise ScopeLeaseError("quarantined lease requires independent native closure before release")
                # Retain the exact closure tombstone for provenance and replay.
                return True
            self._store([row for row in leases if row.get("lease_id") != lease_id])
            return True