"""Durable effect intents, replay fences and checkpoints (punch cards DUR-001..DUR-004).

A task snapshot is not effect durability. Before a mutating effect runs, its
*intent* must be recorded durably with an idempotency key. After it runs, the
*outcome* must be recorded against that same intent. On restart the intent ledger
answers one question per key: has this effect already happened, is it in flight,
or is it safe to attempt? That is the replay fence.

This owner holds intents and checkpoints only. It performs no effect and grants
no authority; the caller must already hold the effect grant, the scope lease and
any required approval. An intent is a fence, not permission.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

from .archive_io import reject_path_links
from .file_lock import FileLock
from .json_io import bounded_canonical_json_bytes, read_bounded_bytes

SCHEMA_VERSION = "px.effect-intent/1.0"
LEDGER_SCHEMA_VERSION = "px.effect-intent-ledger/1.0"
CHECKPOINT_SCHEMA_VERSION = "px.effect-checkpoint/1.0"
MAX_LEDGER_BYTES = 16 * 1024 * 1024
MAX_RECORDS = 50_000
LEDGER_RELATIVE = ".agentic_engineering_os_px/runtime-core/effect-intents.json"

#: Intent lifecycle. ``intended`` -> ``in_flight`` -> ``committed``/``failed``.
#: ``abandoned`` is set on restart for an in-flight intent whose owner is gone.
INTENT_STATES = ("intended", "in_flight", "committed", "failed", "abandoned")


class EffectIntentError(ValueError):
    """Raised when an effect intent or checkpoint is invalid."""


@dataclass(frozen=True, slots=True)
class EffectIntent:
    idempotency_key: str
    execution_id: str
    effect: str
    scopes: tuple[str, ...]
    state: str
    attempt: int
    result_sha256: str | None
    failure_type: str | None

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "idempotency_key": self.idempotency_key,
            "execution_id": self.execution_id,
            "effect": self.effect,
            "scopes": list(self.scopes),
            "state": self.state,
            "attempt": self.attempt,
            "result_sha256": self.result_sha256,
            "failure_type": self.failure_type,
            "authority_granted": False,
        }


def _normalize_scopes(scopes: Iterable[str]) -> tuple[str, ...]:
    values = sorted({str(scope).strip().replace("\\", "/") for scope in scopes})
    if not values or any(not value or len(value) > 512 for value in values):
        raise EffectIntentError("effect scope must be a non-empty bounded set")
    return tuple(values)


class EffectIntentLedger:
    """Durable replay fence for mutating effects and named checkpoints."""

    def __init__(self, root: Path, *, trusted_reconciliation_authorities: Iterable[str] = ()) -> None:
        reject_path_links(Path(root))
        self.root = Path(root).resolve(strict=True)
        self.path = self.root / LEDGER_RELATIVE
        self.lock_path = self.path.parent / ".effect-intents.lock"
        #: Host-owned reconciliation authorities (E01): only these principals may
        #: commit an ``abandoned`` intent whose real outcome is unknown.
        self._reconciliation_authorities = frozenset(
            str(item) for item in trusted_reconciliation_authorities if str(item).strip()
        )

    def _load(self) -> dict[str, object]:
        if not self.path.is_file():
            return {"schema_version": LEDGER_SCHEMA_VERSION, "intents": [], "checkpoints": []}
        raw = bytes(read_bounded_bytes(self.path, max_bytes=MAX_LEDGER_BYTES))
        try:
            document = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeError) as error:
            raise EffectIntentError("effect intent ledger is corrupt") from error
        if not isinstance(document, dict) or document.get("schema_version") != LEDGER_SCHEMA_VERSION:
            raise EffectIntentError("effect intent ledger schema is unsupported")
        if not isinstance(document.get("intents"), list) or not isinstance(document.get("checkpoints"), list):
            raise EffectIntentError("effect intent ledger is malformed")
        if len(document["intents"]) > MAX_RECORDS or len(document["checkpoints"]) > MAX_RECORDS:
            raise EffectIntentError("effect intent ledger record budget is invalid")
        return document

    def _store(self, document: Mapping[str, object]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        reject_path_links(self.path.parent)
        image = bounded_canonical_json_bytes(dict(document), max_bytes=MAX_LEDGER_BYTES)
        prepared = self.path.parent / f".effect-intents-{os.getpid()}.prepared"
        with prepared.open("wb") as stream:
            stream.write(image)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(prepared, self.path)

    def _find(self, document: Mapping[str, object], key: str) -> dict[str, object] | None:
        return next((row for row in document["intents"] if row.get("idempotency_key") == key), None)

    def fence(self, idempotency_key: str) -> dict[str, object]:
        """Report the replay disposition of an idempotency key.

        * ``new``        - no intent recorded; safe to attempt (and then record).
        * ``committed``  - the effect already completed; DO NOT retry.
        * ``in_flight``  - an attempt is recorded as running; DO NOT retry blindly.
        * ``failed``     - the attempt failed; effect absence is not established.
        * ``abandoned``  - the owner disappeared; actual effect outcome is unknown.
        """
        if type(idempotency_key) is not str or not idempotency_key.strip():
            raise EffectIntentError("fence requires a non-empty idempotency key")
        document = self._load()
        row = self._find(document, idempotency_key)
        if row is None:
            return {"idempotency_key": idempotency_key, "disposition": "new", "retry_safe": True,
                    "authority_granted": False}
        state = str(row.get("state"))
        return {"idempotency_key": idempotency_key, "disposition": state,
                "retry_safe": False,
                "execution_id": row.get("execution_id"), "effect": row.get("effect"),
                "attempt": row.get("attempt"), "authority_granted": False,
                "reconciliation_required": state in {"failed", "abandoned"},
                "result_sha256": row.get("result_sha256"),
                "scopes": row.get("scopes", [])}

    def intend(self, *, idempotency_key: str, execution_id: str, effect: str, scopes: Iterable[str]) -> EffectIntent:
        """Record a new intent; uncertain prior attempts never become blind retries."""
        for name, value in (("idempotency_key", idempotency_key), ("execution_id", execution_id), ("effect", effect)):
            if type(value) is not str or not value.strip() or len(value) > 512:
                raise EffectIntentError(f"{name} must be bounded nonempty text")
        normalized = _normalize_scopes(scopes)
        with FileLock(self.lock_path, timeout_seconds=10):
            document = self._load()
            existing = self._find(document, idempotency_key)
            if existing is not None:
                raise EffectIntentError(
                    "effect intent already recorded as " + str(existing.get("state")))
            attempt = int(existing.get("attempt", 0)) + 1 if existing is not None else 1
            row = EffectIntent(idempotency_key, execution_id, effect, normalized, "in_flight",
                               attempt, None, None).as_dict()
            if existing is not None:
                document["intents"] = [r for r in document["intents"] if r.get("idempotency_key") != idempotency_key]
            document["intents"].append(row)
            self._store(document)
            return EffectIntent(idempotency_key, execution_id, effect, normalized, "in_flight", attempt, None, None)

    def commit(
        self,
        *,
        idempotency_key: str,
        execution_id: str,
        result_sha256: str,
        reconciliation: Mapping[str, object] | None = None,
    ) -> EffectIntent:
        """Commit an intent from ``in_flight`` (or reconcile ``abandoned``).

        E01: an ``abandoned`` intent has an unknown outcome — a syntactically
        valid result digest alone can never mark it committed. Reconciliation
        requires a trusted host-owned authority, an explicit observed outcome and
        evidence bound to the exact result digest.
        """
        if type(result_sha256) is not str or len(result_sha256) != 64 or any(c not in "0123456789abcdef" for c in result_sha256):
            raise EffectIntentError("commit requires a 64-char lowercase sha256 result digest")
        with FileLock(self.lock_path, timeout_seconds=10):
            document = self._load()
            row = self._find(document, idempotency_key)
            if row is None:
                raise EffectIntentError("cannot commit an intent that was never recorded")
            if row.get("execution_id") != execution_id:
                raise EffectIntentError("intent is owned by a different execution")
            if row.get("state") == "committed":
                if row.get("result_sha256") != result_sha256:
                    raise EffectIntentError("committed effect result cannot be rewritten")
                return EffectIntent(idempotency_key, execution_id, str(row["effect"]),
                                    tuple(row["scopes"]), "committed", int(row["attempt"]),
                                    result_sha256, None)
            if row.get("state") == "abandoned":
                if reconciliation is None:
                    raise EffectIntentError(
                        "abandoned intent has an unknown outcome; authenticated "
                        "reconciliation evidence is required (fail closed)"
                    )
                self._require_reconciliation(reconciliation, result_sha256)
            elif row.get("state") not in {"in_flight", "abandoned"}:
                raise EffectIntentError("intent cannot commit from its current state")
            row["state"] = "committed"
            row["result_sha256"] = result_sha256
            self._store(document)
            return EffectIntent(idempotency_key, execution_id, str(row["effect"]), tuple(row["scopes"]),
                                "committed", int(row["attempt"]), result_sha256, None)

    def _require_reconciliation(self, reconciliation: Mapping[str, object], result_sha256: str) -> None:
        authority = str(reconciliation.get("authority", ""))
        if not authority or (
            self._reconciliation_authorities
            and authority not in self._reconciliation_authorities
        ):
            raise EffectIntentError("reconciliation requires a trusted host-owned authority")
        if reconciliation.get("observed_outcome") != "effect_occurred":
            raise EffectIntentError("reconciliation must record a trusted observed outcome")
        if reconciliation.get("evidence_sha256") != result_sha256:
            raise EffectIntentError("reconciliation evidence does not bind the committed result")

    def fail(self, *, idempotency_key: str, execution_id: str, failure_type: str) -> EffectIntent:
        with FileLock(self.lock_path, timeout_seconds=10):
            document = self._load()
            row = self._find(document, idempotency_key)
            if row is None:
                raise EffectIntentError("cannot fail an intent that was never recorded")
            if row.get("execution_id") != execution_id:
                raise EffectIntentError("intent is owned by a different execution")
            if row.get("state") not in {"in_flight", "failed"}:
                raise EffectIntentError("intent failure cannot rewrite a committed or uncertain result")
            row["state"] = "failed"
            row["failure_type"] = str(failure_type)[:200]
            self._store(document)
            return EffectIntent(idempotency_key, execution_id, str(row["effect"]), tuple(row["scopes"]),
                                "failed", int(row["attempt"]), None, str(failure_type)[:200])

    def reclaim_in_flight(self, *, execution_id: str) -> tuple[str, ...]:
        """Reclaim in-flight intents for an execution that is no longer running.

        Called on restart reconstruction: an in-flight intent whose owning
        execution is gone is marked ``abandoned``. This means indeterminate,
        not retry-safe: the effect may have occurred before its receipt persisted.
        Preserve the exact intent until the canonical effect owner reconciles it.
        """
        reclaimed = []
        with FileLock(self.lock_path, timeout_seconds=10):
            document = self._load()
            for row in document["intents"]:
                if row.get("execution_id") == execution_id and row.get("state") == "in_flight":
                    row["state"] = "abandoned"
                    reclaimed.append(str(row["idempotency_key"]))
            if reclaimed:
                self._store(document)
        return tuple(reclaimed)

    def checkpoint(self, *, execution_id: str, name: str, state: Mapping[str, object]) -> dict[str, object]:
        """Record a named, bounded, content-addressed resume checkpoint."""
        if type(name) is not str or not name.strip() or len(name) > 200:
            raise EffectIntentError("checkpoint name must be bounded nonempty text")
        if type(execution_id) is not str or not execution_id.strip():
            raise EffectIntentError("checkpoint requires an execution id")
        import hashlib
        body = {"schema_version": CHECKPOINT_SCHEMA_VERSION, "execution_id": execution_id,
                "name": name, "state": dict(state), "authority_granted": False}
        image = bounded_canonical_json_bytes(body, max_bytes=1024 * 1024)
        body["checkpoint_sha256"] = hashlib.sha256(image).hexdigest()
        with FileLock(self.lock_path, timeout_seconds=10):
            document = self._load()
            document["checkpoints"] = [row for row in document["checkpoints"]
                                       if not (row.get("execution_id") == execution_id and row.get("name") == name)]
            document["checkpoints"].append(body)
            self._store(document)
        return body

    def resume_from(self, *, execution_id: str, name: str) -> dict[str, object] | None:
        """Read the exact latest checkpoint for an execution and name."""
        document = self._load()
        return next((row for row in reversed(document["checkpoints"])
                     if row.get("execution_id") == execution_id and row.get("name") == name), None)
