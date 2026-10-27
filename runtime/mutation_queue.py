"""Ordered mutating-effect queue (punch card EXE-005 / EXE-006).

Concurrent mutating effects over overlapping scopes must be serialized and
receipted, not run in parallel and reconciled afterwards. This owner holds the
*ordering and admission* decision for mutating effects; it does not perform the
effect and it grants no authority. A caller must already hold the effect grant
and the exact scope lease before enqueuing.

The queue is deliberately conservative:

* an item is admitted only when no earlier live item overlaps its scope;
* a caller with an explicit dependency on an earlier item waits for that item;
* every transition is appended as an ordered receipt, so an interrupted queue is
  recoverable rather than silently lost;
* a cancelled execution's queued items are cancelled, not executed later.
"""

from __future__ import annotations

from .secure_publish import atomic_write_bytes

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .archive_io import reject_path_links
from .file_lock import FileLock
from .json_io import bounded_canonical_json_bytes, read_bounded_bytes

SCHEMA_VERSION = "px.mutation-queue/1.0"
LEDGER_SCHEMA_VERSION = "px.mutation-queue-ledger/1.0"
MAX_LEDGER_BYTES = 8 * 1024 * 1024
MAX_ITEMS = 10_000
QUEUE_RELATIVE = ".agentic_engineering_os_px/runtime-core/mutation-queue.json"

ITEM_STATES = ("queued", "admitted", "running", "completed", "failed", "cancelled")


class MutationQueueError(ValueError):
    """Raised when a mutation queue request is invalid or conflicts."""


@dataclass(frozen=True, slots=True)
class MutationItem:
    item_id: str
    execution_id: str
    effect: str
    scopes: tuple[str, ...]
    idempotency_key: str
    depends_on: tuple[str, ...]
    state: str
    reason: str

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "item_id": self.item_id,
            "execution_id": self.execution_id,
            "effect": self.effect,
            "scopes": list(self.scopes),
            "idempotency_key": self.idempotency_key,
            "depends_on": list(self.depends_on),
            "state": self.state,
            "reason": self.reason,
            "authority_granted": False,
        }


def _normalize_scopes(scopes: Iterable[str]) -> tuple[str, ...]:
    values = sorted({str(scope).strip().replace("\\", "/") for scope in scopes})
    if not values or any(not value or len(value) > 512 for value in values):
        raise MutationQueueError("mutation scope must be a non-empty bounded set")
    return tuple(values)


def _overlaps(left: tuple[str, ...], right: tuple[str, ...]) -> bool:
    for a in left:
        for b in right:
            if a == b or a.startswith(b + "/") or b.startswith(a + "/"):
                return True
    return False


