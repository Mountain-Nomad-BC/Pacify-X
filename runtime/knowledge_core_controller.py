"""Governed proposal, verification, approval, promotion, and rollback for knowledge."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Mapping, Sequence
from uuid import uuid4

from contextvars import ContextVar
from functools import wraps
import time
from .input_files import (
    contained_file,
    read_file_image,
    cooperative_deadline,
    check_deadline,
    relative_source_path,
)
from .archive_io import reject_path_links
from .bounded_walk import bounded_walk, WalkLimits
from .json_io import decode_json_object, bounded_json_text
from .numeric_inputs import (
    bounded_json_value,
    bounded_sequence,
    bounded_text,
    bounded_mapping,
    bounded_integer,
)

from .file_lock import FileLock
from .dependency_invalidation import (
    build_dependency_graph,
    compute_invalidation_cone,
    load_dependency_authority,
)
from .learning_promotion import (
    aggregate_operations,
    compare_revisions,
    decay_decision,
    extract_pattern,
    form_hypothesis,
    freeze_revision,
    measure_reuse,
    operation_evidence,
    promote_revision,
    research_validation,
    validate_learning_pipeline_state,
)
from .memory_intelligence import sanitize_capture
from .studio_authority import StudioAuthorityStore
from .studio_models import canonical_bytes, verify_safe_ancestors, write_json_atomic


IDENTITY = re.compile(r"^[a-z0-9][a-z0-9._:-]{1,127}$")
PROPOSAL_STATES = frozenset(
    {"candidate", "blocked", "verified", "approved", "promoted", "rejected"}
)
TRANSITIONS = {
    "candidate": frozenset({"blocked", "verified", "rejected"}),
    "blocked": frozenset({"rejected"}),
    "verified": frozenset({"approved", "rejected"}),
    "approved": frozenset({"promoted", "rejected"}),
    "promoted": frozenset(),
    "rejected": frozenset(),
}
LEARNING_STATES = frozenset(
    {
        "evidence",
        "pattern",
        "hypothesis",
        "trialing",
        "confidence-passed",
        "research-blocked",
        "secondary-trialing",
        "research-validated",
        "validation-blocked",
        "validated",
        "admitted",
        "canonical",
        "decayed",
    }
)
LEARNING_MINIMUM_TRIALS = 6
LEARNING_MAXIMUM_TRIALS = 200
LEARNING_MAXIMUM_HISTORY_BYTES = 32 * 1024 * 1024
LEARNING_TRANSITIONS = {
    "evidence": frozenset({"evidence", "pattern"}),
    "pattern": frozenset({"hypothesis"}),
    "hypothesis": frozenset({"trialing", "confidence-passed"}),
    "trialing": frozenset({"trialing", "confidence-passed"}),
    "confidence-passed": frozenset(
        {"research-blocked", "research-validated", "secondary-trialing"}
    ),
    "research-blocked": frozenset(
        {"research-blocked", "research-validated", "secondary-trialing"}
    ),
    "secondary-trialing": frozenset({"secondary-trialing", "research-validated"}),
    "research-validated": frozenset({"validated", "validation-blocked"}),
    "validation-blocked": frozenset({"validated", "validation-blocked"}),
    "validated": frozenset({"admitted"}),
    "admitted": frozenset({"canonical", "decayed"}),
    "canonical": frozenset({"canonical", "decayed"}),
    "decayed": frozenset({"canonical"}),
}


def _now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _hash(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


_ACTIVE_INPUTS = ContextVar("knowledge_input_budget", default=None)


def _input_scope(method):
    """Share bounded acquisition through one synchronous controller operation."""

    @wraps(method)
    def call(self, *args, **kwargs):
        active = _ACTIVE_INPUTS.get()
        if active is not None and active[0] is self:
            check_deadline(active[1]["deadline"])
            return method(self, *args, **kwargs)
        budget = {
            "deadline": cooperative_deadline(),
            "bytes": 0,
            "files": 0,
            "entries": 0,
        }
        token = _ACTIVE_INPUTS.set((self, budget))
        try:
            return method(self, *args, **kwargs)
        finally:
            _ACTIVE_INPUTS.reset(token)

    return call


def _bounded_input(value, *, maximum=2 * 1024 * 1024):
    bounded_json_value(value)
    bounded_json_text(value, max_bytes=maximum)
    # Keep canonical identity encoding unchanged; admission uses a conservative envelope.
    if len(canonical_bytes(value)) > maximum:
        raise ValueError("knowledge input exceeds its byte budget")
    return value


class _KnowledgeAcquisitionLimit(ValueError):
    """An operation budget cannot be converted into a partial successful result."""


class KnowledgeCoreController:
    """Project-local knowledge canon with explicit host approvals at every write."""

    @_input_scope
    def __init__(
        self,
        project_root: Path,
        *,
        policy_root: Path | None = None,
        read_only: bool = False,
    ) -> None:
        if type(read_only) is not bool:
            raise ValueError("knowledge read_only flag must be an actual boolean")
        reject_path_links(project_root)
        self.project_root = project_root.resolve(strict=True)
        if self.project_root == Path(self.project_root.anchor):
            raise ValueError("knowledge project root must be bounded")
        self.root = (
            self.project_root / ".engineering-bootstrap" / "studios" / "knowledge"
        )
        verify_safe_ancestors(self.project_root, self.root / "placeholder")
        reject_path_links(policy_root or self.project_root)
        governance_root = (policy_root or self.project_root).resolve(strict=True)
        policy_path = governance_root / "policies" / "learning-promotion.json"
        try:
            policy_path.relative_to(governance_root)
        except ValueError as error:
            raise PermissionError(
                "learning promotion policy escapes governance root"
            ) from error
        policy = decode_json_object(
            self._image(policy_path, maximum=65536, root=governance_root),
            max_bytes=65536,
            max_depth=16,
            max_nodes=10000,
        )
        if (
            not isinstance(policy, Mapping)
            or policy.get("schema_version") != "px.learning-promotion-policy/1.0"
            or policy.get("learning_direct_canonical_write") is not False
            or policy.get("minimum_trials_per_confidence_gate")
            != LEARNING_MINIMUM_TRIALS
            or policy.get("maximum_trials_per_confidence_gate")
            != LEARNING_MAXIMUM_TRIALS
            or policy.get("maximum_retained_pipeline_history_bytes")
            != LEARNING_MAXIMUM_HISTORY_BYTES
        ):
            raise PermissionError(
                "learning promotion policy and controller bounds differ"
            )
        for field in (
            "minimum_trials_per_confidence_gate",
            "maximum_trials_per_confidence_gate",
            "maximum_retained_pipeline_history_bytes",
        ):
            if type(policy.get(field)) is not int:
                raise ValueError("knowledge policy limits must be actual integers")
        self.learning_policy = dict(policy)
        if read_only:
            if self.root.exists() and (
                not self.root.is_dir() or self.root.is_symlink()
            ):
                raise PermissionError("knowledge control root is not a safe directory")
            self.authority = (
                StudioAuthorityStore.open_existing(self.project_root)
                if self.root.is_dir()
                else None
            )
        else:
            self.root.mkdir(parents=True, exist_ok=True)
            verify_safe_ancestors(self.project_root, self.root / "placeholder")
            self.authority = StudioAuthorityStore(self.project_root)
        self.lock = self.root / ".knowledge-control.lock"

    @staticmethod
    def _identity(value: object, field: str) -> str:
        text = bounded_text(value, field, maximum=128).lower()
        if not IDENTITY.fullmatch(text):
            raise ValueError(f"invalid knowledge {field}")
        return text

    @_input_scope
    def _budget(self):
        active = _ACTIVE_INPUTS.get()
        if active is None or active[0] is not self:
            raise RuntimeError("knowledge input budget is not active")
        check_deadline(active[1]["deadline"])
        return active[1]

    @_input_scope
    def _original_path(self, path: Path, *, root: Path | None = None) -> Path:
        base = self.project_root if root is None else root
        reject_path_links(base)
        reject_path_links(path)
        if not path.resolve().is_relative_to(base.resolve()):
            raise ValueError("knowledge path escapes its admitted root")
        relative = path.relative_to(base).as_posix()
        if relative != ".":
            relative_source_path(relative)
        if any(
            part.casefold() in {"quarantine", ".quarantine", "_quarantine"}
            for part in path.relative_to(base).parts
        ):
            raise ValueError("quarantine is outside knowledge acquisition")
        return path

    @_input_scope
    def _target(self, value: object) -> Path:
        relative = relative_source_path(value)
        return self._original_path(self.project_root / relative)

    @_input_scope
    def _reserve_images(self, admitted):
        budget = self._budget()
        files = len(admitted)
        size = sum(info.st_size for _, info in admitted)
        if (
            budget["files"] + files > 10000
            or budget["bytes"] + size > 256 * 1024 * 1024
        ):
            raise _KnowledgeAcquisitionLimit(
                "knowledge operation exceeds its aggregate image budget"
            )
        budget["files"] += files
        budget["bytes"] += size

    @_input_scope
    def _image(
        self, path: Path, *, maximum: int = 4 * 1024 * 1024, root: Path | None = None
    ):
        base = self.project_root if root is None else root
        path = self._original_path(path, root=base)
        path, info = contained_file(base, path.relative_to(base).as_posix())
        if info.st_size > maximum:
            raise ValueError(
                "knowledge image exceeds its byte budget before acquisition"
            )
        self._reserve_images([(path, info)])
        return read_file_image(
            path, info, limit=maximum, deadline=self._budget()["deadline"]
        )

    @_input_scope
    def _walk(
        self,
        path: Path,
        *,
        maximum_bytes=256 * 1024 * 1024,
        maximum_depth=32,
        exclude=None,
    ):
        self._original_path(path)
        budget = self._budget()
        remaining = 20000 - budget["entries"]
        if remaining <= 0:
            raise _KnowledgeAcquisitionLimit(
                "knowledge operation exceeds its traversal budget"
            )

        def excluded(relative):
            if any(
                part.casefold() in {"quarantine", ".quarantine", "_quarantine"}
                for part in relative.split("/")
            ):
                raise ValueError("quarantine is outside knowledge acquisition")
            return bool(exclude and exclude(relative))

        budget["entries"] += remaining
        result = bounded_walk(
            path,
            limits=WalkLimits(
                max_files=10000,
                max_depth=maximum_depth,
                max_bytes=maximum_bytes,
                max_entries=remaining,
                max_directories=min(10000, remaining),
                max_duration_seconds=max(
                    0.000001, self._budget()["deadline"] - time.monotonic()
                ),
            ),
            symlink_policy="reject",
            exclude=excluded,
        )
        budget["entries"] -= remaining - result.scanned_entries
        check_deadline(budget["deadline"])
        return result

    @_input_scope
    def _preflight(
        self, paths, *, file_limit=64 * 1024 * 1024, total_limit=256 * 1024 * 1024
    ):
        admitted = []
        total = 0
        for source in paths:
            self._original_path(source)
            path, info = contained_file(
                self.project_root, source.relative_to(self.project_root).as_posix()
            )
            total += info.st_size
            if info.st_size > file_limit:
                raise ValueError(
                    "knowledge file exceeds its byte budget before acquisition"
                )
            if len(admitted) >= 10000 or total > total_limit:
                raise _KnowledgeAcquisitionLimit(
                    "knowledge image inventory exceeds its byte or file budget before acquisition"
                )
            admitted.append((path, info))
        return admitted

    @_input_scope
    def _snapshot_inventory(self, target: Path):
        target = self._original_path(target)
        if target.is_file():
            paths = [target]
            kind = "file"
        else:
            inventory = self._walk(target)
            paths = sorted(
                (entry.path for entry in inventory.files),
                key=lambda path: path.relative_to(target).as_posix(),
            )
            kind = "tree"
        if not paths:
            raise ValueError("knowledge source file count is invalid")
        return target, kind, self._preflight(paths)

    @_input_scope
    def _snapshot_image(self, inventory):
        target, kind, admitted = inventory
        records = []
        for path, info in admitted:
            raw = read_file_image(
                path, info, limit=64 * 1024 * 1024, deadline=self._budget()["deadline"]
            )
            records.append(
                {
                    "path": path.name
                    if kind == "file"
                    else path.relative_to(target).as_posix(),
                    "bytes": len(raw),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                }
            )
        return {
            "kind": kind,
            "files": len(records),
            "bytes": sum(row["bytes"] for row in records),
            "content_sha256": _hash(records),
        }

    @_input_scope
    def _history_inventory(self, root: Path):
        directory = self._original_path(root / "events", root=self.root)
        if not directory.exists():
            return []
        inventory = self._walk(
            directory, maximum_bytes=LEARNING_MAXIMUM_HISTORY_BYTES, maximum_depth=1
        )
        paths = sorted(entry.path for entry in inventory.files)
        if (
            any(not re.fullmatch(r"[0-9]{8}\.json", path.name) for path in paths)
            or inventory.directory_count
        ):
            raise ValueError("unclassified knowledge history entry")
        return self._preflight(
            paths,
            file_limit=4 * 1024 * 1024,
            total_limit=LEARNING_MAXIMUM_HISTORY_BYTES,
        )

    @_input_scope
    def _history_paths(self, root: Path):
        return [path for path, _ in self._history_inventory(root)]

    @_input_scope
    def _references(self, values, label):
        supplied = bounded_sequence(values, label, maximum=10000)
        result = [
            bounded_text(value, label, maximum=4096, strip=False) for value in supplied
        ]
        if len(set(result)) != len(result):
            raise ValueError("duplicate knowledge reference")
        return result

    @staticmethod
    def _publication_input(state, actor, operation, previous):
        bounded_text(actor, "knowledge publication actor", maximum=256, strip=False)
        bounded_text(
            operation, "knowledge publication operation", maximum=128, strip=False
        )
        _bounded_input(state)
        if previous is not None:
            _bounded_input(previous)

    @staticmethod
    def _persisted_record_size(value):
        bounded_json_value(value)
        size = 1  # The existing writer terminates its ASCII JSON with a newline.
        for token in json.JSONEncoder(
            indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False
        ).iterencode(value):
            size += len(token)
            if size > 4 * 1024 * 1024:
                raise ValueError(
                    "knowledge persisted record exceeds its exact byte budget"
                )
        return size

    @_input_scope
    def _publish_pair(self, event_path, event, head_path, head):
        _bounded_input(event, maximum=4 * 1024 * 1024)
        _bounded_input(head, maximum=4 * 1024 * 1024)
        signed_event = self.authority.sign_receipt(event)
        signed_head = self.authority.sign_receipt(head)
        event_size = self._persisted_record_size(signed_event)
        self._persisted_record_size(signed_head)
        history = self._history_inventory(event_path.parent.parent)
        if (
            len(history) >= 10000
            or sum(info.st_size for _, info in history) + event_size
            > LEARNING_MAXIMUM_HISTORY_BYTES
        ):
            raise ValueError(
                "knowledge publication exceeds its retained history budget"
            )
        write_json_atomic(event_path, signed_event)
        write_json_atomic(head_path, signed_head)

    @_input_scope
    def _control_inventory(self, kind):
        prefixes = {
            "proposals": "proposal-",
            "learning": "pipeline-",
            "canonical": "record-",
        }
        prefix = prefixes[kind]
        directory = self._original_path(self.root / kind, root=self.root)
        if not directory.exists():
            return [], []

        def excluded(relative):
            parts = relative.split("/")
            if not re.fullmatch(re.escape(prefix) + r"[0-9a-f]{24}", parts[0]):
                raise ValueError("unclassified knowledge collection entry")
            if len(parts) == 1:
                return False
            if len(parts) == 2 and parts[1] in {"events", "revisions"}:
                child = self._original_path(directory / relative)
                if not child.is_dir():
                    raise ValueError("knowledge history component is not a directory")
                return True
            if len(parts) == 2 and parts[1] == "head.json":
                return False
            raise ValueError("unclassified knowledge collection entry")

        inventory = self._walk(directory, maximum_depth=2, exclude=excluded)
        roots = sorted(
            entry.path
            for entry in inventory.entries
            if entry.kind == "directory" and "/" not in entry.relative
        )
        heads = sorted(entry.path for entry in inventory.files)
        if any(path.name != "head.json" or path.parent not in roots for path in heads):
            raise ValueError(
                "knowledge collection head is not contained in an admitted record"
            )
        self._preflight(heads, file_limit=4 * 1024 * 1024)
        return roots, heads

    @_input_scope
    def _control_heads(self, kind):
        return self._control_inventory(kind)[1]

    @_input_scope
    def _control_roots(self, kind):
        return self._control_inventory(kind)[0]

    @_input_scope
    def _revision_paths(self, directory):
        self._original_path(directory, root=self.root)
        if not directory.exists():
            return []
        inventory = self._walk(directory, maximum_depth=1)
        paths = sorted(entry.path for entry in inventory.files)
        if inventory.directory_count or any(
            not re.fullmatch(r"[0-9a-f]{64}\.json", path.name) for path in paths
        ):
            raise ValueError("unclassified knowledge revision entry")
        self._preflight(paths, file_limit=4 * 1024 * 1024)
        return paths

    @staticmethod
    def _browse_input(query, limit):
        bounded_integer(limit, "knowledge browse limit", maximum=500)
        if type(query) is not str:
            raise ValueError("knowledge query must be bounded text")
        if query:
            bounded_text(query, "knowledge query", maximum=4096, strip=False)

    @_input_scope
    def _proposal_root(self, proposal_id: str) -> Path:
        proposal_id = self._identity(proposal_id, "proposal identity")
        component = f"proposal-{hashlib.sha256(proposal_id.encode()).hexdigest()[:24]}"
        path = self.root / "proposals" / component
        verify_safe_ancestors(self.project_root, path / "head.json")
        return path

    @_input_scope
    def _canonical_root(self, record_id: str) -> Path:
        record_id = self._identity(record_id, "record identity")
        component = f"record-{hashlib.sha256(record_id.encode()).hexdigest()[:24]}"
        path = self.root / "canonical" / component
        verify_safe_ancestors(self.project_root, path / "head.json")
        return path

    @_input_scope
    def _learning_root(self, pipeline_id: str) -> Path:
        pipeline_id = self._identity(pipeline_id, "learning pipeline identity")
        component = f"pipeline-{hashlib.sha256(pipeline_id.encode()).hexdigest()[:24]}"
        path = self.root / "learning" / component
        verify_safe_ancestors(self.project_root, path / "head.json")
        return path

    @_input_scope
    def _read_learning(self, pipeline_id: str) -> dict[str, object]:
        root = self._learning_root(pipeline_id)
        head_path = root / "head.json"
        if not head_path.is_file():
            raise FileNotFoundError("learning pipeline is missing")
        head = self._verify_signed(head_path)
        if (
            head.get("schema_version") != "px.learning-pipeline/1.0"
            or head.get("pipeline_id") != pipeline_id
            or head.get("state") not in LEARNING_STATES
            or not isinstance(head.get("sequence"), int)
            or head.get("authority_state") != "codex-host-retained"
            or head.get("learning_direct_write_allowed") is not False
        ):
            raise PermissionError("learning pipeline head contract is invalid")
        events = self._history_paths(root)
        if len(events) != int(head["sequence"]):
            raise PermissionError("learning pipeline history is incomplete")
        previous = None
        latest = None
        projected_states: list[dict[str, object]] = []
        for index, path in enumerate(events, start=1):
            event = self._verify_signed(path)
            unsigned = {
                key: value for key, value in event.items() if key != "event_sha256"
            }
            if (
                event.get("schema_version") != "px.learning-pipeline-event/1.0"
                or event.get("sequence") != index
                or path.name != f"{index:08d}.json"
                or event.get("previous_event_sha256") != previous
                or event.get("event_sha256") != _hash(unsigned)
                or not isinstance(event.get("state"), Mapping)
            ):
                raise PermissionError("learning pipeline event ancestry is invalid")
            try:
                validate_learning_pipeline_state(event["state"])
            except (TypeError, ValueError) as error:
                raise PermissionError(
                    f"learning pipeline typed hash graph is invalid: {error}"
                ) from error
            previous = event["event_sha256"]
            latest = event
            projected_states.append(dict(event["state"]))
        if (
            latest is None
            or {
                **dict(latest["state"]),
                "last_event_sha256": latest["event_sha256"],
            }
            != head
        ):
            raise PermissionError("learning pipeline head differs from history")
        revision_payload = {
            key: value
            for key, value in head.items()
            if key
            not in {
                "pipeline_revision_sha256",
                "last_event_sha256",
                "updated_utc",
            }
        }
        if head.get("pipeline_revision_sha256") != _hash(revision_payload):
            raise PermissionError("learning pipeline revision identity is invalid")
        admission_revision = None
        for index, state in enumerate(projected_states):
            if state.get("knowledge_proposal_id"):
                if index == 0:
                    raise PermissionError(
                        "learning candidate has no admission predecessor"
                    )
                admission_revision = projected_states[index - 1].get(
                    "pipeline_revision_sha256"
                )
                break
        self._validate_learning_candidate_link(head, admission_revision)
        return dict(head)

    @_input_scope
    def _publish_learning(
        self,
        state: Mapping[str, object],
        *,
        actor: str,
        operation: str,
        previous: Mapping[str, object] | None,
    ) -> dict[str, object]:
        self._publication_input(state, actor, operation, previous)
        if not actor.strip():
            raise ValueError("learning mutation requires an identified actor")
        _bounded_input(state)
        projected = {
            key: value
            for key, value in state.items()
            if key not in {"last_event_sha256", "pipeline_revision_sha256"}
        }
        revision_payload = {
            key: value for key, value in projected.items() if key != "updated_utc"
        }
        projected["pipeline_revision_sha256"] = _hash(revision_payload)
        try:
            validate_learning_pipeline_state(projected)
        except (TypeError, ValueError) as error:
            raise PermissionError(
                f"learning pipeline typed hash graph is invalid: {error}"
            ) from error
        self._validate_learning_candidate_link(
            projected,
            previous.get("pipeline_revision_sha256")
            if (
                previous
                and projected.get("knowledge_proposal_id")
                and not previous.get("knowledge_proposal_id")
            )
            else None,
        )
        if len(canonical_bytes(projected)) > 2 * 1024 * 1024:
            raise ValueError("learning pipeline state exceeds the 2 MiB bound")
        event = {
            "schema_version": "px.learning-pipeline-event/1.0",
            "pipeline_id": projected["pipeline_id"],
            "sequence": projected["sequence"],
            "operation": operation,
            "actor": actor,
            "previous_event_sha256": previous.get("last_event_sha256")
            if previous
            else None,
            "recorded_utc": projected["updated_utc"],
            "state": projected,
        }
        event_sha = _hash(event)
        event["event_sha256"] = event_sha
        head = {**projected, "last_event_sha256": event_sha}
        root = self._learning_root(str(projected["pipeline_id"]))
        event_path = root / "events" / f"{int(projected['sequence']):08d}.json"
        if event_path.exists():
            raise FileExistsError("learning pipeline event already exists")
        self._publish_pair(event_path, event, root / "head.json", head)
        return head

    @staticmethod
    def _validate_learning_content(
        value: object, label: str, *, maximum_bytes: int = 256 * 1024
    ) -> object:
        _bounded_input(value, maximum=maximum_bytes)
        if len(canonical_bytes(value)) > maximum_bytes:
            raise ValueError(f"{label} exceeds its bounded size")
        sanitized = sanitize_capture(json.dumps(value, ensure_ascii=False))
        if sanitized.secret_finding_codes:
            raise ValueError(f"{label} contains secret-like material")
        return value

    @_input_scope
    def _recover_learning_projection(self, root: Path) -> bool:
        """Repair one signed event-ahead-of-head learning publication only."""
        events = self._history_paths(root)
        if not events:
            raise PermissionError("learning pipeline recovery has no event history")
        projected: list[dict[str, object]] = []
        previous_hash: str | None = None
        for sequence, path in enumerate(events, start=1):
            event = self._verify_signed(path)
            unsigned = {
                key: value for key, value in event.items() if key != "event_sha256"
            }
            state = event.get("state")
            if not isinstance(state, Mapping):
                raise PermissionError("learning pipeline trailing state is invalid")
            revision_payload = {
                key: value
                for key, value in state.items()
                if key
                not in {
                    "pipeline_revision_sha256",
                    "last_event_sha256",
                    "updated_utc",
                }
            }
            if (
                event.get("schema_version") != "px.learning-pipeline-event/1.0"
                or event.get("sequence") != sequence
                or path.name != f"{sequence:08d}.json"
                or event.get("previous_event_sha256") != previous_hash
                or event.get("event_sha256") != _hash(unsigned)
                or event.get("pipeline_id") != state.get("pipeline_id")
                or state.get("sequence") != sequence
                or state.get("state") not in LEARNING_STATES
                or state.get("authority_state") != "codex-host-retained"
                or state.get("learning_direct_write_allowed") is not False
                or state.get("pipeline_revision_sha256") != _hash(revision_payload)
            ):
                raise PermissionError("learning pipeline trailing event is invalid")
            try:
                validate_learning_pipeline_state(state)
            except (TypeError, ValueError) as error:
                raise PermissionError(
                    f"learning pipeline typed hash graph is invalid: {error}"
                ) from error
            if sequence == 1:
                if state.get("state") != "evidence" or previous_hash is not None:
                    raise PermissionError("learning pipeline initial event is invalid")
                if self._learning_root(str(state.get("pipeline_id") or "")) != root:
                    raise PermissionError(
                        "learning pipeline directory identity is invalid"
                    )
            else:
                prior_state = str(projected[-1]["state"])
                if state.get("state") not in LEARNING_TRANSITIONS[prior_state]:
                    raise PermissionError(
                        "learning pipeline trailing transition is invalid"
                    )
            previous_hash = str(event["event_sha256"])
            projected.append({**dict(state), "last_event_sha256": previous_hash})
        admission_revision = None
        for index, state in enumerate(projected):
            if state.get("knowledge_proposal_id"):
                if index == 0:
                    raise PermissionError(
                        "learning candidate has no admission predecessor"
                    )
                admission_revision = projected[index - 1].get(
                    "pipeline_revision_sha256"
                )
                break
        self._validate_learning_candidate_link(projected[-1], admission_revision)
        head_path = root / "head.json"
        if head_path.is_file():
            head = self._verify_signed(head_path)
            sequence = int(head.get("sequence", 0))
            if sequence == len(projected):
                if head != projected[-1]:
                    raise PermissionError("learning pipeline head differs from history")
                return False
            if sequence != len(projected) - 1 or head != projected[-2]:
                raise PermissionError("learning pipeline divergence exceeds one event")
        elif len(projected) != 1:
            raise PermissionError("missing learning head exceeds one initial event")
        write_json_atomic(head_path, self.authority.sign_receipt(projected[-1]))
        return True

    @_input_scope
    def _validate_learning_candidate_link(
        self,
        state: Mapping[str, object],
        admission_revision_sha256: object,
    ) -> None:
        proposal_id = state.get("knowledge_proposal_id")
        candidate_sha256 = state.get("knowledge_candidate_sha256")
        if proposal_id is None and candidate_sha256 is None:
            return
        if not proposal_id or not re.fullmatch(
            r"[0-9a-f]{64}", str(candidate_sha256 or "")
        ):
            raise PermissionError("learning knowledge candidate link is incomplete")
        proposal = self._read(str(proposal_id))
        candidate = proposal.get("candidate")
        learning = (
            candidate.get("_px_learning") if isinstance(candidate, Mapping) else None
        )
        if not isinstance(learning, Mapping):
            raise PermissionError(
                "learning knowledge candidate role binding is invalid"
            )
        if admission_revision_sha256 is None:
            admission_revision_sha256 = learning.get("pipeline_revision_sha256")
        if not re.fullmatch(r"[0-9a-f]{64}", str(admission_revision_sha256 or "")):
            raise PermissionError("learning candidate admission revision is invalid")
        selected = state.get("selected_revision")
        decision = state.get("promotion_decision")
        expected = {
            "pipeline_id": state.get("pipeline_id"),
            "pipeline_revision_sha256": admission_revision_sha256,
            "selected_revision_sha256": selected.get("revision_sha256")
            if isinstance(selected, Mapping)
            else None,
            "promotion_decision_sha256": decision.get("record_sha256")
            if isinstance(decision, Mapping)
            else None,
            "canonical_corpus_sha256": decision.get("canonical_corpus_sha256")
            if isinstance(decision, Mapping)
            else None,
            "direct_write_allowed": False,
        }
        if (
            proposal.get("candidate_sha256") != candidate_sha256
            or dict(learning) != expected
        ):
            raise PermissionError(
                "learning knowledge candidate role binding is invalid"
            )

    @_input_scope
    def _verify_signed(self, path: Path) -> dict[str, object]:
        if self.authority is None:
            raise PermissionError("knowledge authority has not been initialized")
        self._original_path(path, root=self.root)
        raw = decode_json_object(
            self._image(path), max_bytes=4 * 1024 * 1024, max_depth=32, max_nodes=100000
        )
        if not isinstance(raw, Mapping):
            raise PermissionError("knowledge control record is not an object")
        return self.authority.verify_receipt(raw)

    @_input_scope
    def _read(self, proposal_id: str) -> dict[str, object]:
        root = self._proposal_root(proposal_id)
        head_path = root / "head.json"
        if not head_path.is_file():
            raise FileNotFoundError("knowledge proposal is missing")
        head = self._verify_signed(head_path)
        if (
            head.get("schema_version") != "px.knowledge-proposal/1.0"
            or head.get("proposal_id") != proposal_id
            or head.get("state") not in PROPOSAL_STATES
            or not isinstance(head.get("sequence"), int)
            or not isinstance(head.get("candidate"), Mapping)
            or head.get("authority_state") != "codex-host-retained"
        ):
            raise PermissionError("knowledge proposal head contract is invalid")
        events = self._history_paths(root)
        if len(events) != int(head["sequence"]):
            raise PermissionError("knowledge proposal history is incomplete")
        previous = None
        latest = None
        for index, path in enumerate(events, start=1):
            event = self._verify_signed(path)
            unsigned = {
                key: value for key, value in event.items() if key != "event_sha256"
            }
            if (
                event.get("sequence") != index
                or event.get("previous_event_sha256") != previous
                or event.get("event_sha256") != _hash(unsigned)
            ):
                raise PermissionError("knowledge proposal event ancestry is invalid")
            previous = event["event_sha256"]
            latest = event
        if (
            latest is None
            or {
                **dict(latest["state"]),
                "last_event_sha256": latest["event_sha256"],
            }
            != head
        ):
            raise PermissionError("knowledge proposal head differs from history")
        return dict(head)

    @_input_scope
    def _publish(
        self,
        state: Mapping[str, object],
        *,
        actor: str,
        operation: str,
        previous: Mapping[str, object] | None,
    ) -> dict[str, object]:
        self._publication_input(state, actor, operation, previous)
        if not actor.strip():
            raise ValueError("knowledge mutation requires an identified actor")
        root = self._proposal_root(str(state["proposal_id"]))
        _bounded_input(state)
        projected = {
            key: value for key, value in state.items() if key != "last_event_sha256"
        }
        event = {
            "schema_version": "px.knowledge-proposal-event/1.0",
            "proposal_id": state["proposal_id"],
            "sequence": state["sequence"],
            "operation": operation,
            "actor": actor,
            "previous_event_sha256": previous.get("last_event_sha256")
            if previous
            else None,
            "recorded_utc": state["updated_utc"],
            "state": projected,
        }
        event_sha = _hash(event)
        event["event_sha256"] = event_sha
        head = {**dict(state), "last_event_sha256": event_sha}
        event_path = root / "events" / f"{int(state['sequence']):08d}.json"
        if event_path.exists():
            raise FileExistsError("knowledge proposal event already exists")
        self._publish_pair(event_path, event, root / "head.json", head)
        return head

    @_input_scope
    def _recover_proposal_projection(self, root: Path) -> bool:
        """Repair exactly one authenticated event-ahead-of-head publication."""
        events = self._history_paths(root)
        if not events:
            raise PermissionError("knowledge proposal recovery has no event history")
        projected: list[dict[str, object]] = []
        previous_hash: str | None = None
        for sequence, path in enumerate(events, start=1):
            event = self._verify_signed(path)
            unsigned = {
                key: value for key, value in event.items() if key != "event_sha256"
            }
            state = event.get("state")
            if (
                event.get("schema_version") != "px.knowledge-proposal-event/1.0"
                or event.get("sequence") != sequence
                or path.name != f"{sequence:08d}.json"
                or event.get("previous_event_sha256") != previous_hash
                or event.get("event_sha256") != _hash(unsigned)
                or not isinstance(state, Mapping)
                or state.get("sequence") != sequence
                or state.get("state") not in PROPOSAL_STATES
            ):
                raise PermissionError("knowledge proposal trailing event is invalid")
            if sequence == 1:
                if state.get("state") != "candidate" or previous_hash is not None:
                    raise PermissionError("knowledge proposal initial event is invalid")
            elif state.get("state") not in TRANSITIONS[str(projected[-1]["state"])]:
                raise PermissionError(
                    "knowledge proposal trailing transition is invalid"
                )
            previous_hash = str(event["event_sha256"])
            projected.append({**dict(state), "last_event_sha256": previous_hash})
        head_path = root / "head.json"
        if head_path.is_file():
            head = self._verify_signed(head_path)
            sequence = int(head.get("sequence", 0))
            if sequence == len(projected):
                if head != projected[-1]:
                    raise PermissionError(
                        "knowledge proposal head differs from history"
                    )
                return False
            if sequence != len(projected) - 1 or head != projected[-2]:
                raise PermissionError("knowledge proposal divergence exceeds one event")
        elif len(projected) != 1:
            raise PermissionError("missing knowledge head exceeds one initial event")
        write_json_atomic(head_path, self.authority.sign_receipt(projected[-1]))
        return True

    @_input_scope
    def _sources(self) -> dict[str, Mapping[str, object]]:
        path = self._target("registry/knowledge_sources.json")
        if not path.exists():
            return {}
        payload = decode_json_object(
            self._image(path, maximum=1024 * 1024),
            max_bytes=1024 * 1024,
            max_depth=32,
            max_nodes=100000,
        )
        rows = bounded_sequence(
            payload.get("knowledge_sources"), "knowledge sources", maximum=10000
        )
        result = {}
        locations = set()
        for row in rows:
            bounded_mapping(row, "knowledge source", maximum=64)
            identifier = bounded_text(
                row.get("id"), "knowledge source identity", maximum=128, strip=False
            )
            location = relative_source_path(row.get("location"))
            bounded_text(row.get("status"), "knowledge source status", maximum=128)
            bounded_text(row.get("kind"), "knowledge source kind", maximum=128)
            if identifier in result or location.casefold() in locations:
                raise ValueError("duplicate knowledge source identity or locator")
            result[identifier] = row
            locations.add(location.casefold())
        return result

    @_input_scope
    def _source_errors(self, source_ids: Sequence[str]) -> list[str]:
        _, errors = self._source_snapshots(source_ids)
        return errors

    @_input_scope
    def _path_snapshot(self, target: Path) -> dict[str, object]:
        inventory = self._snapshot_inventory(target)
        self._reserve_images(inventory[2])
        return self._snapshot_image(inventory)

    @_input_scope
    def _source_snapshots(
        self, source_ids: Sequence[str]
    ) -> tuple[list[dict[str, object]], list[str]]:
        source_ids = self._references(source_ids, "knowledge source identities")
        declared = self._sources()
        plans = []
        errors = []
        for source_id in source_ids:
            row = declared.get(source_id)
            if row is None:
                errors.append(f"source_not_declared:{source_id}")
                continue
            if row.get("status") != "active":
                errors.append(f"source_not_eligible:{source_id}:{row.get('status')}")
                continue
            try:
                target = self._target(row["location"])
                inventory = self._snapshot_inventory(target)
            except _KnowledgeAcquisitionLimit:
                raise
            except (OSError, ValueError):
                errors.append(f"source_unavailable:{source_id}")
                continue
            plans.append((source_id, row, inventory))
        self._reserve_images(
            [item for _, _, inventory in plans for item in inventory[2]]
        )
        snapshots = []
        for source_id, row, inventory in plans:
            try:
                identity = self._snapshot_image(inventory)
            except _KnowledgeAcquisitionLimit:
                raise
            except (OSError, ValueError):
                errors.append(f"source_unavailable:{source_id}")
                continue
            snapshots.append(
                {
                    "source_id": source_id,
                    "status": row.get("status"),
                    "kind": row.get("kind"),
                    "location": row["location"],
                    **identity,
                }
            )
        return snapshots, errors

    @_input_scope
    def _evidence_snapshots(
        self, evidence_refs: Sequence[str]
    ) -> tuple[list[dict[str, object]], list[str]]:
        references = self._references(evidence_refs, "knowledge evidence references")
        plans = []
        errors = []
        for reference in references:
            if re.fullmatch(r"sha256:[0-9a-f]{64}", reference):
                plans.append((reference, None, None))
                continue
            match = re.fullmatch(r"([^#]+)#sha256=([0-9a-f]{64})", reference)
            if not match:
                errors.append(f"evidence_unresolved:{reference}")
                continue
            try:
                target = self._target(match.group(1))
                admitted = self._preflight([target])
            except _KnowledgeAcquisitionLimit:
                raise
            except (OSError, ValueError):
                errors.append(f"evidence_unavailable:{reference}")
                continue
            plans.append((reference, admitted[0], match.group(2)))
        self._reserve_images([image for _, image, _ in plans if image is not None])
        snapshots = []
        for reference, image, expected in plans:
            if image is None:
                snapshots.append(
                    {
                        "reference": reference,
                        "kind": "content-hash",
                        "sha256": reference[7:],
                    }
                )
                continue
            target, info = image
            try:
                raw = read_file_image(
                    target,
                    info,
                    limit=64 * 1024 * 1024,
                    deadline=self._budget()["deadline"],
                )
            except _KnowledgeAcquisitionLimit:
                raise
            except (OSError, ValueError):
                errors.append(f"evidence_unavailable:{reference}")
                continue
            actual = hashlib.sha256(raw).hexdigest()
            if actual != expected:
                errors.append(f"evidence_hash_mismatch:{reference}")
                continue
            snapshots.append(
                {
                    "reference": reference,
                    "kind": "project-file",
                    "path": target.relative_to(self.project_root).as_posix(),
                    "bytes": len(raw),
                    "sha256": actual,
                }
            )
        return snapshots, errors

    @_input_scope
    def _dependency_snapshot(
        self, expected: Mapping[str, str]
    ) -> tuple[dict[str, str], list[str]]:
        if type(expected) is not dict or len(expected) > 10000:
            raise ValueError("knowledge dependencies must be a bounded mapping")
        bounded_json_value(expected)
        plans = []
        errors = []
        for supplied_path, supplied_sha in sorted(expected.items()):
            try:
                target = self._target(supplied_path)
                if type(supplied_sha) is not str or not re.fullmatch(
                    r"[0-9a-f]{64}", supplied_sha
                ):
                    raise ValueError("invalid dependency digest")
                inventory = self._snapshot_inventory(target)
            except _KnowledgeAcquisitionLimit:
                raise
            except (OSError, ValueError):
                errors.append(f"dependency_invalid:{supplied_path}")
                continue
            plans.append((supplied_path, supplied_sha, inventory))
        self._reserve_images(
            [item for _, _, inventory in plans for item in inventory[2]]
        )
        current = {}
        for supplied_path, supplied_sha, inventory in plans:
            try:
                identity = self._snapshot_image(inventory)
            except _KnowledgeAcquisitionLimit:
                raise
            except (OSError, ValueError):
                errors.append(f"dependency_unavailable:{supplied_path}")
                continue
            current[supplied_path] = identity["content_sha256"]
            if current[supplied_path] != supplied_sha:
                errors.append(f"dependency_hash_mismatch:{supplied_path}")
        return current, errors

    @_input_scope
    def _transition_learning(
        self,
        pipeline_id: str,
        *,
        allowed_states: Sequence[str],
        target: str,
        actor: str,
        approved: bool,
        operation: str,
        updates: Mapping[str, object],
        expected_revision_sha256: str | None = None,
    ) -> dict[str, object]:
        if not approved:
            raise PermissionError("learning transition requires explicit host approval")
        if target not in LEARNING_STATES:
            raise ValueError("learning target state is invalid")
        with FileLock(self.lock, timeout_seconds=10):
            current = self._read_learning(pipeline_id)
            if current["state"] not in set(allowed_states):
                raise ValueError(
                    f"illegal learning transition: {current['state']} -> {target}"
                )
            if target not in LEARNING_TRANSITIONS[str(current["state"])]:
                raise ValueError(
                    f"unregistered learning transition: {current['state']} -> {target}"
                )
            if (
                expected_revision_sha256
                and current.get("pipeline_revision_sha256") != expected_revision_sha256
            ):
                raise PermissionError("learning pipeline changed during the operation")
            next_state = {
                **current,
                **dict(updates),
                "state": target,
                "sequence": int(current["sequence"]) + 1,
                "updated_utc": _now(),
                "learning_direct_write_allowed": False,
            }
            return self._publish_learning(
                next_state,
                actor=actor,
                operation=operation,
                previous=current,
            )

    @_input_scope
    def observe_experience(
        self,
        *,
        pipeline_id: str | None,
        operation_id: str,
        task_class: str,
        outcome: str,
        measurements: Mapping[str, object],
        capability_ids: Sequence[str],
        environment_sha256: str,
        source_ids: Sequence[str],
        evidence_refs: Sequence[str],
        approved: bool,
        observed_by: str,
    ) -> dict[str, object]:
        if not approved:
            raise PermissionError("experience capture requires explicit host approval")
        sources = sorted(self._references(source_ids, "knowledge source identities"))
        references = sorted(
            self._references(evidence_refs, "knowledge evidence references")
        )
        if not sources or not references:
            raise ValueError(
                "experience capture requires declared sources and evidence"
            )
        bounded_mapping(measurements, "knowledge measurements", maximum=256)
        _bounded_input(measurements, maximum=64 * 1024)
        capability_ids = self._references(
            capability_ids, "knowledge capability identities"
        )
        self._validate_learning_content(
            {
                "operation_id": operation_id,
                "task_class": task_class,
                "outcome": outcome,
                "measurements": dict(measurements),
                "capability_ids": list(capability_ids),
            },
            "experience observation",
            maximum_bytes=64 * 1024,
        )
        _, source_errors = self._source_snapshots(sources)
        evidence_snapshots, evidence_errors = self._evidence_snapshots(references)
        if source_errors or evidence_errors:
            raise PermissionError(
                "experience provenance is unresolved: "
                + ", ".join(source_errors + evidence_errors)
            )
        evidence = operation_evidence(
            operation_id=operation_id,
            task_class=task_class,
            outcome=outcome,
            measurements={str(key): value for key, value in measurements.items()},
            capability_ids=capability_ids,
            environment_sha256=environment_sha256,
            source_refs=references,
        )
        if pipeline_id:
            current = self._read_learning(
                self._identity(pipeline_id, "learning pipeline identity")
            )
            if current["state"] != "evidence":
                raise ValueError(
                    "evidence may only be appended before pattern extraction"
                )
            if list(current.get("source_ids") or ()) != sources:
                raise PermissionError(
                    "learning source scope cannot change after capture"
                )
            records = list(current.get("operation_evidence") or ())
            if any(
                item.get("record_sha256") == evidence["record_sha256"]
                for item in records
                if isinstance(item, Mapping)
            ):
                raise ValueError("duplicate operation evidence is not admitted")
            records.append(evidence)
            return self._transition_learning(
                str(current["pipeline_id"]),
                allowed_states=("evidence",),
                target="evidence",
                actor=observed_by,
                approved=True,
                operation="observe.append",
                updates={"operation_evidence": records},
                expected_revision_sha256=str(current["pipeline_revision_sha256"]),
            )
        pipeline_id = f"learning:{uuid4().hex}"
        timestamp = _now()
        state = {
            "schema_version": "px.learning-pipeline/1.0",
            "pipeline_id": pipeline_id,
            "state": "evidence",
            "sequence": 1,
            "created_utc": timestamp,
            "updated_utc": timestamp,
            "source_ids": sources,
            "operation_evidence": [evidence],
            "aggregation": None,
            "pattern": None,
            "hypothesis": None,
            "incumbent_revision": None,
            "challenger_revision": None,
            "trials": [],
            "comparison": None,
            "research": None,
            "secondary_revision": None,
            "secondary_trials": [],
            "secondary_comparison": None,
            "selected_revision": None,
            "final_validation": None,
            "promotion_decision": None,
            "knowledge_proposal_id": None,
            "reuse_measurements": [],
            "decay_decision": None,
            "learning_direct_write_allowed": False,
            "canonical_writes_performed": False,
            "authority_state": "codex-host-retained",
            "last_event_sha256": "0" * 64,
        }
        self._publication_input(state, observed_by, "observe", None)
        with FileLock(self.lock, timeout_seconds=10):
            root = self._learning_root(pipeline_id)
            root.mkdir(parents=True, exist_ok=False)
            (root / "events").mkdir()
            return self._publish_learning(
                state, actor=observed_by, operation="observe", previous=None
            )

    @_input_scope
    def extract_learning_pattern(
        self,
        pipeline_id: str,
        *,
        metric: str,
        higher_is_better: bool,
        interpretation: str,
        applicability: Sequence[str],
        approved: bool,
        extracted_by: str,
    ) -> dict[str, object]:
        current = self._read_learning(pipeline_id)
        self._validate_learning_content(
            {"interpretation": interpretation, "applicability": list(applicability)},
            "pattern interpretation",
            maximum_bytes=64 * 1024,
        )
        records = [
            item
            for item in current.get("operation_evidence", [])
            if isinstance(item, Mapping)
        ]
        aggregation = aggregate_operations(
            records, metric=metric, higher_is_better=higher_is_better
        )
        pattern = extract_pattern(
            aggregation=aggregation,
            interpretation=interpretation,
            applicability=applicability,
        )
        return self._transition_learning(
            pipeline_id,
            allowed_states=("evidence",),
            target="pattern",
            actor=extracted_by,
            approved=approved,
            operation="pattern.extract",
            updates={"aggregation": aggregation, "pattern": pattern},
            expected_revision_sha256=str(current["pipeline_revision_sha256"]),
        )

    @_input_scope
    def form_learning_hypothesis(
        self,
        pipeline_id: str,
        *,
        unit_id: str,
        kind: str,
        claim: str,
        incumbent_artifact: object,
        challenger_artifact: object,
        dependency_sha256: Mapping[str, str],
        approved: bool,
        formed_by: str,
    ) -> dict[str, object]:
        current = self._read_learning(pipeline_id)
        normalized_unit_id = self._identity(unit_id, "learning unit identity")
        normalized_kind = self._identity(kind, "learning unit kind")
        self._validate_learning_content(
            {"unit_id": normalized_unit_id, "kind": normalized_kind, "claim": claim},
            "learning hypothesis",
            maximum_bytes=64 * 1024,
        )
        for label, artifact in (
            ("incumbent", incumbent_artifact),
            ("challenger", challenger_artifact),
        ):
            if not isinstance(artifact, Mapping):
                raise ValueError(f"{label} artifact must be an object")
            artifact_id = self._identity(
                artifact.get("id"), f"{label} artifact identity"
            )
            artifact_kind = self._identity(
                artifact.get("kind"), f"{label} artifact kind"
            )
            if artifact_id != normalized_unit_id or artifact_kind != normalized_kind:
                raise ValueError(
                    f"{label} artifact id and kind must match the frozen learning unit"
                )
        pattern = current.get("pattern")
        aggregation = current.get("aggregation")
        if not isinstance(pattern, Mapping) or not isinstance(aggregation, Mapping):
            raise PermissionError(
                "a hashed pattern is required before hypothesis formation"
            )
        dependencies, dependency_errors = self._dependency_snapshot(dependency_sha256)
        if dependency_errors:
            raise PermissionError(
                "hypothesis dependencies are not current: "
                + ", ".join(dependency_errors)
            )
        evidence_hashes = [
            str(item.get("record_sha256"))
            for item in current.get("operation_evidence", [])
            if isinstance(item, Mapping)
        ]
        incumbent = freeze_revision(
            unit_id=normalized_unit_id,
            kind=normalized_kind,
            artifact=self._validate_learning_content(
                incumbent_artifact, "incumbent artifact"
            ),
            evidence_sha256=evidence_hashes,
            dependency_sha256=dependencies,
            tier=1,
        )
        challenger = freeze_revision(
            unit_id=normalized_unit_id,
            kind=normalized_kind,
            artifact=self._validate_learning_content(
                challenger_artifact, "challenger artifact"
            ),
            evidence_sha256=evidence_hashes,
            dependency_sha256=dependencies,
            parent_revision_sha256=str(incumbent["revision_sha256"]),
            tier=2,
        )
        hypothesis = form_hypothesis(
            pattern=pattern,
            claim=claim,
            success_metric=str(aggregation.get("metric") or ""),
            incumbent_revision_sha256=str(incumbent["revision_sha256"]),
            challenger_revision_sha256=str(challenger["revision_sha256"]),
        )
        return self._transition_learning(
            pipeline_id,
            allowed_states=("pattern",),
            target="hypothesis",
            actor=formed_by,
            approved=approved,
            operation="hypothesis.form",
            updates={
                "hypothesis": hypothesis,
                "incumbent_revision": incumbent,
                "challenger_revision": challenger,
                "dependency_sha256": dependencies,
            },
            expected_revision_sha256=str(current["pipeline_revision_sha256"]),
        )

    @_input_scope
    def record_learning_trial(
        self,
        pipeline_id: str,
        *,
        winner: str,
        evidence_ref: str,
        approved: bool,
        recorded_by: str,
    ) -> dict[str, object]:
        current = self._read_learning(pipeline_id)
        if current["state"] not in {"hypothesis", "trialing", "secondary-trialing"}:
            raise ValueError("the learning pipeline is not accepting A/B trials")
        evidence, errors = self._evidence_snapshots([evidence_ref])
        if errors or len(evidence) != 1:
            raise PermissionError("A/B trial evidence is unresolved")
        if winner not in {"challenger", "incumbent", "tie"}:
            raise ValueError("trial winner must be challenger, incumbent, or tie")
        trial = {
            "winner": winner,
            "evidence_ref": evidence_ref,
            "evidence_sha256": evidence[0]["sha256"],
            "recorded_utc": _now(),
        }
        secondary = current["state"] == "secondary-trialing"
        field = "secondary_trials" if secondary else "trials"
        trials = list(current.get(field) or ())
        if len(trials) >= LEARNING_MAXIMUM_TRIALS:
            raise ValueError("learning trial bound has been reached")
        if any(
            isinstance(item, Mapping)
            and item.get("evidence_sha256") == trial["evidence_sha256"]
            for item in trials
        ):
            raise ValueError("duplicate A/B trial evidence is not admitted")
        trials.append(trial)
        updates: dict[str, object] = {field: trials}
        target = "secondary-trialing" if secondary else "trialing"
        operation = "trial.secondary.record" if secondary else "trial.record"
        if secondary:
            incumbent = current.get("challenger_revision")
            challenger = current.get("secondary_revision")
        else:
            incumbent = current.get("incumbent_revision")
            challenger = current.get("challenger_revision")
        if not isinstance(incumbent, Mapping) or not isinstance(challenger, Mapping):
            raise PermissionError("A/B trial revisions are unavailable")
        if len(trials) >= LEARNING_MINIMUM_TRIALS:
            comparison = compare_revisions(
                incumbent=incumbent,
                challenger=challenger,
                trials=trials,
                minimum_trials=LEARNING_MINIMUM_TRIALS,
            )
            if secondary:
                reverse_trials = [
                    {
                        **item,
                        "winner": "challenger"
                        if item["winner"] == "incumbent"
                        else "incumbent"
                        if item["winner"] == "challenger"
                        else "tie",
                    }
                    for item in trials
                ]
                incumbent_comparison = compare_revisions(
                    incumbent=challenger,
                    challenger=incumbent,
                    trials=reverse_trials,
                    minimum_trials=LEARNING_MINIMUM_TRIALS,
                )
                updates.update(
                    {
                        "secondary_comparison": comparison,
                        "secondary_incumbent_comparison": incumbent_comparison,
                    }
                )
                if comparison["passed"]:
                    target = "research-validated"
                    updates["selected_revision"] = challenger
                    updates["selection_comparison"] = comparison
                elif incumbent_comparison["passed"]:
                    target = "research-validated"
                    updates["selected_revision"] = incumbent
                    updates["selection_comparison"] = current.get("comparison")
            else:
                updates["comparison"] = comparison
                if comparison["passed"]:
                    target = "confidence-passed"
                    updates["selected_revision"] = challenger
                    updates["selection_comparison"] = comparison
        return self._transition_learning(
            pipeline_id,
            allowed_states=("hypothesis", "trialing", "secondary-trialing"),
            target=target,
            actor=recorded_by,
            approved=approved,
            operation=operation,
            updates=updates,
            expected_revision_sha256=str(current["pipeline_revision_sha256"]),
        )

    @_input_scope
    def validate_learning_research(
        self,
        pipeline_id: str,
        *,
        question: str,
        references: Sequence[Mapping[str, object]],
        better_alternative_found: bool,
        conclusion: str,
        secondary_artifact: object | None,
        approved: bool,
        validated_by: str,
    ) -> dict[str, object]:
        current = self._read_learning(pipeline_id)
        self._validate_learning_content(
            {
                "question": question,
                "conclusion": conclusion,
                "references": list(references),
            },
            "research validation",
            maximum_bytes=128 * 1024,
        )
        normalized = []
        for item in references:
            evidence_ref = str(item.get("evidence_ref") or "")
            evidence, errors = self._evidence_snapshots([evidence_ref])
            if errors or len(evidence) != 1:
                raise PermissionError("research reference evidence is unresolved")
            normalized.append(
                {
                    "uri": str(item.get("uri") or ""),
                    "evidence_sha256": evidence[0]["sha256"],
                    "evidence_ref": evidence_ref,
                    "independent": bool(item.get("independent", True)),
                }
            )
        research = research_validation(
            question=question,
            references=normalized,
            better_alternative_found=better_alternative_found,
            conclusion=conclusion,
        )
        updates: dict[str, object] = {
            "research": research,
            "research_references": normalized,
        }
        target = "research-blocked"
        if research["passed"] and better_alternative_found:
            if secondary_artifact is None:
                raise ValueError(
                    "a discovered better alternative requires a tier-three artifact"
                )
            selected = current.get("selected_revision")
            if not isinstance(selected, Mapping):
                raise PermissionError("the confidence-selected revision is unavailable")
            evidence_hashes = [
                str(item.get("record_sha256"))
                for item in current.get("operation_evidence", [])
                if isinstance(item, Mapping)
            ] + [str(research["record_sha256"])]
            secondary = freeze_revision(
                unit_id=str(selected.get("unit_id") or ""),
                kind=str(selected.get("kind") or ""),
                artifact=self._validate_learning_content(
                    secondary_artifact, "tier-three artifact"
                ),
                evidence_sha256=evidence_hashes,
                dependency_sha256=dict(selected.get("dependency_sha256") or {}),
                parent_revision_sha256=str(selected.get("revision_sha256") or ""),
                tier=3,
            )
            updates.update(
                {
                    "secondary_revision": secondary,
                    "secondary_trials": [],
                    "secondary_comparison": None,
                }
            )
            target = "secondary-trialing"
        elif research["passed"]:
            target = "research-validated"
        return self._transition_learning(
            pipeline_id,
            allowed_states=("confidence-passed", "research-blocked"),
            target=target,
            actor=validated_by,
            approved=approved,
            operation="research.validate",
            updates=updates,
            expected_revision_sha256=str(current["pipeline_revision_sha256"]),
        )

    @_input_scope
    def final_validate_learning(
        self,
        pipeline_id: str,
        *,
        validation_evidence_ref: str,
        partial_units: Sequence[str],
        approved: bool,
        validated_by: str,
    ) -> dict[str, object]:
        current = self._read_learning(pipeline_id)
        normalized_partial_units = sorted(
            {self._identity(item, "partial unit identity") for item in partial_units}
        )
        self._validate_learning_content(
            {
                "validation_evidence_ref": validation_evidence_ref,
                "partial_units": normalized_partial_units,
            },
            "final learning validation",
            maximum_bytes=64 * 1024,
        )
        evidence, errors = self._evidence_snapshots([validation_evidence_ref])
        if errors or len(evidence) != 1:
            raise PermissionError("final validation evidence is unresolved")
        revision = current.get("selected_revision")
        comparison = current.get("selection_comparison")
        research = current.get("research")
        if (
            not isinstance(revision, Mapping)
            or not isinstance(comparison, Mapping)
            or not isinstance(research, Mapping)
            or not isinstance(comparison.get("gate"), Mapping)
        ):
            raise PermissionError("final validation gates are incomplete")
        expected_dependencies = revision.get("dependency_sha256")
        if not isinstance(expected_dependencies, Mapping):
            raise PermissionError("selected revision dependencies are invalid")
        current_dependencies, dependency_errors = self._dependency_snapshot(
            {str(key): str(value) for key, value in expected_dependencies.items()}
        )
        final_validation = {
            "schema_version": "px.learning-final-validation/1.0",
            "evidence_ref": validation_evidence_ref,
            "evidence_sha256": evidence[0]["sha256"],
            "dependency_errors": dependency_errors,
            "validated_by": validated_by,
            "validated_utc": _now(),
        }
        decision = promote_revision(
            revision=revision,
            confidence=comparison["gate"],
            comparison=comparison,
            research=research,
            final_validation_sha256=str(evidence[0]["sha256"]),
            current_dependencies=current_dependencies,
            partial_units=normalized_partial_units,
        )
        target = (
            "validated"
            if decision["passed"] and not dependency_errors
            else "validation-blocked"
        )
        return self._transition_learning(
            pipeline_id,
            allowed_states=("research-validated", "validation-blocked"),
            target=target,
            actor=validated_by,
            approved=approved,
            operation="validation.final",
            updates={
                "final_validation": final_validation,
                "promotion_decision": decision,
                "blocked_reasons": dependency_errors
                + (
                    []
                    if decision["passed"]
                    else [
                        f"gate_failed:{key}"
                        for key, passed in decision["checks"].items()
                        if not passed
                    ]
                ),
            },
            expected_revision_sha256=str(current["pipeline_revision_sha256"]),
        )

    @_input_scope
    def admit_learning_candidate(
        self,
        pipeline_id: str,
        *,
        approved: bool,
        admitted_by: str,
    ) -> dict[str, object]:
        if not approved:
            raise PermissionError("learning admission requires explicit host approval")
        current = self._read_learning(pipeline_id)
        if current["state"] != "validated":
            raise PermissionError(
                "only a fully validated learning pipeline may be admitted"
            )
        decision = current.get("promotion_decision")
        revision = current.get("selected_revision")
        if (
            not isinstance(decision, Mapping)
            or decision.get("passed") is not True
            or not isinstance(revision, Mapping)
            or not isinstance(revision.get("artifact"), Mapping)
        ):
            raise PermissionError("validated learning promotion evidence is incomplete")
        artifact = dict(revision["artifact"])
        artifact["_px_learning"] = {
            "pipeline_id": pipeline_id,
            "pipeline_revision_sha256": current["pipeline_revision_sha256"],
            "selected_revision_sha256": revision["revision_sha256"],
            "promotion_decision_sha256": decision["record_sha256"],
            "canonical_corpus_sha256": decision["canonical_corpus_sha256"],
            "direct_write_allowed": False,
        }
        existing_proposal = None
        for path in self._control_heads("proposals"):
            candidate = self._verify_signed(path)
            learning = (
                candidate.get("candidate", {}).get("_px_learning", {})
                if isinstance(candidate.get("candidate"), Mapping)
                else {}
            )
            if (
                isinstance(learning, Mapping)
                and learning.get("pipeline_id") == pipeline_id
                and learning.get("promotion_decision_sha256")
                == decision["record_sha256"]
            ):
                existing_proposal = self._read(str(candidate["proposal_id"]))
                break
        evidence_refs = sorted(
            {
                str(reference)
                for record in current.get("operation_evidence", [])
                if isinstance(record, Mapping)
                for reference in record.get("source_refs", [])
            }
            | {
                f"sha256:{item['evidence_sha256']}"
                for item in current.get("research_references", [])
                if isinstance(item, Mapping) and item.get("evidence_sha256")
            }
            | {
                str(item.get("evidence_ref") or "")
                for field in ("trials", "secondary_trials")
                for item in current.get(field, [])
                if isinstance(item, Mapping)
            }
            | {str(current.get("final_validation", {}).get("evidence_ref") or "")}
        )
        evidence_refs = [item for item in evidence_refs if item]
        proposal = existing_proposal or self.propose(
            artifact,
            source_ids=list(map(str, current.get("source_ids") or ())),
            evidence_refs=evidence_refs,
            approved=True,
            proposed_by=admitted_by,
        )
        return self._transition_learning(
            pipeline_id,
            allowed_states=("validated",),
            target="admitted",
            actor=admitted_by,
            approved=True,
            operation="candidate.admit",
            updates={
                "knowledge_proposal_id": proposal["proposal_id"],
                "knowledge_candidate_sha256": proposal["candidate_sha256"],
                "canonical_writes_performed": False,
            },
            expected_revision_sha256=str(current["pipeline_revision_sha256"]),
        )

    @_input_scope
    def measure_learning_reuse(
        self,
        pipeline_id: str,
        *,
        uses: int,
        successes: int,
        regressions: int,
        approved: bool,
        measured_by: str,
        dependency_graph: Mapping[str, object] | None = None,
        dependency_current_revisions: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        current = self._read_learning(pipeline_id)
        proposal_id = str(current.get("knowledge_proposal_id") or "")
        proposal = self._read(proposal_id) if proposal_id else None
        if (
            current["state"] not in {"admitted", "canonical"}
            or not proposal
            or proposal.get("state") != "promoted"
        ):
            raise PermissionError(
                "measured reuse requires a promoted canonical knowledge revision"
            )
        decision = current.get("promotion_decision")
        if not isinstance(decision, Mapping):
            raise PermissionError("learning promotion decision is unavailable")
        measurement = measure_reuse(
            promotion_sha256=str(decision.get("record_sha256") or ""),
            uses=uses,
            successes=successes,
            regressions=regressions,
        )
        decay = decay_decision(measurement)
        measurements = list(current.get("reuse_measurements") or ())
        if measurements:
            prior = measurements[-1]
            if not isinstance(prior, Mapping) or any(
                int(measurement[field]) < int(prior.get(field, 0))
                for field in ("uses", "successes", "regressions")
            ):
                raise ValueError("reuse measurements must be cumulative and monotonic")
        if len(measurements) >= 100:
            raise ValueError(
                "learning reuse measurement history bound has been reached"
            )
        measurements.append(measurement)
        invalidation: Mapping[str, object] | None = None
        if decay["decay"]:
            record_id = str(proposal.get("record_id") or "")
            knowledge_node = f"knowledge:{record_id}"
            graph = dependency_graph
            if graph is None:
                graph = build_dependency_graph(
                    Path(__file__).resolve().parents[1],
                    [
                        {
                            "node_id": knowledge_node,
                            "kind": "knowledge",
                            "revision": str(proposal.get("candidate_sha256") or ""),
                        }
                    ],
                    [],
                )
            graph_nodes = {
                str(item.get("node_id"))
                for item in graph.get("nodes", [])
                if isinstance(item, Mapping)
            }
            if knowledge_node not in graph_nodes:
                raise ValueError(
                    "decay dependency graph omits canonical knowledge node"
                )
            revisions = dict(dependency_current_revisions or {})
            revisions[knowledge_node] = f"decayed:{decay['record_sha256']}"
            invalidation = compute_invalidation_cone(
                graph,
                revisions,
                authority=load_dependency_authority(
                    Path(__file__).resolve().parents[1]
                ),
            )
            canonical_root = self._canonical_root(record_id)
            head_path = canonical_root / "head.json"
            head = self._verify_signed(head_path)
            if head.get("candidate_sha256") != proposal.get("candidate_sha256"):
                raise PermissionError(
                    "canonical knowledge changed before decay invalidation"
                )
            suspect_head = {
                **head,
                "updated_utc": _now(),
                "authority_status": "suspect",
                "authoritative": False,
                "revalidation_required": True,
                "decay_decision_sha256": decay["record_sha256"],
                "dependent_invalidation": invalidation,
            }
            suspect_head.pop("host_authority", None)
            write_json_atomic(head_path, self.authority.sign_receipt(suspect_head))
        return self._transition_learning(
            pipeline_id,
            allowed_states=("admitted", "canonical"),
            target="decayed" if decay["decay"] else "canonical",
            actor=measured_by,
            approved=approved,
            operation="reuse.measure",
            updates={
                "reuse_measurements": measurements,
                "decay_decision": decay,
                "dependent_invalidation": invalidation,
                "revalidation_evidence": None,
                "canonical_writes_performed": False,
            },
            expected_revision_sha256=str(current["pipeline_revision_sha256"]),
        )

    @_input_scope
    def revalidate_learning(
        self,
        pipeline_id: str,
        *,
        evidence_ref: str,
        evidence_sha256: str,
        approved: bool,
        revalidated_by: str,
    ) -> dict[str, object]:
        """Restore canonical authority only from fresh, hash-bound evidence."""
        current = self._read_learning(pipeline_id)
        if current["state"] != "decayed":
            raise PermissionError("only decayed canonical knowledge may be revalidated")
        if (
            not approved
            or not str(evidence_ref).strip()
            or not re.fullmatch(r"[a-f0-9]{64}", str(evidence_sha256))
        ):
            raise PermissionError(
                "canonical revalidation requires fresh hash-bound evidence"
            )
        proposal_id = str(current.get("knowledge_proposal_id") or "")
        proposal = self._read(proposal_id)
        record_id = str(proposal.get("record_id") or "")
        head_path = self._canonical_root(record_id) / "head.json"
        head = self._verify_signed(head_path)
        if head.get("authority_status") != "suspect" or head.get(
            "candidate_sha256"
        ) != proposal.get("candidate_sha256"):
            raise PermissionError(
                "canonical suspect identity changed before revalidation"
            )
        dependent_invalidation = current.get("dependent_invalidation")
        if not isinstance(dependent_invalidation, Mapping):
            dependent_invalidation = {}
        revalidation = {
            "schema_version": "px.knowledge-revalidation/1.0",
            "evidence_ref": evidence_ref,
            "evidence_sha256": evidence_sha256,
            "canonical_revision": head["candidate_sha256"],
            "revalidated_by": revalidated_by,
            "revalidated_utc": _now(),
            "dependent_rebuild_required": bool(
                dependent_invalidation.get("direct_consumers")
                or dependent_invalidation.get("transitive_consumers")
            ),
        }
        transitioned = self._transition_learning(
            pipeline_id,
            allowed_states=("decayed",),
            target="canonical",
            actor=revalidated_by,
            approved=approved,
            operation="reuse.revalidate",
            updates={
                "revalidation_evidence": revalidation,
                "canonical_writes_performed": False,
            },
            expected_revision_sha256=str(current["pipeline_revision_sha256"]),
        )
        current_head = {
            **head,
            "updated_utc": _now(),
            "authority_status": "current",
            "authoritative": True,
            "revalidation_required": False,
            "revalidation": revalidation,
        }
        current_head.pop("host_authority", None)
        write_json_atomic(head_path, self.authority.sign_receipt(current_head))
        return transitioned

    @_input_scope
    def resolve_canonical(
        self, record_id: str, *, require_authoritative: bool = True
    ) -> dict[str, object]:
        """Resolve current canonical bytes, failing closed while they are suspect."""
        root = self._canonical_root(record_id)
        head = self._verify_signed(root / "head.json")
        if require_authoritative and (
            head.get("authority_status") == "suspect"
            or head.get("revalidation_required") is True
        ):
            raise PermissionError(
                "canonical knowledge is suspect and requires revalidation"
            )
        revision = self._verify_signed(self.project_root / str(head["revision"]))
        return {"head": head, "canonical": revision, "historical": True}

    @_input_scope
    def _browse_learning(self, *, query: str, limit: int) -> dict[str, object]:
        self._browse_input(query, limit)
        needle = query.casefold().strip()
        pipelines = []
        invalid = []
        for path in self._control_heads("learning"):
            try:
                supplied = self._verify_signed(path)
                pipeline = self._read_learning(str(supplied.get("pipeline_id") or ""))
                proposal_id = str(pipeline.get("knowledge_proposal_id") or "")
                linked = self._read(proposal_id) if proposal_id else None
                effective_state = pipeline["state"]
                if linked and pipeline["state"] == "admitted":
                    if linked.get("state") == "promoted":
                        effective_state = "canonical"
                    elif linked.get("state") in {"blocked", "rejected"}:
                        effective_state = f"admission-{linked['state']}"
                projected = {
                    **pipeline,
                    "effective_state": effective_state,
                    "knowledge_proposal_state": linked.get("state") if linked else None,
                    "knowledge_candidate_sha256": linked.get("candidate_sha256")
                    if linked
                    else pipeline.get("knowledge_candidate_sha256"),
                }
                if (
                    needle
                    and needle not in json.dumps(projected, sort_keys=True).casefold()
                ):
                    continue
                pipelines.append(projected)
                if len(pipelines) >= limit:
                    break
            except _KnowledgeAcquisitionLimit:
                raise
            except (
                FileNotFoundError,
                OSError,
                ValueError,
                PermissionError,
                json.JSONDecodeError,
            ) as error:
                invalid.append(
                    {
                        "path": path.relative_to(self.project_root).as_posix(),
                        "error": type(error).__name__,
                        "detail": str(error),
                    }
                )
        states: dict[str, int] = {}
        for item in pipelines:
            state = str(item.get("effective_state") or "unknown")
            states[state] = states.get(state, 0) + 1
        return {
            "schema_version": "px.learning-pipeline-control/1.0",
            "pipelines": pipelines,
            "invalid": invalid,
            "counts": {
                "pipelines": len(pipelines),
                "invalid": len(invalid),
                "states": dict(sorted(states.items())),
                "trials": sum(
                    len(item.get("trials") or ())
                    + len(item.get("secondary_trials") or ())
                    for item in pipelines
                ),
            },
            "policy": {
                "lifecycle": [
                    "evidence",
                    "pattern",
                    "hypothesis",
                    "bounded-a-b",
                    "confidence",
                    "independent-research",
                    "final-validation",
                    "knowledge-admission",
                    "canonical-or-decay",
                ],
                "minimum_trials": LEARNING_MINIMUM_TRIALS,
                "maximum_trials": LEARNING_MAXIMUM_TRIALS,
                "maximum_retained_history_bytes": LEARNING_MAXIMUM_HISTORY_BYTES,
                "direct_canonical_write": False,
                "loser_retention_required": True,
                "automatic_destructive_retirement": False,
            },
            "available": not invalid,
            "degraded": bool(invalid),
            "limitations": [
                "Learning candidates cannot write canonical knowledge directly; admitted candidates still cross knowledge verification, approval, and promotion gates."
            ],
        }

    @_input_scope
    def propose(
        self,
        candidate: Mapping[str, object],
        *,
        source_ids: Sequence[str],
        evidence_refs: Sequence[str],
        approved: bool,
        proposed_by: str,
    ) -> dict[str, object]:
        if not approved:
            raise PermissionError(
                "knowledge proposal write requires explicit host approval"
            )
        bounded_mapping(candidate, "knowledge candidate", maximum=256)
        _bounded_input(candidate, maximum=256 * 1024)
        record_id = self._identity(candidate.get("id"), "record identity")
        kind = self._identity(candidate.get("kind"), "record kind")
        normalized_candidate = {**dict(candidate), "id": record_id, "kind": kind}
        if len(canonical_bytes(normalized_candidate)) > 256 * 1024:
            raise ValueError("knowledge candidate exceeds the 256 KiB bound")
        sanitized = sanitize_capture(
            json.dumps(normalized_candidate, ensure_ascii=False)
        )
        if sanitized.secret_finding_codes:
            raise ValueError("knowledge candidate contains secret-like material")
        sources = sorted(self._references(source_ids, "knowledge source identities"))
        evidence = sorted(
            self._references(evidence_refs, "knowledge evidence references")
        )
        if not sources or not evidence:
            raise ValueError("knowledge proposal requires sources and evidence")
        candidate_sha = _hash(normalized_candidate)
        proposal_id = f"proposal:{uuid4().hex}"
        timestamp = _now()
        state = {
            "schema_version": "px.knowledge-proposal/1.0",
            "proposal_id": proposal_id,
            "record_id": record_id,
            "candidate_sha256": candidate_sha,
            "candidate": normalized_candidate,
            "source_ids": sources,
            "evidence_refs": evidence,
            "state": "candidate",
            "sequence": 1,
            "created_utc": timestamp,
            "updated_utc": timestamp,
            "verification": None,
            "approval": None,
            "promotion": None,
            "blocked_reasons": [],
            "authority_state": "codex-host-retained",
            "canonical_writes_performed": False,
            "last_event_sha256": "0" * 64,
        }
        self._publication_input(state, proposed_by, "propose", None)
        with FileLock(self.lock, timeout_seconds=10):
            root = self._proposal_root(proposal_id)
            root.mkdir(parents=True, exist_ok=False)
            (root / "events").mkdir()
            return self._publish(
                state, actor=proposed_by, operation="propose", previous=None
            )

    @_input_scope
    def _transition(
        self,
        proposal_id: str,
        target: str,
        *,
        actor: str,
        approved: bool,
        updates: Mapping[str, object] | None = None,
        operation: str,
    ) -> dict[str, object]:
        if not approved:
            raise PermissionError(
                "knowledge transition requires explicit host approval"
            )
        with FileLock(self.lock, timeout_seconds=10):
            current = self._read(proposal_id)
            if target not in TRANSITIONS[str(current["state"])]:
                raise ValueError(
                    f"illegal knowledge transition: {current['state']} -> {target}"
                )
            next_state = {
                **current,
                **dict(updates or {}),
                "state": target,
                "sequence": int(current["sequence"]) + 1,
                "updated_utc": _now(),
            }
            return self._publish(
                next_state,
                actor=actor,
                operation=operation,
                previous=current,
            )

    @_input_scope
    def verify(
        self, proposal_id: str, *, approved: bool, verified_by: str
    ) -> dict[str, object]:
        current = self._read(proposal_id)
        if current["state"] != "candidate":
            raise ValueError("only a candidate knowledge proposal may be verified")
        source_snapshots, reasons = self._source_snapshots(
            list(map(str, current["source_ids"]))
        )
        evidence_snapshots, evidence_errors = self._evidence_snapshots(
            list(map(str, current["evidence_refs"]))
        )
        reasons.extend(evidence_errors)
        canonical_root = self._canonical_root(str(current["record_id"]))
        canonical_head = (
            self._verify_signed(canonical_root / "head.json")
            if (canonical_root / "head.json").is_file()
            else None
        )
        expected = str(current["candidate"].get("supersedes_sha256") or "")
        if canonical_head is not None and expected != canonical_head.get(
            "candidate_sha256"
        ):
            reasons.append("canonical_revision_conflict")
        verification = {
            "verified_utc": _now(),
            "verified_by": verified_by,
            "candidate_sha256": current["candidate_sha256"],
            "source_errors": reasons,
            "source_snapshots": source_snapshots,
            "evidence_snapshots": evidence_snapshots,
            "canonical_head_sha256": canonical_head.get("candidate_sha256")
            if canonical_head
            else None,
            "eligible": not reasons,
            "oracle": "source-availability+content-identity+optimistic-concurrency",
        }
        return self._transition(
            proposal_id,
            "verified" if not reasons else "blocked",
            actor=verified_by,
            approved=approved,
            updates={"verification": verification, "blocked_reasons": reasons},
            operation="verify" if not reasons else "block",
        )

    @_input_scope
    def approve(
        self, proposal_id: str, *, approved: bool, approved_by: str
    ) -> dict[str, object]:
        current = self._read(proposal_id)
        verification = current.get("verification")
        if (
            current["state"] != "verified"
            or not isinstance(verification, Mapping)
            or verification.get("eligible") is not True
            or verification.get("candidate_sha256") != current["candidate_sha256"]
        ):
            raise PermissionError("current eligible verification is required")
        approval = {
            "approval_id": f"knowledge-approval:{uuid4().hex}",
            "approved_by": approved_by,
            "approved_utc": _now(),
            "candidate_sha256": current["candidate_sha256"],
            "single_use": True,
        }
        return self._transition(
            proposal_id,
            "approved",
            actor=approved_by,
            approved=approved,
            updates={"approval": approval},
            operation="approve",
        )

    @_input_scope
    def promote(
        self, proposal_id: str, *, approved: bool, promoted_by: str
    ) -> dict[str, object]:
        if not approved:
            raise PermissionError("knowledge promotion requires explicit host approval")
        with FileLock(self.lock, timeout_seconds=10):
            current = self._read(proposal_id)
            approval = current.get("approval")
            if (
                current["state"] != "approved"
                or not isinstance(approval, Mapping)
                or approval.get("candidate_sha256") != current["candidate_sha256"]
            ):
                raise PermissionError("current knowledge approval is required")
            canonical_root = self._canonical_root(str(current["record_id"]))
            verification = current.get("verification")
            if not isinstance(verification, Mapping):
                raise PermissionError("current knowledge verification is required")
            canonical_head_path = canonical_root / "head.json"
            canonical_head = (
                self._verify_signed(canonical_head_path)
                if canonical_head_path.is_file()
                else None
            )
            observed_head = (
                canonical_head.get("candidate_sha256") if canonical_head else None
            )
            if observed_head != verification.get("canonical_head_sha256"):
                raise PermissionError(
                    "canonical knowledge head changed after verification"
                )
            sources, source_errors = self._source_snapshots(
                list(map(str, current["source_ids"]))
            )
            evidence, evidence_errors = self._evidence_snapshots(
                list(map(str, current["evidence_refs"]))
            )
            if (
                source_errors
                or evidence_errors
                or sources != verification.get("source_snapshots")
                or evidence != verification.get("evidence_snapshots")
            ):
                raise PermissionError(
                    "knowledge source or evidence identity changed after verification"
                )
            revision = (
                canonical_root / "revisions" / f"{current['candidate_sha256']}.json"
            )
            revision.parent.mkdir(parents=True, exist_ok=True)
            canonical_payload = {
                "schema_version": "px.knowledge-canonical-record/1.0",
                "record_id": current["record_id"],
                "candidate_sha256": current["candidate_sha256"],
                "candidate": current["candidate"],
                "source_ids": current["source_ids"],
                "evidence_refs": current["evidence_refs"],
                "proposal_id": proposal_id,
                "approval_id": approval["approval_id"],
                "verified_canonical_head_sha256": verification.get(
                    "canonical_head_sha256"
                ),
                "source_snapshots": sources,
                "evidence_snapshots": evidence,
                "promoted_by": promoted_by,
                "promoted_utc": _now(),
                "authority_state": "codex-host-retained",
            }
            canonical = self.authority.sign_receipt(canonical_payload)
            if revision.exists():
                existing = self._verify_signed(revision)
                for field in (
                    "record_id",
                    "candidate_sha256",
                    "candidate",
                    "source_ids",
                    "evidence_refs",
                    "proposal_id",
                    "approval_id",
                    "verified_canonical_head_sha256",
                    "source_snapshots",
                    "evidence_snapshots",
                    "authority_state",
                ):
                    if existing.get(field) != canonical_payload.get(field):
                        raise FileExistsError("canonical knowledge revision differs")
                canonical_payload = existing
            else:
                write_json_atomic(revision, canonical)
            head = {
                "schema_version": "px.knowledge-canonical-head/1.0",
                "record_id": current["record_id"],
                "candidate_sha256": current["candidate_sha256"],
                "revision": revision.relative_to(self.project_root).as_posix(),
                "proposal_id": proposal_id,
                "updated_utc": _now(),
                "authority_state": "codex-host-retained",
            }
            write_json_atomic(
                canonical_root / "head.json", self.authority.sign_receipt(head)
            )
            promoted = {
                **current,
                "state": "promoted",
                "sequence": int(current["sequence"]) + 1,
                "updated_utc": _now(),
                "promotion": head,
                "canonical_writes_performed": True,
            }
            return self._publish(
                promoted,
                actor=promoted_by,
                operation="promote",
                previous=current,
            )

    @_input_scope
    def recover(self, *, approved: bool, recovered_by: str) -> dict[str, object]:
        """Reconcile only signed projections and provable commits; infer no authority."""
        if not approved:
            raise PermissionError("knowledge recovery requires explicit host approval")
        checked = recovered = projections_repaired = learning_projections_repaired = (
            conflicts
        ) = 0
        with FileLock(self.lock, timeout_seconds=10):
            for learning_root in self._control_roots("learning"):
                if learning_root.is_dir():
                    learning_projections_repaired += int(
                        self._recover_learning_projection(learning_root)
                    )
            for proposal_root in self._control_roots("proposals"):
                if not proposal_root.is_dir():
                    continue
                repaired = self._recover_proposal_projection(proposal_root)
                projections_repaired += int(repaired)
                head_path = proposal_root / "head.json"
                proposal_id = str(
                    self._verify_signed(head_path).get("proposal_id") or ""
                )
                state = self._read(proposal_id)
                checked += 1
                if state["state"] != "approved":
                    continue
                revision = (
                    self._canonical_root(str(state["record_id"]))
                    / "revisions"
                    / f"{state['candidate_sha256']}.json"
                )
                if not revision.is_file():
                    continue
                canonical = self._verify_signed(revision)
                if (
                    canonical.get("proposal_id") != proposal_id
                    or canonical.get("candidate_sha256") != state["candidate_sha256"]
                    or canonical.get("approval_id")
                    != dict(state.get("approval") or {}).get("approval_id")
                ):
                    raise PermissionError(
                        "partial knowledge promotion cannot be reconciled"
                    )
                canonical_root = self._canonical_root(str(state["record_id"]))
                verification = state.get("verification")
                if not isinstance(verification, Mapping):
                    raise PermissionError(
                        "partial promotion lacks verification identity"
                    )
                current_head = (
                    self._verify_signed(canonical_root / "head.json")
                    if (canonical_root / "head.json").is_file()
                    else None
                )
                current_sha = (
                    current_head.get("candidate_sha256") if current_head else None
                )
                if current_sha not in {
                    verification.get("canonical_head_sha256"),
                    state["candidate_sha256"],
                }:
                    conflicts += 1
                    continue
                if (
                    current_sha == state["candidate_sha256"]
                    and current_head.get("proposal_id") != proposal_id
                ):
                    conflicts += 1
                    continue
                promotion = {
                    "schema_version": "px.knowledge-canonical-head/1.0",
                    "record_id": state["record_id"],
                    "candidate_sha256": state["candidate_sha256"],
                    "revision": revision.relative_to(self.project_root).as_posix(),
                    "proposal_id": proposal_id,
                    "updated_utc": _now(),
                    "authority_state": "codex-host-retained",
                }
                write_json_atomic(
                    canonical_root / "head.json", self.authority.sign_receipt(promotion)
                )
                promoted = {
                    **state,
                    "state": "promoted",
                    "sequence": int(state["sequence"]) + 1,
                    "updated_utc": _now(),
                    "promotion": promotion,
                    "canonical_writes_performed": True,
                }
                self._publish(
                    promoted,
                    actor=recovered_by,
                    previous=state,
                    operation="recover.promoted",
                )
                recovered += 1
        return {
            "schema_version": "px.knowledge-recovery/1.0",
            "checked": checked,
            "recovered": recovered,
            "projections_repaired": projections_repaired,
            "learning_projections_repaired": learning_projections_repaired,
            "conflicts": conflicts,
            "valid": conflicts == 0,
            "authority_state": "codex-host-retained",
        }

    @_input_scope
    def reject(
        self,
        proposal_id: str,
        *,
        approved: bool,
        rejected_by: str,
        reason: str,
    ) -> dict[str, object]:
        if not reason.strip():
            raise ValueError("knowledge rejection requires a reason")
        return self._transition(
            proposal_id,
            "rejected",
            actor=rejected_by,
            approved=approved,
            updates={"blocked_reasons": [reason.strip()]},
            operation="reject",
        )

    @_input_scope
    def rollback(
        self,
        record_id: str,
        target_sha256: str,
        *,
        approved: bool,
        approved_by: str,
        evidence_refs: Sequence[str],
        expected_head_sha256: str | None = None,
    ) -> dict[str, object]:
        if not approved:
            raise PermissionError("knowledge rollback requires explicit host approval")
        evidence = sorted(
            self._references(evidence_refs, "knowledge evidence references")
        )
        if not evidence:
            raise ValueError("knowledge rollback requires evidence")
        evidence_snapshots, evidence_errors = self._evidence_snapshots(evidence)
        if evidence_errors:
            raise PermissionError("knowledge rollback evidence is unresolved")
        with FileLock(self.lock, timeout_seconds=10):
            root = self._canonical_root(record_id)
            current = self._verify_signed(root / "head.json")
            if (
                not expected_head_sha256
                or current.get("candidate_sha256") != expected_head_sha256
            ):
                raise PermissionError(
                    "knowledge rollback canonical head compare-and-swap failed"
                )
            target = root / "revisions" / f"{target_sha256}.json"
            revision = self._verify_signed(target)
            if revision.get("candidate_sha256") != target_sha256:
                raise PermissionError("knowledge rollback target identity is invalid")
            receipt = {
                "schema_version": "px.knowledge-rollback/1.0",
                "record_id": self._identity(record_id, "record identity"),
                "from_sha256": current["candidate_sha256"],
                "to_sha256": target_sha256,
                "approved_by": approved_by,
                "evidence_refs": evidence,
                "evidence_snapshots": evidence_snapshots,
                "rolled_back_utc": _now(),
                "hard_delete": False,
                "authority_state": "codex-host-retained",
            }
            write_json_atomic(
                root / "head.json",
                self.authority.sign_receipt(
                    {
                        "schema_version": "px.knowledge-canonical-head/1.0",
                        "record_id": receipt["record_id"],
                        "candidate_sha256": target_sha256,
                        "revision": target.relative_to(self.project_root).as_posix(),
                        "proposal_id": revision["proposal_id"],
                        "updated_utc": _now(),
                        "authority_state": "codex-host-retained",
                    }
                ),
            )
            receipt_path = root / "rollbacks" / f"{uuid4().hex}.json"
            write_json_atomic(receipt_path, self.authority.sign_receipt(receipt))
            return receipt

    @_input_scope
    def browse(self, *, query: str = "", limit: int = 100) -> dict[str, object]:
        self._browse_input(query, limit)
        needle = query.casefold().strip()
        proposals = []
        for path in self._control_heads("proposals"):
            proposal_id = str(self._verify_signed(path).get("proposal_id") or "")
            head = self._read(proposal_id)
            if needle and needle not in json.dumps(head, sort_keys=True).casefold():
                continue
            proposals.append(head)
            if len(proposals) >= limit:
                break
        canonical = []
        for path in self._control_heads("canonical"):
            head = self._verify_signed(path)
            if not needle or needle in json.dumps(head, sort_keys=True).casefold():
                rollback_targets = []
                revisions = path.parent / "revisions"
                if revisions.is_dir():
                    for revision_path in self._revision_paths(revisions)[:100]:
                        revision = self._verify_signed(revision_path)
                        candidate_sha256 = str(revision.get("candidate_sha256") or "")
                        if candidate_sha256 and candidate_sha256 != head.get(
                            "candidate_sha256"
                        ):
                            rollback_targets.append(
                                {
                                    "candidate_sha256": candidate_sha256,
                                    "proposal_id": revision.get("proposal_id"),
                                    "revision": revision_path.relative_to(
                                        self.project_root
                                    ).as_posix(),
                                }
                            )
                canonical.append(
                    {
                        **head,
                        "authority_status": head.get("authority_status", "current"),
                        "authoritative": head.get("authority_status") != "suspect",
                        "revalidation_required": head.get(
                            "revalidation_required", False
                        ),
                        "rollback_targets": rollback_targets,
                    }
                )
            if len(canonical) >= limit:
                break
        sources = list(self._sources().values())
        source_errors = self._source_errors([str(row.get("id")) for row in sources])
        learning = self._browse_learning(query=query, limit=limit)
        return {
            "schema_version": "px.knowledge-core-control/1.0",
            "sources": sources[:limit],
            "proposals": proposals,
            "canonical": canonical,
            "invalid_sources": source_errors,
            "conflicts": [
                item
                for item in proposals
                if "canonical_revision_conflict" in item.get("blocked_reasons", [])
            ],
            "learning": learning,
            "actions": {
                "propose": {
                    "available": True,
                    "requires": [
                        "explicit host approval",
                        "declared sources",
                        "evidence",
                    ],
                    "route": "studio knowledge propose",
                },
                "promote": {
                    "available": True,
                    "requires": [
                        "eligible verification",
                        "explicit approval",
                        "current canonical head",
                    ],
                    "route": "studio knowledge promote",
                },
                "rollback": {
                    "available": any(
                        item.get("rollback_targets") for item in canonical
                    ),
                    "requires": [
                        "explicit host approval",
                        "evidence-bound rollback reason",
                        "unchanged current canonical head",
                        "authenticated retained target revision",
                    ],
                    "route": "studio knowledge rollback",
                },
                "learning": {
                    "available": learning["available"],
                    "requires": [
                        "payload-bound host approval for every durable transition",
                        "hashed operation and trial evidence",
                        "confidence, independent research, and final validation gates",
                        "ordinary knowledge verification and approval before canonical promotion",
                    ],
                    "route": "studio knowledge observe-experience through measure-reuse",
                },
            },
            "authority_state": "codex-host-retained",
        }
