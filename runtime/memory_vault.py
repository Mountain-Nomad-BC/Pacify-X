"""Append-only, project-scoped memory vault with human-readable notes and derived indexes."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Iterable

from .memory_fabric import (
    MemoryRecord,
    assign_shard_address,
    candidate_memories,
    simhash64,
)
from .file_lock import FileLock


CATEGORIES = {
    "fact": "Facts",
    "decision": "Decisions",
    "failure": "Failures",
    "pattern": "Patterns",
    "preference": "Preferences",
    "skill": "Skills",
    "architecture": "Architectures",
    "risk": "Risks",
    "assumption": "Assumptions",
    "lesson": "Lessons",
    "relationship": "Relationships",
    "procedure": "Procedures",
    "evidence": "Evidence",
    "constraint": "Constraints",
    "instruction": "Instructions",
    "event": "Events",
    "negative_knowledge": "NegativeKnowledge",
    "work_task": "WorkTasks",
    "scenario": "Scenarios",
    "project_doctrine": "ProjectDoctrine",
    "team_model": "TeamModels",
    "user_core": "UserCore",
    "agent_profile": "AgentProfiles",
    "skill_candidate": "SkillCandidates",
}
TRANSITIONS = {
    "candidate": {"validated", "disputed", "quarantined", "expired", "revoked"},
    "validated": {"certified", "candidate", "disputed", "expired", "revoked"},
    "certified": {
        "trusted",
        "validated",
        "disputed",
        "expired",
        "revoked",
        "superseded",
    },
    "trusted": {"validated", "disputed", "expired", "revoked", "superseded"},
    "disputed": {"candidate", "validated", "revoked", "superseded"},
    "quarantined": {"candidate", "revoked"},
    "expired": {"candidate", "revoked", "superseded"},
    "revoked": set(),
    "superseded": set(),
}
WORD = re.compile(r"[a-z0-9]+")
RECORD_NAME = re.compile(r"^record-(\d{6})\.json$")


def _json_default(value: object) -> object:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, tuple):
        return list(value)
    raise TypeError(type(value).__name__)


def _stable(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), default=_json_default
        ).encode()
    ).hexdigest()


def _slug(value: str) -> str:
    text = "-".join(WORD.findall(value.casefold()))[:80].strip("-") or "memory"
    if text.upper() in {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }:
        text = "memory-" + text
    return text


def _write_new(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(value)


def _record_payload(record: MemoryRecord) -> dict[str, object]:
    return asdict(record)


def _record_from_payload(value: dict[str, object]) -> MemoryRecord:
    value = {
        key: item
        for key, item in value.items()
        if key in MemoryRecord.__dataclass_fields__
    }
    return MemoryRecord(
        **{
            **value,
            "acl": tuple(value.get("acl", ())),
            "supersedes": tuple(value.get("supersedes", ())),
            "relationships": tuple(value.get("relationships", ())),
            "negative_matches": tuple(value.get("negative_matches", ())),
            "conflicts_with": tuple(value.get("conflicts_with", ())),
            "fixed_agent_ids": tuple(value.get("fixed_agent_ids", ())),
            "observed_at": datetime.fromisoformat(str(value["observed_at"])),
            "effective_at": datetime.fromisoformat(str(value["effective_at"])),
            "expires_at": datetime.fromisoformat(str(value["expires_at"]))
            if value.get("expires_at")
            else None,
        }
    )


def _hash_without(value: dict[str, object], field: str) -> str:
    return _stable({key: item for key, item in value.items() if key != field})


@dataclass(frozen=True, slots=True)
class VaultWrite:
    memory_id: str
    revision: int
    json_path: str
    markdown_path: str
    short_address: str
    address_bits: int
    integrity_sha256: str


@dataclass(frozen=True, slots=True)
class LifecycleDecision:
    memory_id: str
    previous: str
    current: str
    event_path: str
    evidence: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class IndexGeneration:
    generation: int
    manifest_path: str
    record_count: int
    source_tree_sha256: str
    previous_generations_preserved: bool


class MemoryVault:
    def __init__(
        self,
        root: Path,
        *,
        workspace_id: str,
        project_id: str,
        max_records_per_bucket: int = 1000,
    ) -> None:
        self.root = root.resolve()
        if not workspace_id or not project_id or max_records_per_bucket < 1:
            raise ValueError(
                "workspace, project, and positive bucket capacity are required"
            )
        self.workspace_id = workspace_id
        self.project_id = project_id
        self.max_records_per_bucket = max_records_per_bucket

    @property
    def knowledge_root(self) -> Path:
        return self.root / "Knowledge"

    def _all_record_paths(self) -> tuple[Path, ...]:
        return (
            tuple(sorted(self.knowledge_root.rglob("record-*.json")))
            if self.knowledge_root.is_dir()
            else ()
        )

    def records(self) -> tuple[MemoryRecord, ...]:
        values: list[MemoryRecord] = []
        previous_by_id: dict[str, str] = {}
        revision_by_id: dict[str, int] = {}
        lifecycle_hashes: dict[str, set[str]] = {}
        for path in self._all_record_paths():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as error:
                raise ValueError(
                    f"memory record integrity failure: {path.name}: {type(error).__name__}"
                ) from error
            if not isinstance(payload, dict):
                raise ValueError(
                    f"memory record integrity failure: {path.name}: record is not an object"
                )
            required_seals = {
                "previous_record_sha256",
                "record_sha256",
                "lifecycle_event_head_sha256",
            }
            if not required_seals.issubset(payload):
                raise ValueError(
                    f"memory record integrity failure: {path.name}: seal fields missing"
                )
            memory_id = str(payload.get("memory_id", ""))
            revision = payload.get("revision")
            if (
                not isinstance(revision, int)
                or isinstance(revision, bool)
                or revision != revision_by_id.get(memory_id, 0) + 1
            ):
                raise ValueError(
                    f"memory record integrity failure: {path.name}: revision chain invalid"
                )
            if payload["previous_record_sha256"] != previous_by_id.get(
                memory_id, "0" * 64
            ):
                raise ValueError(
                    f"memory record integrity failure: {path.name}: previous-record link mismatch"
                )
            if payload["record_sha256"] != _hash_without(payload, "record_sha256"):
                raise ValueError(
                    f"memory record integrity failure: {path.name}: record digest mismatch"
                )
            if memory_id not in lifecycle_hashes:
                lifecycle_hashes[memory_id] = {
                    str(item["event_sha256"])
                    for item in self._validate_lifecycle(memory_id)
                }
            if (
                payload["lifecycle_event_head_sha256"]
                not in lifecycle_hashes[memory_id]
            ):
                raise ValueError(
                    f"memory record integrity failure: {path.name}: lifecycle binding mismatch"
                )
            record = _record_from_payload(payload)
            errors = record.validation_errors()
            if errors:
                raise ValueError(
                    f"memory record integrity failure: {path.name}: {', '.join(errors)}"
                )
            values.append(record)
            previous_by_id[memory_id] = str(payload["record_sha256"])
            revision_by_id[memory_id] = revision
        return tuple(values)

    def latest_records(self) -> tuple[MemoryRecord, ...]:
        latest: dict[str, MemoryRecord] = {}
        for record in self.records():
            prior = latest.get(record.memory_id)
            if prior is None or record.revision > prior.revision:
                latest[record.memory_id] = record
        return tuple(latest[key] for key in sorted(latest))

    def _address(self, record: MemoryRecord, content: bytes):
        occupied = tuple(
            f"{item.title} {item.memory_id}" for item in self.latest_records()
        )
        minimum = 8
        while minimum <= 256:
            address = assign_shard_address(
                f"{record.title} {record.memory_id}",
                content,
                occupied,
                minimum_bits=minimum,
            )
            bucket = self.knowledge_root / CATEGORIES[record.memory_type]
            for component in address.bucket_path:
                bucket /= component
            count = self._verified_bucket_count(bucket) if bucket.is_dir() else 0
            if count < self.max_records_per_bucket:
                return address
            minimum += 4
        raise ValueError("memory namespace cannot allocate a bounded bucket")

    def _verified_bucket_count(self, bucket: Path) -> int:
        """Count only parseable, sealed, filename-consistent bucket records."""
        count = 0
        for path in sorted(bucket.glob("*/record-*.json")):
            match = RECORD_NAME.fullmatch(path.name)
            if match is None:
                raise ValueError(
                    f"memory bucket integrity failure: invalid record filename {path.name}"
                )
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                record = _record_from_payload(payload)
            except (
                OSError,
                UnicodeError,
                json.JSONDecodeError,
                KeyError,
                TypeError,
                ValueError,
            ) as error:
                raise ValueError(
                    f"memory bucket integrity failure: corrupt entry {path.name}"
                ) from error
            if record.revision != int(match.group(1)) or record.validation_errors():
                raise ValueError(
                    f"memory bucket integrity failure: invalid metadata {path.name}"
                )
            required = {
                "previous_record_sha256",
                "record_sha256",
                "lifecycle_event_head_sha256",
            }
            if not required <= set(payload) or payload[
                "record_sha256"
            ] != _hash_without(payload, "record_sha256"):
                raise ValueError(
                    f"memory bucket integrity failure: invalid seal {path.name}"
                )
            count += 1
        return count

    def append(self, record: MemoryRecord) -> VaultWrite:
        with FileLock(self.root / ".memory-control" / "vault.lock"):
            return self._append_locked(record)

    def _append_locked(self, record: MemoryRecord) -> VaultWrite:
        errors = record.validation_errors()
        if errors:
            raise ValueError("invalid memory record: " + ", ".join(errors))
        if (
            record.workspace_id != self.workspace_id
            or record.project_id != self.project_id
        ):
            raise ValueError("memory record is outside the vault namespace")
        prior = [item for item in self.records() if item.memory_id == record.memory_id]
        expected_revision = max((item.revision for item in prior), default=0) + 1
        if record.revision != expected_revision:
            raise ValueError(
                f"memory revision must be append-only revision {expected_revision}"
            )
        payload = _record_payload(record)
        canonical = (
            json.dumps(
                payload, sort_keys=True, separators=(",", ":"), default=_json_default
            )
            + "\n"
        ).encode()
        address = self._address(record, canonical)
        directory = self.knowledge_root / CATEGORIES[record.memory_type]
        for component in address.bucket_path:
            directory /= component
        directory /= f"{_slug(record.title)}--{address.short_address}"
        json_path = directory / f"record-{record.revision:06d}.json"
        markdown_path = directory / f"note-{record.revision:06d}.md"
        lifecycle_path = self._append_lifecycle(
            record.memory_id,
            "record-created" if record.revision == 1 else "record-revised",
            record.certification_status,
            (record.evidence_locator,),
        )
        lifecycle_event = json.loads(lifecycle_path.read_text(encoding="utf-8"))
        prior_payloads = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in self._all_record_paths()
            if json.loads(path.read_text(encoding="utf-8")).get("memory_id")
            == record.memory_id
        ]
        sealed = {
            **payload,
            "previous_record_sha256": str(prior_payloads[-1]["record_sha256"])
            if prior_payloads
            else "0" * 64,
            "lifecycle_event_head_sha256": lifecycle_event["event_sha256"],
        }
        sealed["record_sha256"] = _hash_without(sealed, "record_sha256")
        _write_new(
            json_path, json.dumps(sealed, indent=2, default=_json_default) + "\n"
        )
        links = "\n".join(f"- [[{link}]]" for link in record.relationships) or "- None"
        note = (
            f"---\nmemory_id: {record.memory_id}\nrevision: {record.revision}\n"
            f"project_id: {record.project_id}\ncertification_status: {record.certification_status}\n"
            f"retrieval_enabled: {str(record.retrieval_enabled).lower()}\n"
            f"source_sha256: {record.source_sha256}\nevidence_locator: {record.evidence_locator}\n"
            f"address: {address.short_address}\nintegrity_sha256: {address.integrity_sha256}\n---\n\n"
            f"# {record.title}\n\n{record.summary}\n\n## Relationships\n\n{links}\n"
        )
        _write_new(markdown_path, note)
        return VaultWrite(
            record.memory_id,
            record.revision,
            json_path.relative_to(self.root).as_posix(),
            markdown_path.relative_to(self.root).as_posix(),
            address.short_address,
            address.address_bits,
            address.integrity_sha256,
        )

    def _lifecycle_paths(self, memory_id: str) -> tuple[Path, ...]:
        directory = self.root / ".memory-control" / "lifecycle" / _slug(memory_id)
        return tuple(sorted(directory.glob("*.json"))) if directory.is_dir() else ()

    def _lifecycle_authority(self, memory_id: str) -> tuple[Path, Path]:
        root = self.root / ".memory-control" / "lifecycle-authority" / _slug(memory_id)
        return root / "head.json", root / "anchors"

    def _validate_lifecycle(self, memory_id: str) -> tuple[dict[str, object], ...]:
        paths = self._lifecycle_paths(memory_id)
        events: list[dict[str, object]] = []
        previous_hash = "0" * 64
        previous_state: str | None = None
        for sequence, path in enumerate(paths, start=1):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as error:
                raise ValueError(
                    f"memory lifecycle integrity failure: {path.name}: {type(error).__name__}"
                ) from error
            required = {
                "schema_version",
                "sequence",
                "memory_id",
                "event",
                "state",
                "evidence",
                "created_utc",
                "previous_event_sha256",
                "event_sha256",
            }
            if not isinstance(payload, dict) or set(payload) != required:
                raise ValueError(
                    f"memory lifecycle integrity failure: {path.name}: fields are not exact"
                )
            state = str(payload.get("state", ""))
            event = str(payload.get("event", ""))
            if (
                payload.get("sequence") != sequence
                or payload.get("memory_id") != memory_id
            ):
                raise ValueError(
                    f"memory lifecycle integrity failure: {path.name}: identity or sequence mismatch"
                )
            if state not in TRANSITIONS:
                raise ValueError(
                    f"memory lifecycle integrity failure: {path.name}: invalid lifecycle state"
                )
            if payload.get("previous_event_sha256") != previous_hash or payload.get(
                "event_sha256"
            ) != _hash_without(payload, "event_sha256"):
                raise ValueError(
                    f"memory lifecycle integrity failure: {path.name}: hash chain mismatch"
                )
            if (
                previous_state is not None
                and state != previous_state
                and state not in TRANSITIONS.get(previous_state, set())
            ):
                if event != "reinstated":
                    raise ValueError(
                        f"memory lifecycle integrity failure: {path.name}: transition is not allowed"
                    )
            if event == "reinstated" and (
                previous_state != "revoked" or not payload["evidence"]
            ):
                raise ValueError(
                    f"memory lifecycle integrity failure: {path.name}: reinstatement is not approved"
                )
            previous_hash = str(payload["event_sha256"])
            previous_state = state
            events.append(payload)
        if paths:
            head_path, anchors = self._lifecycle_authority(memory_id)
            try:
                head = json.loads(head_path.read_text(encoding="utf-8"))
                expected = {
                    "schema_version": "1.0",
                    "sequence": len(paths),
                    "event_sha256": previous_hash,
                }
                if (
                    head != expected
                    or not (
                        anchors / f"{len(paths):06d}-{previous_hash}.json"
                    ).is_file()
                ):
                    raise ValueError("head mismatch")
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
                raise ValueError(
                    "memory lifecycle integrity failure: protected head mismatch"
                ) from error
        return tuple(events)

    def _append_lifecycle(
        self, memory_id: str, event: str, state: str, evidence: Iterable[str]
    ) -> Path:
        events = self._validate_lifecycle(memory_id)
        paths = self._lifecycle_paths(memory_id)
        sequence = len(paths) + 1
        path = (
            self.root
            / ".memory-control"
            / "lifecycle"
            / _slug(memory_id)
            / f"{sequence:06d}-{event}.json"
        )
        payload = {
            "schema_version": "1.0",
            "sequence": sequence,
            "memory_id": memory_id,
            "event": event,
            "state": state,
            "evidence": sorted(set(map(str, evidence))),
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "previous_event_sha256": str(events[-1]["event_sha256"])
            if events
            else "0" * 64,
        }
        payload["event_sha256"] = _hash_without(payload, "event_sha256")
        _write_new(path, json.dumps(payload, indent=2) + "\n")
        head_path, anchors = self._lifecycle_authority(memory_id)
        anchors.mkdir(parents=True, exist_ok=True)
        head = {
            "schema_version": "1.0",
            "sequence": sequence,
            "event_sha256": payload["event_sha256"],
        }
        _write_new(
            anchors / f"{sequence:06d}-{payload['event_sha256']}.json",
            json.dumps(head, indent=2) + "\n",
        )
        head_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = head_path.with_name(f".{head_path.name}.{sequence:06d}.prepared")
        _write_new(temporary, json.dumps(head, indent=2) + "\n")
        os.replace(temporary, head_path)
        return path

    def lifecycle_state(self, memory_id: str) -> str:
        events = self._validate_lifecycle(memory_id)
        if not events:
            raise KeyError(memory_id)
        return str(events[-1]["state"])

    def inspect_record(self, memory_id: str) -> dict[str, object]:
        """Return one integrity-checked record with source, seal, and lifecycle lineage."""
        matches = [record for record in self.latest_records() if record.memory_id == memory_id]
        if len(matches) != 1:
            raise KeyError(memory_id)
        record = matches[0]
        payloads = []
        for path in self._all_record_paths():
            value = json.loads(path.read_text(encoding="utf-8"))
            if value.get("memory_id") == memory_id:
                payloads.append((int(value["revision"]), path, value))
        _, path, sealed = sorted(payloads)[-1]
        lifecycle = self._validate_lifecycle(memory_id)
        return {
            "schema_version": "px.canonical-memory-record/1.0",
            "authority": "canonical workspace memory vault",
            "memory_id": record.memory_id,
            "title": record.title,
            "summary": record.summary,
            "memory_type": record.memory_type,
            "project_id": record.project_id,
            "owner_id": record.owner_id,
            "revision": record.revision,
            "layer": record.layer,
            "visibility": record.visibility,
            "epistemic_status": record.epistemic_status,
            "confidence": record.confidence,
            "confidence_method": record.confidence_method,
            "certification_status": record.certification_status,
            "lifecycle_state": str(lifecycle[-1]["state"]),
            "retrieval_enabled": record.retrieval_enabled,
            "source_artifact": record.source_artifact,
            "source_sha256": record.source_sha256,
            "evidence_locator": record.evidence_locator,
            "source": {"path": record.source_artifact, "sha256": record.source_sha256},
            "evidence": [record.evidence_locator],
            "relationships": list(record.relationships),
            "supersedes": list(record.supersedes),
            "conflicts_with": list(record.conflicts_with),
            "record_sha256": sealed["record_sha256"],
            "previous_record_sha256": sealed["previous_record_sha256"],
            "lifecycle_event_head_sha256": sealed["lifecycle_event_head_sha256"],
            "lifecycle_head_sha256": sealed["lifecycle_event_head_sha256"],
            "record_relative": path.relative_to(self.root).as_posix(),
            "lifecycle": [
                {key: event[key] for key in ("sequence", "event", "state", "evidence", "created_utc", "previous_event_sha256", "event_sha256")}
                for event in lifecycle
            ],
        }

    def transition(
        self, memory_id: str, target: str, *, evidence: Iterable[str]
    ) -> LifecycleDecision:
        with FileLock(self.root / ".memory-control" / "vault.lock"):
            return self._transition_locked(memory_id, target, evidence=evidence)

    def _transition_locked(
        self, memory_id: str, target: str, *, evidence: Iterable[str]
    ) -> LifecycleDecision:
        previous = self.lifecycle_state(memory_id)
        evidence_ids = tuple(sorted(set(map(str, evidence))))
        if target not in TRANSITIONS.get(previous, set()):
            raise ValueError(
                f"invalid memory lifecycle transition: {previous} -> {target}"
            )
        if target in {"validated", "certified", "trusted"} and not evidence_ids:
            raise ValueError("promotion requires evidence")
        path = self._append_lifecycle(memory_id, "transition", target, evidence_ids)
        return LifecycleDecision(
            memory_id,
            previous,
            target,
            path.relative_to(self.root).as_posix(),
            evidence_ids,
        )

    def reinstate(
        self, memory_id: str, *, approval_evidence: Iterable[str]
    ) -> LifecycleDecision:
        """Create an explicit reviewed reinstatement event; never erase revocation."""
        with FileLock(self.root / ".memory-control" / "vault.lock"):
            previous = self.lifecycle_state(memory_id)
            evidence_ids = tuple(sorted(set(map(str, approval_evidence))))
            if previous != "revoked" or not evidence_ids:
                raise ValueError(
                    "reinstatement requires a revoked memory and approval evidence"
                )
            path = self._append_lifecycle(
                memory_id, "reinstated", "candidate", evidence_ids
            )
            return LifecycleDecision(
                memory_id,
                previous,
                "candidate",
                path.relative_to(self.root).as_posix(),
                evidence_ids,
            )

    def retrieval_records(
        self, *, actor_id: str, now: datetime | None = None
    ) -> tuple[MemoryRecord, ...]:
        current = now or datetime.now(timezone.utc)
        values = []
        latest = self.latest_records()
        # A correction is not authoritative until it is itself certified. This
        # prevents an unreviewed candidate from suppressing trusted memory.
        superseded = {
            memory_id
            for record in latest
            if self.lifecycle_state(record.memory_id) in {"certified", "trusted"}
            for memory_id in record.supersedes
        }
        for record in latest:
            state = self.lifecycle_state(record.memory_id)
            effective = replace(
                record,
                certification_status=state,
                retrieval_enabled=state in {"certified", "trusted"},
            )
            if record.memory_id in superseded or state not in {"certified", "trusted"}:
                continue
            if record.expires_at and record.expires_at <= current:
                continue
            if actor_id not in record.acl and self.project_id not in record.acl:
                continue
            values.append(effective)
        return tuple(values)

    def search(
        self, query: str, *, actor_id: str, limit: int = 5
    ) -> tuple[MemoryRecord, ...]:
        records = self.retrieval_records(actor_id=actor_id)
        ids = candidate_memories(
            query, records, project_id=self.project_id, actor_id=actor_id
        )
        by_id = {record.memory_id: record for record in records}
        query_terms = set(WORD.findall(query.casefold()))
        ranked = []
        for memory_id in ids:
            record = by_id[memory_id]
            terms = set(WORD.findall((record.title + " " + record.summary).casefold()))
            semantic = len(query_terms & terms) / max(1, len(query_terms | terms))
            graph = sum(
                link.casefold() in query.casefold() for link in record.relationships
            )
            ranked.append(
                (semantic + graph * 0.1, record.confidence, memory_id, record)
            )
        return tuple(
            item[-1]
            for item in sorted(ranked, key=lambda item: (-item[0], -item[1], item[2]))[
                :limit
            ]
        )

    def build_index(self) -> IndexGeneration:
        with FileLock(self.root / ".memory-control" / "vault.lock"):
            return self._build_index_locked()

    def _build_index_locked(self) -> IndexGeneration:
        generations = self.root / ".memory-control" / "index" / "generations"
        existing = (
            tuple(sorted(path for path in generations.glob("*") if path.is_dir()))
            if generations.is_dir()
            else ()
        )
        generation = len(existing) + 1
        directory = generations / f"{generation:06d}"
        directory.mkdir(parents=True, exist_ok=False)
        records = self.latest_records()
        entries = [
            {
                "memory_id": record.memory_id,
                "revision": record.revision,
                "source_sha256": record.source_sha256,
                "record_sha256": _stable(_record_payload(record)),
                "simhash64": f"{simhash64(record.title + ' ' + record.summary):016x}",
                "relationships": list(record.relationships),
            }
            for record in records
        ]
        _write_new(directory / "entries.json", json.dumps(entries, indent=2) + "\n")
        source_hash = _stable(entries)
        manifest = {
            "schema_version": "1.0",
            "generation": generation,
            "status": "complete",
            "record_count": len(entries),
            "source_tree_sha256": source_hash,
            "entries_sha256": hashlib.sha256(
                (directory / "entries.json").read_bytes()
            ).hexdigest(),
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "previous_generations_preserved": all(path.is_dir() for path in existing),
        }
        _write_new(directory / "manifest.json", json.dumps(manifest, indent=2) + "\n")
        return IndexGeneration(
            generation,
            (directory / "manifest.json").relative_to(self.root).as_posix(),
            len(entries),
            source_hash,
            bool(manifest["previous_generations_preserved"]),
        )

    def reconcile_indexes(self) -> dict[str, object]:
        generations = self.root / ".memory-control" / "index" / "generations"
        directories = (
            tuple(sorted(path for path in generations.glob("*") if path.is_dir()))
            if generations.is_dir()
            else ()
        )
        complete = []
        orphaned = []
        for directory in directories:
            manifest = directory / "manifest.json"
            entries = directory / "entries.json"
            if not manifest.is_file() or not entries.is_file():
                orphaned.append(directory.name)
                continue
            value = json.loads(manifest.read_text(encoding="utf-8"))
            if (
                value.get("status") != "complete"
                or value.get("entries_sha256")
                != hashlib.sha256(entries.read_bytes()).hexdigest()
            ):
                orphaned.append(directory.name)
            else:
                complete.append(directory.name)
        return {
            "complete_generations": tuple(complete),
            "orphan_generations": tuple(orphaned),
            "authoritative_generation": complete[-1] if complete else None,
            "action": "quarantine_orphans_after_review" if orphaned else "none",
            "hard_delete": False,
        }