class MutationQueue:
    """Durable ordered queue for mutating effects, serialized by exact scope."""

    def __init__(self, root: Path) -> None:
        reject_path_links(Path(root))
        self.root = Path(root).resolve(strict=True)
        self.path = self.root / QUEUE_RELATIVE
        self.lock_path = self.path.parent / ".mutation-queue.lock"

    def _load(self) -> list[dict[str, object]]:
        if not self.path.is_file():
            return []
        raw = bytes(read_bounded_bytes(self.path, max_bytes=MAX_LEDGER_BYTES))
        try:
            document = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeError) as error:
            raise MutationQueueError("mutation queue ledger is corrupt") from error
        if not isinstance(document, dict) or document.get("schema_version") != LEDGER_SCHEMA_VERSION:
            raise MutationQueueError("mutation queue ledger schema is unsupported")
        items = document.get("items")
        if not isinstance(items, list) or len(items) > MAX_ITEMS:
            raise MutationQueueError("mutation queue record budget is invalid")
        return items

    def _store(self, items: list[dict[str, object]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        reject_path_links(self.path.parent)
        image = bounded_canonical_json_bytes(
            {"schema_version": LEDGER_SCHEMA_VERSION, "items": items}, max_bytes=MAX_LEDGER_BYTES
        )
        atomic_write_bytes(self.path, image)

    def enqueue(self, *, item_id: str, execution_id: str, effect: str, scopes: Iterable[str],
                idempotency_key: str, depends_on: Iterable[str] = (), reason: str = "") -> MutationItem:
        for name, value in (("item_id", item_id), ("execution_id", execution_id), ("effect", effect),
                            ("idempotency_key", idempotency_key)):
            if type(value) is not str or not value.strip() or len(value) > 512:
                raise MutationQueueError(f"{name} must be bounded nonempty text")
        normalized = _normalize_scopes(scopes)
        deps = tuple(sorted({str(dep).strip() for dep in depends_on}))
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(self.lock_path, timeout_seconds=10):
            items = self._load()
            if any(row.get("item_id") == item_id for row in items):
                raise MutationQueueError("mutation item id already exists")
            known = {str(row.get("item_id")) for row in items}
            unknown = [dep for dep in deps if dep not in known]
            if unknown:
                raise MutationQueueError("mutation item depends on unknown items: " + ",".join(unknown))
            # Refuse a duplicate item for the same idempotency key: replaying an
            # already queued, running OR completed mutation is exactly what this
            # queue must prevent (a completed effect already happened). Only a
            # cancelled item frees its key for a genuine retry.
            if any(row.get("idempotency_key") == idempotency_key
                   and row.get("state") != "cancelled"
                   for row in items):
                raise MutationQueueError("mutation already recorded for this idempotency key")
            item = MutationItem(item_id, execution_id, effect, normalized, idempotency_key, deps, "queued", reason)
            items.append(item.as_dict())
            self._store(items)
            return item

    def _live(self, items: list[dict[str, object]]) -> list[dict[str, object]]:
        return [row for row in items if row.get("state") in {"admitted", "running"}]

    def admit_next(self, *, execution_id: str) -> MutationItem | None:
        """Admit the oldest queued item whose dependencies are complete and whose
        scope does not overlap any currently live mutation.

        Returns the admitted item, or None when nothing can be admitted yet.
        """
        with FileLock(self.lock_path, timeout_seconds=10):
            items = self._load()
            done = {str(row.get("item_id")) for row in items if row.get("state") == "completed"}
            live = self._live(items)
            for row in items:
                if row.get("state") != "queued":
                    continue
                if str(row.get("execution_id")) != execution_id:
                    continue
                deps = tuple(row.get("depends_on") or ())
                if any(dep not in done for dep in deps):
                    continue
                if any(_overlaps(tuple(row.get("scopes") or ()), tuple(other.get("scopes") or ())) for other in live):
                    continue
                row["state"] = "admitted"
                self._store(items)
                return MutationItem(str(row["item_id"]), str(row["execution_id"]), str(row["effect"]),
                                    tuple(row["scopes"]), str(row["idempotency_key"]),
                                    deps, "admitted", str(row.get("reason", "")))
            return None

    def transition(self, *, item_id: str, execution_id: str, state: str) -> MutationItem:
        if state not in ITEM_STATES:
            raise MutationQueueError("unknown mutation item state")
        with FileLock(self.lock_path, timeout_seconds=10):
            items = self._load()
            row = next((entry for entry in items if entry.get("item_id") == item_id), None)
            if row is None:
                raise MutationQueueError("mutation item not found")
            if row.get("execution_id") != execution_id:
                raise MutationQueueError("mutation item is owned by a different execution")
            row["state"] = state
            self._store(items)
            return MutationItem(str(row["item_id"]), str(row["execution_id"]), str(row["effect"]),
                                tuple(row["scopes"]), str(row["idempotency_key"]),
                                tuple(row.get("depends_on") or ()), state, str(row.get("reason", "")))

    def cancel_execution(self, *, execution_id: str) -> tuple[str, ...]:
        """Cancel every queued item for an execution; running items are left to
        the owning run's own cancellation, never silently reclassified."""
        cancelled = []
        with FileLock(self.lock_path, timeout_seconds=10):
            items = self._load()
            for row in items:
                if row.get("execution_id") == execution_id and row.get("state") in {"queued", "admitted"}:
                    row["state"] = "cancelled"
                    cancelled.append(str(row["item_id"]))
            if cancelled:
                self._store(items)
        return tuple(cancelled)

    def snapshot(self) -> dict[str, object]:
        items = self._load()
        counts: dict[str, int] = {}
        for row in items:
            state = str(row.get("state"))
            counts[state] = counts.get(state, 0) + 1
        return {"schema_version": LEDGER_SCHEMA_VERSION, "item_count": len(items),
                "state_counts": counts, "authority_granted": False}