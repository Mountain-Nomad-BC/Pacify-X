"""Canonical, versioned studio records with independent lifecycle dimensions."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Mapping, Sequence
from uuid import uuid4

from .file_lock import FileLock
from .studio_filesystem import (
    bounded_directory_entries,
    read_bounded_regular_file,
)


IDENTITY = re.compile(r"^[a-z0-9][a-z0-9._:-]{1,127}$")
# PX canonical versions are lowercase ``major.minor.patch`` values with an
# optional ``-`` or ``.`` suffix.  The complete suffix is bounded to 64
# characters and every dot-delimited identifier must begin and end with an
# ASCII alphanumeric character.  Keep this grammar identical to the dashboard
# VERSION_PATTERN; normalization is trim + lowercase before validation.
CANONICAL_VERSION = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:[.-]([a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)*))?$"
)
CANONICAL_UTC = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{3})?Z$"
)
STUDIO_VERSION_ALLOCATION_SCHEMA = "px.studio-version-allocation/1.0"
MAX_VERSION_COMPONENT = (2**31) - 1
MAX_VERSION_ALLOCATION_PROBES = 10_000
MAX_VERSION_OCCUPANCY_ENTRIES = 10_000
MAX_REVISION_TREE_ENTRIES = 512
MAX_REVISION_TREE_FILE_BYTES = 4 * 1024 * 1024
MAX_REVISION_TREE_BYTES = 16 * 1024 * 1024
MAX_REVISION_TREE_DEPTH = 12
_STUDIO_KIND_ROOTS = {
    "agent": "agents",
    "agents": "agents",
    "workflow": "workflows",
    "workflows": "workflows",
    "skill": "skills",
    "skills": "skills",
}
LIFECYCLE_STATES = frozenset(
    {"draft", "candidate", "tested", "admitted", "deprecated", "retired", "rejected"}
)
PORT_TYPES = frozenset(
    {"json", "string", "integer", "number", "boolean", "object", "array"}
)
FAILURE_POLICIES = frozenset({"fail-closed", "continue"})
EDGE_CONDITIONS = frozenset(
    {"always", "never", "source-present", "source-truthy", "source-falsy"}
)
WORKFLOW_NODE_KINDS = frozenset(
    {"task", "validation", "approval", "branch", "join"}
)
VALIDATION_OPERATORS = frozenset(
    {
        "exists",
        "truthy",
        "falsy",
        "equals",
        "not-equals",
        "type",
        "greater-than-or-equal",
        "less-than-or-equal",
        "contains",
    }
)
VALIDATION_SOURCES = frozenset({"inputs", "outputs"})


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def digest(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def write_json_atomic(path: Path, value: object) -> None:
    """Publish formatted JSON through one same-directory atomic replacement."""
    path.parent.mkdir(parents=True, exist_ok=True)
    prepared = path.with_name(f".{path.name}.{uuid4().hex}.prepared")
    prepared.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(prepared, path)


def _is_link_or_reparse(path: Path) -> bool:
    """Treat every symlink/reparse point as an untrusted traversal boundary."""
    info = path.lstat()
    attributes = int(getattr(info, "st_file_attributes", 0))
    reparse = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    return stat.S_ISLNK(info.st_mode) or bool(attributes & reparse)


def verify_safe_ancestors(
    root: Path, target: Path, *, include_target: bool = False
) -> None:
    """Reject an existing link/reparse point between a bounded root and target.

    This check is intentionally repeated immediately before publication.  It is
    conservative on Windows, where reparse points include junctions.
    """
    root = root.resolve(strict=True)
    if root == Path(root.anchor) or not root.is_dir() or _is_link_or_reparse(root):
        raise ValueError("studio root must be a bounded physical directory")
    candidate = target if include_target else target.parent
    try:
        relative = candidate.relative_to(root)
    except ValueError as error:
        raise ValueError("studio target escapes the project root") from error
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        if os.path.lexists(cursor):
            if _is_link_or_reparse(cursor):
                raise ValueError(
                    f"studio path contains a link or reparse point: {cursor.relative_to(root)}"
                )
            if cursor != candidate and not cursor.is_dir():
                raise ValueError("studio path ancestor is not a directory")


def _identity(value: str, field_name: str) -> str:
    value = str(value).strip().lower()
    if not IDENTITY.fullmatch(value):
        raise ValueError(f"invalid {field_name}")
    return value


def _version(value: str) -> str:
    return _parse_version(value)[0]


STUDIO_VERSION_CONFLICT_REASONS = frozenset(
    {
        "allocation-binding-mismatch",
        "allocation-envelope-invalid",
        "allocation-exhausted",
        "allocation-probe-bound-exhausted",
        "allocation-source-invalid",
        "allocation-stale",
        "immutable-agent-receipt-missing",
        "immutable-agent-revision-differs",
        "immutable-revision-differs",
        "immutable-skill-revision-differs",
        "immutable-workflow-revision-differs",
        "initial-identity-occupied",
        "initial-version-invalid",
        "occupancy-bound-exceeded",
        "publication-collision",
        "revision-already-occupied",
        "external-source-invalid",
        "external-source-not-allowed",
        "source-content-bound-exceeded",
        "source-revision-invalid",
        "source-revision-mismatch",
        "source-revision-missing",
    }
)


class StudioVersionConflict(FileExistsError):
    """A typed immutable-revision collision that callers can recover from."""

    REASONS = STUDIO_VERSION_CONFLICT_REASONS

    def __init__(self, reason: str) -> None:
        token, separator, detail = str(reason).partition(":")
        if token not in self.REASONS:
            raise ValueError("unknown Studio version conflict reason")
        self.reason = token
        self.detail = detail if separator else ""
        super().__init__(f"studio-version-conflict:{reason}")


def _studio_kind(kind: str) -> tuple[str, str]:
    token = str(kind).strip().lower()
    physical = _STUDIO_KIND_ROOTS.get(token)
    if physical is None:
        raise ValueError("studio version kind must be agent, workflow, or skill")
    return physical.removesuffix("s"), physical


def studio_component(identity: str) -> str:
    identity = _identity(identity, "record identity")
    return (
        f"{re.sub(r'[^a-z0-9._-]+', '-', identity).strip('-')}-"
        f"{hashlib.sha256(identity.encode()).hexdigest()[:8]}"
    )


def studio_revision_root(root: Path, kind: str, identity: str) -> Path:
    root = root.resolve(strict=True)
    _, physical = _studio_kind(kind)
    return (
        root
        / ".engineering-bootstrap"
        / "studios"
        / physical
        / studio_component(identity)
        / "revisions"
    )


def studio_revision_lock(root: Path, kind: str, identity: str) -> Path:
    return studio_revision_root(root, kind, identity).parent / ".revision-publication.lock"


def _revision_tree_sha256(root: Path, revision: Path) -> str:
    """Hash a bounded physical revision tree without following links."""
    project_root = root.resolve(strict=True)
    verify_safe_ancestors(project_root, revision, include_target=True)
    if not revision.is_dir() or _is_link_or_reparse(revision):
        raise StudioVersionConflict("source-revision-invalid")
    rows: list[dict[str, object]] = []
    total_bytes = 0
    pending = [revision]
    while pending:
        directory = pending.pop()
        try:
            entries = bounded_directory_entries(
                directory,
                MAX_REVISION_TREE_ENTRIES - len(rows),
                lambda: StudioVersionConflict("source-content-bound-exceeded"),
            )
        except StudioVersionConflict:
            raise
        except OSError as error:
            raise StudioVersionConflict("source-revision-invalid") from error
        for entry in entries:
            relative = entry.relative_to(revision)
            if len(relative.parts) > MAX_REVISION_TREE_DEPTH:
                raise StudioVersionConflict("source-content-bound-exceeded")
            if len(rows) >= MAX_REVISION_TREE_ENTRIES:
                raise StudioVersionConflict("source-content-bound-exceeded")
            try:
                if entry.is_symlink() or _is_link_or_reparse(entry):
                    raise StudioVersionConflict("source-revision-invalid")
                if entry.is_dir():
                    rows.append({"kind": "directory", "path": relative.as_posix()})
                    pending.append(entry)
                    continue
                if not entry.is_file():
                    raise StudioVersionConflict("source-revision-invalid")
                data = read_bounded_regular_file(
                    entry,
                    min(
                        MAX_REVISION_TREE_FILE_BYTES,
                        MAX_REVISION_TREE_BYTES - total_bytes,
                    ),
                    lambda: StudioVersionConflict("source-content-bound-exceeded"),
                )
                size = len(data)
                total_bytes += size
                rows.append(
                    {
                        "kind": "file",
                        "path": relative.as_posix(),
                        "size": size,
                        "sha256": hashlib.sha256(data).hexdigest(),
                    }
                )
            except StudioVersionConflict:
                raise
            except OSError as error:
                raise StudioVersionConflict("source-revision-invalid") from error
    rows.sort(key=lambda row: (str(row["path"]), str(row["kind"])))
    return digest(rows)


def _source_revision_identity(
    root: Path, kind: str, identity: str, source_version: str
) -> tuple[str, str]:
    """Return the catalog-facing revision hash and bounded tree hash."""
    singular, _ = _studio_kind(kind)
    identity = _identity(identity, f"{singular} identity")
    source_version = _version(source_version)
    revision = studio_revision_root(root, singular, identity) / source_version
    if not revision.exists() and not revision.is_symlink():
        raise StudioVersionConflict("source-revision-missing")
    if revision.is_symlink() or not revision.is_dir() or _is_link_or_reparse(revision):
        raise StudioVersionConflict("source-revision-invalid")
    record_path = revision / (
        "package-record.json" if singular == "skill" else "record.json"
    )
    try:
        if (
            not record_path.is_file()
            or record_path.is_symlink()
            or _is_link_or_reparse(record_path)
            or record_path.stat().st_size > MAX_REVISION_TREE_FILE_BYTES
        ):
            raise StudioVersionConflict("source-revision-invalid")
        raw = read_bounded_regular_file(
            record_path,
            MAX_REVISION_TREE_FILE_BYTES,
            lambda: StudioVersionConflict("source-revision-invalid"),
        )
        envelope = json.loads(raw.decode("utf-8"))
    except StudioVersionConflict:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError) as error:
        raise StudioVersionConflict("source-revision-invalid") from error
    if not isinstance(envelope, Mapping):
        raise StudioVersionConflict("source-revision-invalid")
    if singular == "skill":
        model = envelope.get("manifest")
        identity_field = "skill_id"
        revision_sha256 = str(envelope.get("manifest_sha256") or "")
        try:
            valid_digest = isinstance(model, Mapping) and revision_sha256 == digest(model)
        except (TypeError, ValueError):
            valid_digest = False
        if not valid_digest:
            raise StudioVersionConflict("source-revision-invalid")
    else:
        model = envelope.get("record")
        identity_field = "agent_id" if singular == "agent" else "workflow_id"
        try:
            valid_digest = isinstance(model, Mapping) and envelope.get("sha256") == digest(model)
        except (TypeError, ValueError):
            valid_digest = False
        if not valid_digest:
            raise StudioVersionConflict("source-revision-invalid")
        revision_sha256 = hashlib.sha256(raw).hexdigest()
    try:
        model_identity = _identity(str(model.get(identity_field) or ""), identity_field)
        model_version = _version(str(model.get("version") or ""))
    except ValueError as error:
        raise StudioVersionConflict("source-revision-invalid") from error
    if model_identity != identity or model_version != source_version:
        raise StudioVersionConflict("source-revision-mismatch")
    return revision_sha256, _revision_tree_sha256(root, revision)


def _parse_version(value: str) -> tuple[str, int, int, int, bool]:
    normalized = str(value).strip().lower()
    if len(normalized) > 96:
        raise ValueError("version exceeds bounded semantic-version length")
    match = CANONICAL_VERSION.fullmatch(normalized)
    if match is None:
        raise ValueError("invalid canonical version")
    components = tuple(int(match.group(index)) for index in (1, 2, 3))
    if any(component > MAX_VERSION_COMPONENT for component in components):
        raise ValueError("version component exceeds the bounded integer range")
    prerelease = match.group(4)
    if prerelease and len(prerelease) > 64:
        raise ValueError("version suffix exceeds bounded semantic-version length")
    if prerelease and any(
        part.isdigit() and len(part) > 1 and part.startswith("0")
        for part in prerelease.split(".")
    ):
        raise ValueError("invalid canonical version")
    return (
        normalized,
        components[0],
        components[1],
        components[2],
        prerelease is not None,
    )


def valid_canonical_utc(value: object) -> bool:
    """Accept only a real canonical UTC instant used by allocation envelopes."""
    if not isinstance(value, str) or CANONICAL_UTC.fullmatch(value) is None:
        return False
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return False
    return True


def _valid_observed_utc(value: object) -> bool:
    """Backward-compatible private alias for canonical UTC validation."""

    return valid_canonical_utc(value)


def _version_parts(value: str) -> tuple[int, int, int, bool]:
    _, major, minor, patch, prerelease = _parse_version(value)
    return major, minor, patch, prerelease


def _occupied_versions(root: Path, kind: str, identity: str) -> tuple[str, ...]:
    revisions = studio_revision_root(root, kind, identity)
    verify_safe_ancestors(root.resolve(strict=True), revisions)
    try:
        # ``Path.exists`` follows links.  A dangling revision-root link is a
        # physical authority boundary, not proof that the identity is absent.
        if not os.path.lexists(revisions):
            return ()
        if _is_link_or_reparse(revisions) or not revisions.is_dir():
            raise StudioVersionConflict("source-revision-invalid")
    except StudioVersionConflict:
        raise
    except OSError as error:
        raise StudioVersionConflict("source-revision-invalid") from error
    occupied: list[str] = []
    try:
        entries = bounded_directory_entries(
            revisions,
            MAX_VERSION_OCCUPANCY_ENTRIES,
            lambda: StudioVersionConflict("occupancy-bound-exceeded"),
        )
    except StudioVersionConflict:
        raise
    except OSError as error:
        raise StudioVersionConflict("source-revision-invalid") from error
    for entry in entries:
        try:
            if entry.is_symlink() or _is_link_or_reparse(entry):
                raise StudioVersionConflict("source-revision-invalid")
            canonical = _version(entry.name)
            # Parser normalization is valid for user input, but physical
            # occupancy must require an exact canonical filename.  Otherwise
            # whitespace/case aliases can consume a candidate without being a
            # publishable canonical revision path.
            if entry.name == canonical:
                occupied.append(canonical)
        except StudioVersionConflict:
            raise
        except ValueError:
            # Non-revision control artifacts are not semantic-version occupancy.
            continue
        except OSError as error:
            # Removal, replacement, or ACL races remain a typed fail-closed
            # conflict rather than leaking a platform-specific raw exception.
            raise StudioVersionConflict("source-revision-invalid") from error
    return tuple(sorted(set(occupied)))


def studio_identity_absence(
    root: Path, kind: str, identity: str
) -> dict[str, object]:
    """Report physical identity absence from the authoritative revision store."""
    root = root.resolve(strict=True)
    singular, _ = _studio_kind(kind)
    canonical_identity = _identity(identity, f"{singular} identity")
    occupied = _occupied_versions(root, singular, canonical_identity)
    return {
        "schema_version": "px.studio-identity-absence/1.0",
        "kind": singular,
        "identity": canonical_identity,
        "absent": not occupied,
        "observed_utc": datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z"),
    }


def require_initial_studio_identity(
    root: Path, kind: str, identity: str, version: str
) -> None:
    """Admit only a real first revision or an exact 1.0.0 idempotent replay."""
    root = root.resolve(strict=True)
    singular, _ = _studio_kind(kind)
    canonical_identity = _identity(identity, f"{singular} identity")
    canonical_version = _version(version)
    occupied = _occupied_versions(root, singular, canonical_identity)
    if canonical_version != "1.0.0":
        raise StudioVersionConflict("initial-version-invalid")
    if not occupied or occupied == ("1.0.0",):
        return
    raise StudioVersionConflict("initial-identity-occupied")


def allocate_studio_version(
    root: Path,
    kind: str,
    identity: str,
    source_version: str,
    *,
    source_scope: str = "studio-physical",
    source_revision_sha256: str | None = None,
    source_content_sha256: str | None = None,
) -> dict[str, object]:
    """Allocate a bounded next revision with explicit predecessor provenance."""
    singular, _ = _studio_kind(kind)
    identity = _identity(identity, f"{singular} identity")
    source_version = _version(source_version)
    major, minor, patch, prerelease = _version_parts(source_version)
    if source_scope == "studio-physical":
        if source_revision_sha256 is not None or source_content_sha256 is not None:
            raise StudioVersionConflict("external-source-invalid")
        source_revision_sha256, source_content_sha256 = _source_revision_identity(
            root, singular, identity, source_version
        )
    elif source_scope == "external-authenticated":
        if singular != "skill":
            raise StudioVersionConflict("external-source-not-allowed")
        hashes = (source_revision_sha256, source_content_sha256)
        if any(
            not isinstance(item, str)
            or re.fullmatch(r"[0-9a-f]{64}", item) is None
            for item in hashes
        ):
            raise StudioVersionConflict("external-source-invalid")
    else:
        raise StudioVersionConflict("external-source-invalid")
    occupied = _occupied_versions(root, singular, identity)
    occupied_set = set(occupied)
    candidate_patch = patch if prerelease else patch + 1
    for _ in range(MAX_VERSION_ALLOCATION_PROBES):
        if candidate_patch > MAX_VERSION_COMPONENT:
            raise StudioVersionConflict("allocation-exhausted")
        candidate = f"{major}.{minor}.{candidate_patch}"
        if candidate not in occupied_set:
            break
        candidate_patch += 1
    else:
        raise StudioVersionConflict("allocation-probe-bound-exhausted")
    return {
        "schema_version": STUDIO_VERSION_ALLOCATION_SCHEMA,
        "kind": singular,
        "identity": identity,
        "source_version": source_version,
        "source_scope": source_scope,
        "source_revision_sha256": source_revision_sha256,
        "source_content_sha256": source_content_sha256,
        "candidate_version": candidate,
        "occupied_versions_sha256": digest(list(occupied)),
        "observed_utc": datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z"),
    }


def revalidate_studio_version_allocation(
    root: Path,
    kind: str,
    identity: str,
    version: str,
    allocation: Mapping[str, object],
) -> None:
    """Fail closed when an allocation is malformed, mismatched, or stale."""
    singular, _ = _studio_kind(kind)
    identity = _identity(identity, f"{singular} identity")
    version = _version(version)
    required = {
        "schema_version",
        "kind",
        "identity",
        "source_version",
        "source_scope",
        "source_revision_sha256",
        "source_content_sha256",
        "candidate_version",
        "occupied_versions_sha256",
        "observed_utc",
    }
    if set(allocation) != required:
        raise StudioVersionConflict("allocation-envelope-invalid")
    try:
        canonical_source_version = _version(allocation.get("source_version"))
    except (TypeError, ValueError) as error:
        raise StudioVersionConflict("allocation-binding-mismatch") from error
    if (
        allocation.get("schema_version") != STUDIO_VERSION_ALLOCATION_SCHEMA
        or allocation.get("kind") != singular
        or allocation.get("identity") != identity
        or allocation.get("source_version") != canonical_source_version
        or allocation.get("source_scope")
        not in {"studio-physical", "external-authenticated"}
        or allocation.get("candidate_version") != version
        or not isinstance(allocation.get("source_revision_sha256"), str)
        or re.fullmatch(
            r"[0-9a-f]{64}", str(allocation.get("source_revision_sha256"))
        )
        is None
        or not isinstance(allocation.get("source_content_sha256"), str)
        or re.fullmatch(
            r"[0-9a-f]{64}", str(allocation.get("source_content_sha256"))
        )
        is None
        or not isinstance(allocation.get("occupied_versions_sha256"), str)
        or re.fullmatch(
            r"[0-9a-f]{64}", str(allocation.get("occupied_versions_sha256"))
        )
        is None
        or not _valid_observed_utc(allocation.get("observed_utc"))
    ):
        raise StudioVersionConflict("allocation-binding-mismatch")
    try:
        current = allocate_studio_version(
            root,
            singular,
            identity,
            canonical_source_version,
            source_scope=str(allocation.get("source_scope") or ""),
            source_revision_sha256=(
                str(allocation.get("source_revision_sha256"))
                if allocation.get("source_scope") == "external-authenticated"
                else None
            ),
            source_content_sha256=(
                str(allocation.get("source_content_sha256"))
                if allocation.get("source_scope") == "external-authenticated"
                else None
            ),
        )
    except (TypeError, ValueError) as error:
        if isinstance(error, StudioVersionConflict):
            raise
        raise StudioVersionConflict("allocation-source-invalid") from error
    if (
        current["source_version"] != allocation.get("source_version")
        or current["candidate_version"] != version
        or current["occupied_versions_sha256"]
        != allocation.get("occupied_versions_sha256")
        or current["source_revision_sha256"]
        != allocation.get("source_revision_sha256")
        or current["source_content_sha256"]
        != allocation.get("source_content_sha256")
    ):
        raise StudioVersionConflict("allocation-stale")


def _unique(values: Sequence[str], field_name: str) -> tuple[str, ...]:
    rows = tuple(str(value).strip() for value in values if str(value).strip())
    if len(rows) != len(set(rows)):
        raise ValueError(f"duplicate {field_name}")
    return rows


@dataclass(frozen=True, slots=True)
class LifecycleDimensions:
    """Observed dimensions; no single boolean or label substitutes for another."""

    detected: bool = False
    packaged: bool = False
    installed: bool = False
    enabled: bool = False
    process_ready: bool = False
    connected: bool = False
    authenticated: bool = False
    admitted: bool = False
    bound: bool = False
    evidence: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        allowed = set(self.__dataclass_fields__) - {"evidence"}
        unknown = set(self.evidence) - allowed
        if unknown:
            raise ValueError(
                f"unknown lifecycle evidence dimensions: {sorted(unknown)}"
            )
        for name, value in asdict(self).items():
            if (
                name != "evidence"
                and value
                and not str(self.evidence.get(name, "")).strip()
            ):
                raise ValueError(f"true lifecycle dimension lacks evidence: {name}")

    @property
    def operational(self) -> bool:
        return all(
            (
                self.installed,
                self.enabled,
                self.process_ready,
                self.connected,
                self.authenticated,
                self.admitted,
                self.bound,
            )
        )


@dataclass(frozen=True, slots=True)
class EffectGrant:
    grant_id: str
    subject_id: str
    effects: tuple[str, ...]
    scope_roots: tuple[str, ...]
    approved_by: str
    evidence_refs: tuple[str, ...]
    expires_utc: str | None = None
    state: str = "candidate"

    def __post_init__(self) -> None:
        object.__setattr__(self, "grant_id", _identity(self.grant_id, "grant_id"))
        object.__setattr__(self, "subject_id", _identity(self.subject_id, "subject_id"))
        object.__setattr__(self, "effects", _unique(self.effects, "effects"))
        object.__setattr__(
            self, "scope_roots", _unique(self.scope_roots, "scope_roots")
        )
        object.__setattr__(
            self, "evidence_refs", _unique(self.evidence_refs, "evidence_refs")
        )
        if self.state not in LIFECYCLE_STATES:
            raise ValueError("invalid effect-grant state")
        if (
            not self.effects
            or not self.scope_roots
            or not self.approved_by
            or not self.evidence_refs
        ):
            raise ValueError(
                "effect grant requires effects, roots, approver, and evidence"
            )
        if self.expires_utc:
            try:
                datetime.fromisoformat(self.expires_utc.replace("Z", "+00:00"))
            except ValueError as error:
                raise ValueError("invalid effect-grant expiry") from error


@dataclass(frozen=True, slots=True)
class CapabilityBinding:
    binding_id: str
    subject_kind: str
    subject_id: str
    capability_id: str
    capability_version: str
    effect_grant_ids: tuple[str, ...]
    credential_namespace: str | None
    cost_policy: str
    egress_policy: str
    state: str
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in ("binding_id", "subject_id", "capability_id"):
            object.__setattr__(self, name, _identity(getattr(self, name), name))
        object.__setattr__(
            self, "capability_version", _version(self.capability_version)
        )
        object.__setattr__(
            self, "effect_grant_ids", _unique(self.effect_grant_ids, "effect_grant_ids")
        )
        object.__setattr__(
            self, "evidence_refs", _unique(self.evidence_refs, "evidence_refs")
        )
        if (
            self.subject_kind not in {"agent", "workflow", "skill"}
            or self.state not in LIFECYCLE_STATES
        ):
            raise ValueError("invalid capability binding kind or state")
        if (
            not self.effect_grant_ids
            or not self.cost_policy
            or not self.egress_policy
            or not self.evidence_refs
        ):
            raise ValueError(
                "binding requires grants, cost/egress policy, and evidence"
            )


@dataclass(frozen=True, slots=True)
class AgentSpec:
    agent_id: str
    version: str
    project_id: str
    owner: str
    harness_id: str
    instruction_sha256: str
    capability_binding_ids: tuple[str, ...]
    effect_grant_ids: tuple[str, ...]
    required_tests: tuple[str, ...]
    lifecycle: str = "draft"
    model: Mapping[str, object] = field(
        default_factory=lambda: {
            "provider": "deterministic",
            "family": "px-bounded-worker",
            "model_id": "px-bounded-worker",
            "max_output_tokens": 1024,
            "temperature": 0.0,
        }
    )
    tool_binding_ids: tuple[str, ...] = ()
    memory_binding_ids: tuple[str, ...] = ()
    handoff_agent_ids: tuple[str, ...] = ()
    input_schema: Mapping[str, object] = field(
        default_factory=lambda: {"type": "object", "additionalProperties": True}
    )
    output_schema: Mapping[str, object] = field(
        default_factory=lambda: {"type": "object", "additionalProperties": True}
    )

    def __post_init__(self) -> None:
        for name in ("agent_id", "project_id", "harness_id"):
            object.__setattr__(self, name, _identity(getattr(self, name), name))
        object.__setattr__(self, "version", _version(self.version))
        for name in (
            "capability_binding_ids",
            "effect_grant_ids",
            "required_tests",
            "tool_binding_ids",
            "memory_binding_ids",
            "handoff_agent_ids",
        ):
            object.__setattr__(self, name, _unique(getattr(self, name), name))
        if not re.fullmatch(r"[0-9a-f]{64}", self.instruction_sha256):
            raise ValueError("instruction_sha256 must be a SHA-256")
        if (
            self.lifecycle not in LIFECYCLE_STATES
            or not self.owner
            or not self.required_tests
        ):
            raise ValueError("agent spec requires owner, tests, and valid lifecycle")
        if not isinstance(self.model, Mapping):
            raise ValueError("agent model route must be an object")
        model = json.loads(canonical_bytes(dict(self.model)))
        provider = str(model.get("provider") or "").strip().lower()
        if provider not in {"deterministic", "vscode-lm", "pacify-local"}:
            raise ValueError("agent model provider is not admitted")
        model["provider"] = provider
        model["vendor"] = str(model.get("vendor") or "").strip()
        model["family"] = str(model.get("family") or "").strip()
        model["model_id"] = str(model.get("model_id") or "").strip()
        model["version"] = str(model.get("version") or "").strip()
        model["max_output_tokens"] = int(model.get("max_output_tokens", 1024))
        model["temperature"] = float(model.get("temperature", 0.0))
        if not model["family"] or not model["model_id"]:
            raise ValueError("agent model family and model ID are required")
        if provider in {"vscode-lm", "pacify-local"} and any(
            not model.get(field) or model.get(field) == "auto"
            for field in ("vendor", "family", "model_id", "version")
        ):
            raise ValueError("host model routes require exact vendor, family, model ID, and version")
        if provider == "pacify-local" and model.get("vendor") != "pacify-local":
            raise ValueError("pacify-local routes require vendor pacify-local")
        if not 1 <= model["max_output_tokens"] <= 32768:
            raise ValueError("agent max output tokens must be between 1 and 32768")
        if not 0.0 <= model["temperature"] <= 2.0:
            raise ValueError("agent temperature must be between 0 and 2")
        if self.harness_id == "harness:vscode-lm" and provider not in {
            "vscode-lm",
            "pacify-local",
        }:
            raise ValueError("VS Code LM harness requires a host-visible model provider")
        if provider in {"vscode-lm", "pacify-local"} and self.harness_id != "harness:vscode-lm":
            raise ValueError("host-visible model providers require the VS Code LM harness")
        object.__setattr__(self, "model", model)
        for name in ("input_schema", "output_schema"):
            value = getattr(self, name)
            if not isinstance(value, Mapping):
                raise ValueError(f"agent {name} must be an object")
            normalized = json.loads(canonical_bytes(dict(value)))
            if normalized.get("type") != "object":
                raise ValueError(f"agent {name} root type must be object")
            if len(canonical_bytes(normalized)) > 65536:
                raise ValueError(f"agent {name} exceeds 65536 bytes")
            object.__setattr__(self, name, normalized)


@dataclass(frozen=True, slots=True)
class WorkflowPort:
    name: str
    data_type: str
    required: bool = True

    def __post_init__(self) -> None:
        name = str(self.name).strip().lower()
        data_type = str(self.data_type).strip().lower()
        if not IDENTITY.fullmatch(name) or data_type not in PORT_TYPES:
            raise ValueError("invalid workflow port contract")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "data_type", data_type)


@dataclass(frozen=True, slots=True)
class WorkflowNode:
    node_id: str
    executor_binding_id: str
    inputs: tuple[WorkflowPort, ...]
    outputs: tuple[WorkflowPort, ...]
    effect_grant_ids: tuple[str, ...]
    failure_policy: str
    timeout_seconds: float
    retry_limit: int = 0
    approval_required: bool = False
    kind: str = "task"
    config: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "node_id", _identity(self.node_id, "node_id"))
        object.__setattr__(
            self,
            "executor_binding_id",
            _identity(self.executor_binding_id, "executor_binding_id"),
        )
        object.__setattr__(
            self, "effect_grant_ids", _unique(self.effect_grant_ids, "effect_grant_ids")
        )
        if (
            not self.inputs
            or not self.outputs
            or not self.effect_grant_ids
            or not self.failure_policy
        ):
            raise ValueError("workflow node lacks contract, grant, or failure policy")
        if not (0 < self.timeout_seconds <= 3600) or not (0 <= self.retry_limit <= 10):
            raise ValueError("workflow node timeout or retry bound is invalid")
        if self.failure_policy not in FAILURE_POLICIES:
            raise ValueError("unsupported workflow failure policy")
        kind = str(self.kind).strip().lower()
        if kind not in WORKFLOW_NODE_KINDS:
            raise ValueError("unsupported workflow node kind")
        if kind == "approval" and not self.approval_required:
            raise ValueError("approval workflow node must require approval")
        if not isinstance(self.config, Mapping):
            raise ValueError("workflow node config must be an object")
        try:
            normalized_config = json.loads(canonical_bytes(dict(self.config)))
        except (TypeError, ValueError) as error:
            raise ValueError("workflow node config must be canonical JSON") from error
        if len(canonical_bytes(normalized_config)) > 16384:
            raise ValueError("workflow node config exceeds 16384 bytes")
        if kind != "validation" and normalized_config:
            raise ValueError(
                f"{kind} workflow node config is closed and must be empty"
            )
        if kind == "validation":
            if self.failure_policy != "fail-closed":
                raise ValueError("validation workflow nodes must fail closed")
            if set(normalized_config) != {"checks"} or not isinstance(
                normalized_config.get("checks"), list
            ):
                raise ValueError(
                    "validation workflow node config requires only a checks array"
                )
            checks = normalized_config["checks"]
            if not checks or len(checks) > 64:
                raise ValueError(
                    "validation workflow node requires between 1 and 64 checks"
                )
            check_ids: set[str] = set()
            expected_operators = {
                "equals",
                "not-equals",
                "type",
                "greater-than-or-equal",
                "less-than-or-equal",
                "contains",
            }
            for check in checks:
                if not isinstance(check, Mapping):
                    raise ValueError("workflow validation check must be an object")
                required = {"id", "source", "port", "operator"}
                operator = str(check.get("operator", "")).strip().lower()
                allowed = required | ({"expected"} if operator in expected_operators else set())
                if set(check) != allowed:
                    raise ValueError("workflow validation check shape is invalid")
                check_id = _identity(str(check.get("id", "")), "validation check id")
                source = str(check.get("source", "")).strip().lower()
                port = _identity(str(check.get("port", "")), "validation check port")
                if check_id in check_ids:
                    raise ValueError("duplicate workflow validation check id")
                if source not in VALIDATION_SOURCES or operator not in VALIDATION_OPERATORS:
                    raise ValueError("unsupported workflow validation check")
                if operator == "type" and check.get("expected") not in PORT_TYPES:
                    raise ValueError("workflow validation type check is invalid")
                check_ids.add(check_id)
                check["id"] = check_id
                check["source"] = source
                check["port"] = port
                check["operator"] = operator
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "config", normalized_config)
        if len({port.name for port in self.inputs}) != len(self.inputs) or len(
            {port.name for port in self.outputs}
        ) != len(self.outputs):
            raise ValueError("duplicate workflow port")


@dataclass(frozen=True, slots=True)
class WorkflowEdge:
    source_node: str
    source_port: str
    target_node: str
    target_port: str
    condition: str = "always"

    def __post_init__(self) -> None:
        for name in ("source_node", "source_port", "target_node", "target_port"):
            object.__setattr__(self, name, _identity(getattr(self, name), name))
        condition = str(self.condition).strip().lower()
        if condition not in EDGE_CONDITIONS:
            raise ValueError("unsupported workflow edge condition")
        object.__setattr__(self, "condition", condition)


@dataclass(frozen=True, slots=True)
class WorkflowDefinition:
    workflow_id: str
    version: str
    owner: str
    nodes: tuple[WorkflowNode, ...]
    edges: tuple[WorkflowEdge, ...]
    lifecycle: str = "draft"

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "workflow_id", _identity(self.workflow_id, "workflow_id")
        )
        object.__setattr__(self, "version", _version(self.version))
        if self.lifecycle not in LIFECYCLE_STATES or not self.owner or not self.nodes:
            raise ValueError("workflow requires owner, nodes, and valid lifecycle")
        node_map = {node.node_id: node for node in self.nodes}
        if len(node_map) != len(self.nodes):
            raise ValueError("duplicate workflow node")
        adjacency = {node_id: [] for node_id in node_map}
        indegree = {node_id: 0 for node_id in node_map}
        driven_inputs: set[tuple[str, str]] = set()
        for edge in self.edges:
            if edge.source_node not in node_map or edge.target_node not in node_map:
                raise ValueError("workflow edge references missing node")
            outputs = {
                port.name: port.data_type for port in node_map[edge.source_node].outputs
            }
            inputs = {
                port.name: port.data_type for port in node_map[edge.target_node].inputs
            }
            if (
                edge.source_port not in outputs
                or edge.target_port not in inputs
                or outputs[edge.source_port] != inputs[edge.target_port]
            ):
                raise ValueError("workflow edge port contract mismatch")
            target_input = (edge.target_node, edge.target_port)
            if target_input in driven_inputs:
                raise ValueError("multiple workflow edges drive one input")
            driven_inputs.add(target_input)
            adjacency[edge.source_node].append(edge.target_node)
            indegree[edge.target_node] += 1
        for node in self.nodes:
            outgoing = [edge for edge in self.edges if edge.source_node == node.node_id]
            incoming = [edge for edge in self.edges if edge.target_node == node.node_id]
            if node.kind == "branch":
                output_types = {port.name: port.data_type for port in node.outputs}
                binary_ports = {
                    edge.source_port
                    for edge in outgoing
                    if edge.condition in {"source-truthy", "source-falsy"}
                }
                if not any(
                    output_types.get(port) == "boolean"
                    and {"source-truthy", "source-falsy"}
                    <= {
                        edge.condition
                        for edge in outgoing
                        if edge.source_port == port
                    }
                    for port in binary_ports
                ):
                    raise ValueError(
                        "branch workflow node requires truthy and falsy edges from one boolean output"
                    )
            if node.kind == "join" and len(incoming) < 2:
                raise ValueError("join workflow node requires at least two incoming edges")
        ready = [node for node, count in indegree.items() if count == 0]
        visited = 0
        while ready:
            current = ready.pop()
            visited += 1
            for target in adjacency[current]:
                indegree[target] -= 1
                if indegree[target] == 0:
                    ready.append(target)
        if visited != len(node_map):
            raise ValueError("workflow graph contains a cycle")


@dataclass(frozen=True, slots=True)
class SkillPackage:
    skill_id: str
    version: str
    owner: str
    triggers: tuple[str, ...]
    non_triggers: tuple[str, ...]
    permissions: tuple[str, ...]
    effects: tuple[str, ...]
    resources: tuple[str, ...]
    contracts: tuple[str, ...]
    tests: tuple[str, ...]
    provenance: Mapping[str, str]
    lifecycle: str = "draft"

    def __post_init__(self) -> None:
        object.__setattr__(self, "skill_id", _identity(self.skill_id, "skill_id"))
        object.__setattr__(self, "version", _version(self.version))
        for name in (
            "triggers",
            "non_triggers",
            "permissions",
            "effects",
            "resources",
            "contracts",
            "tests",
        ):
            object.__setattr__(self, name, _unique(getattr(self, name), name))
        if self.lifecycle not in LIFECYCLE_STATES or not all(
            (
                self.owner,
                self.triggers,
                self.non_triggers,
                self.permissions,
                self.resources,
                self.contracts,
                self.tests,
                self.provenance,
            )
        ):
            raise ValueError("skill package manifest is incomplete")


def record(model: object) -> dict[str, object]:
    value = asdict(model)
    return {
        "schema_version": f"px.{type(model).__name__.lower()}/1.0",
        "record": value,
        "sha256": digest(value),
    }


def write_versioned_record(
    root: Path,
    kind: str,
    identity: str,
    version: str,
    model: object,
    *,
    include_created: bool = False,
) -> Path | tuple[Path, bool]:
    root = root.resolve(strict=True)
    identity = _identity(identity, "record identity")
    version = _version(version)
    target = studio_revision_root(root, kind, identity) / version / "record.json"
    lock_path = studio_revision_lock(root, kind, identity)
    verify_safe_ancestors(root, target)
    with FileLock(lock_path, timeout_seconds=10):
        verify_safe_ancestors(root, target)
        value = record(model)
        normalized_value = json.loads(canonical_bytes(value))
        if target.parent.exists():
            if (
                not target.is_file()
                or target.is_symlink()
                or json.loads(
                    read_bounded_regular_file(
                        target,
                        MAX_REVISION_TREE_FILE_BYTES,
                        lambda: StudioVersionConflict("immutable-revision-differs"),
                    ).decode("utf-8")
                )
                != normalized_value
            ):
                raise StudioVersionConflict("immutable-revision-differs")
            return (target, False) if include_created else target
        revisions = target.parent.parent
        revisions.mkdir(parents=True, exist_ok=True)
        verify_safe_ancestors(root, target)
        prepared = revisions / f".{version}.{uuid4().hex}.record.prepared"
        claimed_revision = False
        try:
            prepared.write_text(
                json.dumps(value, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            try:
                target.parent.mkdir(exist_ok=False)
                claimed_revision = True
            except OSError as error:
                if target.parent.exists():
                    raise StudioVersionConflict("publication-collision") from error
                raise
            verify_safe_ancestors(root, target)
            os.replace(prepared, target)
        finally:
            prepared.unlink(missing_ok=True)
            if claimed_revision and target.parent.exists() and not target.exists():
                try:
                    target.parent.rmdir()
                except OSError:
                    pass
        return (target, True) if include_created else target
