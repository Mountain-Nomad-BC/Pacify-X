"""Admitted planning corpus and the v1 punch-card ledger.

This module implements locked cards BASE-003 and BASE-004.

BASE-003 - admit and deduplicate the planning corpus. Every archive under the
resource root is fingerprinted by content, and archives that carry an identical
payload collapse onto a single admitted requirement source. The point is not
tidiness: it is that a duplicated archive must never become a duplicated
requirement, because two copies of the same plan read as two independent
sources of truth and silently multiply acceptance criteria.

BASE-004 - the v1 architecture change ledger. All punch cards publish owner,
dependencies, acceptance, rollback and source traceability, and the dependency
graph is validated as acyclic with resolvable edges and no ownerless card.

Both artifacts are pure functions of the archive on disk. They are deterministic
and digest-bound, so regenerating them from the same archive produces the same
bytes, and a drift between the ledger and the archive is detectable.
"""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

CORPUS_SCHEMA = "px.plan-corpus/1.0"
LEDGER_SCHEMA = "px.punch-card-ledger/1.0"
STATUS_SCHEMA = "px.punch-card-status/2.0"
CORPUS_RELATIVE = Path("registry/plan_corpus.json")
LEDGER_RELATIVE = Path("registry/punch_card_ledger.json")
CURRENT_STATUS_RELATIVE = Path("registry/planning/rev1xx/current-status.json")
FOUNDATION_NAMESPACE = "registry/planning/rev1xx/foundation/"
FOUNDATION_BINDING = "foundation_status_authority"
FOUNDATION_GIT_CRITERIA = {
    "BASE-001": frozenset({"clean working tree proven", "commit/tree/package versions recorded", "rollback tag/worktree created"}),
    "BASE-002": frozenset({"decision receipt names v1 starting commit"}),
}

# BASE-003 anticipates this many unique payloads. It is recorded and compared,
# never forced: if the measured count differs, the difference is a finding.
EXPECTED_UNIQUE_PAYLOADS = 8


class PlanRegistryError(ValueError):
    """Raised when the corpus or card ledger is invalid."""


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value: Any) -> str:
    return _sha256_bytes(_canonical(value).encode("utf-8"))


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PlanRegistryError("duplicate JSON field")
        result[key] = value
    return result


def _write_digest_bound(target: Path, body: dict[str, Any]) -> Path:
    payload = dict(body)
    payload.pop("artifact_sha256", None)
    payload["artifact_sha256"] = _digest(payload)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".new")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(target)
    return target


# --- BASE-003: corpus admission -------------------------------------------


@dataclass(frozen=True)
class ArchiveFingerprint:
    name: str
    file_count: int
    byte_count: int
    payload_sha256: str

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "file_count": self.file_count,
            "byte_count": self.byte_count,
            "payload_sha256": self.payload_sha256,
        }


def fingerprint_archive(directory: Path) -> ArchiveFingerprint:
    """Content fingerprint of one archive.

    The digest covers each file's repository-relative path together with the
    sha256 of its bytes, and accumulates in sorted path order so the result is
    order-independent and reproducible. A pure content hash would be enough to
    find byte-identical copies; including the path means two archives that
    happen to hold the same bytes under different internal layouts are NOT
    collapsed, which is the conservative direction.
    """
    directory = Path(directory).resolve(strict=True)
    tree = hashlib.sha256()
    files = 0
    total = 0
    for path in sorted(directory.rglob("*")):
        if not path.is_file():
            continue
        data = path.read_bytes()
        relative = path.relative_to(directory).as_posix()
        tree.update(relative.encode("utf-8"))
        tree.update(b"\0")
        tree.update(bytes.fromhex(_sha256_bytes(data)))
        tree.update(b"\0")
        files += 1
        total += len(data)
    return ArchiveFingerprint(
        name=directory.name,
        file_count=files,
        byte_count=total,
        payload_sha256=tree.hexdigest(),
    )


def admit_corpus(resource_root: Path) -> dict[str, Any]:
    """Fingerprint every archive and collapse identical payloads to one source."""
    resource_root = Path(resource_root).resolve(strict=True)
    archives = [
        fingerprint_archive(path)
        for path in sorted(resource_root.iterdir())
        if path.is_dir()
    ]
    sources: dict[str, dict[str, Any]] = {}
    for archive in archives:
        entry = sources.setdefault(
            archive.payload_sha256,
            {
                "payload_sha256": archive.payload_sha256,
                # The alphabetically first archive name is the admitted
                # requirement source. Duplicates are recorded against it so the
                # duplicate never becomes a second source of truth.
                "admitted_source": archive.name,
                "duplicate_copies": [],
                "file_count": archive.file_count,
                "byte_count": archive.byte_count,
            },
        )
        if archive.name != entry["admitted_source"]:
            entry["duplicate_copies"].append(archive.name)
        entry["duplicate_copies"] = sorted(set(entry["duplicate_copies"]))
    ordered = [sources[key] for key in sorted(sources)]
    duplicates = [entry for entry in ordered if entry["duplicate_copies"]]
    body = {
        "schema_version": CORPUS_SCHEMA,
        "archive_count": len(archives),
        "unique_payload_count": len(ordered),
        "expected_unique_payload_count": EXPECTED_UNIQUE_PAYLOADS,
        # A variance is a finding to carry forward, not a number to reconcile by
        # assuming the plan author was right.
        "unique_payload_matches_expectation": len(ordered) == EXPECTED_UNIQUE_PAYLOADS,
        "duplicate_payload_count": len(duplicates),
        "archives": [archive.to_json() for archive in archives],
        "admitted_sources": ordered,
    }
    body["corpus_sha256"] = _digest(body)
    return body


def write_corpus(resource_root: Path, repository_root: Path) -> Path:
    body = admit_corpus(resource_root)
    return _write_digest_bound(Path(repository_root) / CORPUS_RELATIVE, body)


CURRENT_CORPUS_SCHEMA = "px.current-plan-corpus/1.0"


def inventory_current_corpus(resource_root: Path) -> dict[str, Any]:
    """Measure every current reference file; duplicate bytes share one source ID.

    This inventories candidate input, never admits implementation or grants
    acceptance. Root files and nested files are equally represented.
    """
    from .archive_io import reject_path_links

    resource_root = Path(resource_root).absolute()
    reject_path_links(resource_root)
    resource_root = resource_root.resolve(strict=True)
    if not resource_root.is_dir():
        raise PlanRegistryError("reference root must be a directory")
    files = []
    sources: dict[str, dict[str, Any]] = {}
    for path in sorted(resource_root.rglob("*")):
        reject_path_links(path)
        if not path.is_file():
            continue
        data = path.read_bytes()
        relative = path.relative_to(resource_root).as_posix()
        digest = _sha256_bytes(data)
        files.append({"path": relative, "bytes": len(data), "sha256": digest,
                      "source_id": "sha256:" + digest})
        source = sources.setdefault(digest, {"source_id": "sha256:" + digest,
                                            "bytes": len(data), "paths": []})
        source["paths"].append(relative)
    if not files:
        raise PlanRegistryError("reference corpus is empty")
    body = {"schema_version": CURRENT_CORPUS_SCHEMA,
            "validation_basis": "current_implementation",
            "historical_expectations": "reference_only",
            "admission_role": "candidate_inventory_only",
            "file_count": len(files), "byte_count": sum(row["bytes"] for row in files),
            "unique_content_count": len(sources), "files": files,
            "content_sources": [sources[key] for key in sorted(sources)]}
    body["corpus_sha256"] = _digest(body)
    return body


def admit_current_corpus(resource_root: Path, repository_root: Path) -> dict[str, Any]:
    """Publish an immutable inventory after two matching current measurements."""
    from .archive_io import reject_path_links

    root = Path(repository_root).resolve(strict=True)
    policy = _planning_object(root / "policies/rev1xx-validation.json")
    _require_current_campaign(policy)
    body = inventory_current_corpus(resource_root)
    if inventory_current_corpus(resource_root) != body:
        raise PlanRegistryError("reference corpus changed during admission")
    target = root / "registry/planning/rev1xx" / ("corpus-" + body["corpus_sha256"] + ".json")
    reject_path_links(target)
    rendered = (_canonical(body) + "\n").encode("utf-8")
    if target.exists():
        if target.read_bytes() != rendered:
            raise PlanRegistryError("admitted current corpus bytes differ")
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as output:
            output.write(rendered)
    return {"valid": True, "path": target.relative_to(root).as_posix(),
            "corpus_sha256": body["corpus_sha256"], "file_count": body["file_count"],
            "byte_count": body["byte_count"], "unique_content_count": body["unique_content_count"],
            "admission_role": body["admission_role"], "implementation_integrated": False}


REQUIREMENT_TRACE_SCHEMA = "px.current-requirement-trace/1.0"
_EXTERNAL_PACK = "PX_V1_EXTERNAL_INTEGRATION_EXECUTION_PACK"
_CANDIDATE_PACK = "PX_39_CANDIDATE_IMPLEMENTATION_ASSIST_PACK"


def _current_requirement_records(trace: dict[str, Any], matrix: dict[str, Any],
                                 routing: dict[str, Any], ledger: dict[str, Any]) -> list[dict[str, Any]]:
    cards = {row["card_id"]: row for row in ledger["cards"]}
    candidates = matrix.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != 39:
        raise PlanRegistryError("current candidate matrix must account for39candidates")
    candidates_by_id = {row["id"]: row for row in candidates}
    if len(candidates_by_id) != 39:
        raise PlanRegistryError("duplicate candidate IDs")
    source_rows = trace.get("records")
    bindings = routing.get("bindings")
    if (not isinstance(source_rows, list) or len(source_rows) != 118
            or routing.get("schema_version") != "px.current-requirement-routing/1.0"
            or not isinstance(bindings, dict)):
        raise PlanRegistryError("requirement trace/routing denominator is invalid")
    seen = set()
    records = []
    totals = {_EXTERNAL_PACK: 0, _CANDIDATE_PACK: 0}
    for source in source_rows:
        pack, source_id = source["source_pack"], source["source_id"]
        if pack not in totals or (pack, source_id) in seen:
            raise PlanRegistryError("unknown source pack or duplicate requirement ID")
        seen.add((pack, source_id))
        totals[pack] += 1
        assigned = bindings.get(source_id)
        if (not isinstance(assigned, list) or not assigned or len(set(assigned)) != len(assigned)
                or any(card not in cards or cards[card]["wave"] != source["final_wave"] for card in assigned)):
            raise PlanRegistryError("requirement has missing, unknown or conflicting card/wave assignment")
        candidate = candidates_by_id.get(source_id) if pack == _CANDIDATE_PACK else None
        if pack == _CANDIDATE_PACK and candidate is None:
            raise PlanRegistryError("candidate source is missing from current matrix")
        title = source["title"] or (candidate or {}).get("capability")
        if not isinstance(title, str) or not title.strip():
            raise PlanRegistryError("requirement intent is missing")
        targets = source["target_paths"]
        if not isinstance(targets, list) or not targets:
            raise PlanRegistryError("requirement landing scope is missing")
        row = {"requirement_id": pack + ":" + source_id, "source_id": source_id,
               "source_pack": pack, "intent": title, "wave": source["final_wave"],
               "card_ids": assigned, "canonical_card_owners": sorted({cards[card]["owner"] for card in assigned}),
               "requested_targets": targets, "source_disposition": source.get("disposition"),
               "implementation_status": "pending", "acceptance_evidence": [],
               "rollback": sorted({cards[card]["rollback"] for card in assigned})}
        if candidate:
            row["candidate_requirements"] = {key: candidate.get(key) for key in
                ["acceptance", "implementation", "guardrails", "license", "method", "source", "source_paths", "px_extend", "px_new"]}
            if source_id == "P0-08":
                row["owner_exception"] = "Git implementation explicitly deferred by owner; file checkpoints remain in scope"
        records.append(row)
    if totals != {_EXTERNAL_PACK: 79, _CANDIDATE_PACK: 39} or set(bindings) != {row["source_id"] for row in source_rows}:
        raise PlanRegistryError("source requirements or routing do not account for79findings and39candidates")
    return records


def admit_current_requirement_trace(root: Path, *, trace_path: Path,
                                    candidate_path: Path, routing_path: Path,
                                    trace_sha256: str, candidate_sha256: str) -> dict[str, Any]:
    """Bind current requirement assignments; never inherit implementation claims."""
    from .archive_io import reject_path_links
    from .json_io import read_bounded_bytes

    root = Path(root).resolve(strict=True)
    _require_current_campaign(_planning_object(root / "policies/rev1xx-validation.json"))
    ledger = _planning_object(root / LEDGER_RELATIVE)
    _require_valid_ledger(ledger)
    cards = {row["card_id"]: row for row in ledger["cards"]}
    inputs = []
    documents = []
    for path, expected in [(trace_path, trace_sha256), (candidate_path, candidate_sha256),
                           (routing_path, None)]:
        path = Path(path)
        reject_path_links(path)
        data = read_bounded_bytes(path, max_bytes=8 * 1024 * 1024)
        digest = _sha256_bytes(data)
        if expected is not None and digest != expected:
            raise PlanRegistryError("requirement input hash mismatch")
        value = json.loads(data, object_pairs_hook=_unique_object)
        if not isinstance(value, dict):
            raise PlanRegistryError("requirement input must be an object")
        inputs.append((path, data, digest))
        documents.append(value)
    trace, matrix, routing = documents
    records = _current_requirement_records(trace, matrix, routing, ledger)
    for path, data, digest in inputs:
        if read_bounded_bytes(path, max_bytes=8 * 1024 * 1024) != data:
            raise PlanRegistryError("requirement inputs changed during admission")
    directory = root / "registry/planning/rev1xx"
    reject_path_links(directory)
    directory.mkdir(parents=True, exist_ok=True)
    bound_inputs = []
    for path, data, digest in inputs:
        target = directory / ("source-" + digest + ".json")
        reject_path_links(target)
        if target.exists():
            if target.read_bytes() != data:
                raise PlanRegistryError("admitted requirement input differs")
        else:
            with target.open("xb") as output:
                output.write(data)
        bound_inputs.append({"path": target.relative_to(root).as_posix(), "sha256": digest})
    body = {"schema_version": REQUIREMENT_TRACE_SCHEMA, "base_ledger_sha256": ledger["ledger_sha256"],
            "inputs": bound_inputs, "record_count": len(records), "records": records,
            "validation_basis": "current_implementation", "inherited_implementation_claims": False}
    body["trace_sha256"] = _digest(body)
    target = directory / ("requirements-" + body["trace_sha256"] + ".json")
    reject_path_links(target)
    rendered = (_canonical(body) + "\n").encode("utf-8")
    if target.exists():
        if target.read_bytes() != rendered:
            raise PlanRegistryError("admitted requirement trace differs")
    else:
        with target.open("xb") as output:
            output.write(rendered)
    return {"valid": True, "path": target.relative_to(root).as_posix(),
            "sha256": _sha256_bytes(rendered), "requirements": len(records),
            "candidates": 39, "external_findings": 79, "implementation_verified": 0}


def requirement_report(root: Path) -> dict[str, Any]:
    """Validate portable current requirement custody and assignments."""
    from .archive_io import portable_member_name
    from .json_io import read_bounded_bytes

    root = Path(root).resolve(strict=True)
    policy = _planning_object(root / "policies/rev1xx-validation.json")
    _require_current_campaign(policy)
    binding = policy.get("requirement_trace")
    if not isinstance(binding, dict):
        raise PlanRegistryError("current requirement trace is not bound")
    relative = portable_member_name(binding["path"], allow_directory=False)
    if not relative.startswith("registry/planning/rev1xx/requirements-"):
        raise PlanRegistryError("requirement trace must be campaign-relative")
    body = _planning_object(root / relative)
    if _sha256_bytes(read_bounded_bytes(root / relative, max_bytes=8 * 1024 * 1024)) != binding["sha256"]:
        raise PlanRegistryError("current requirement trace hash mismatch")
    if body.get("schema_version") != REQUIREMENT_TRACE_SCHEMA or _digest({k:v for k,v in body.items() if k != "trace_sha256"}) != body.get("trace_sha256"):
        raise PlanRegistryError("requirement trace semantic digest mismatch")
    ledger = _planning_object(root / LEDGER_RELATIVE)
    _require_valid_ledger(ledger)
    if body["base_ledger_sha256"] != ledger["ledger_sha256"]:
        raise PlanRegistryError("requirement trace ledger binding changed")
    documents = []
    if not isinstance(body.get("inputs"), list) or len(body["inputs"]) != 3:
        raise PlanRegistryError("requirement trace must bind three source inputs")
    for item in body["inputs"]:
        path = portable_member_name(item["path"], allow_directory=False)
        if not path.startswith("registry/planning/rev1xx/source-"):
            raise PlanRegistryError("requirement input must be campaign-relative")
        documents.append(_planning_object(root / path))
        if _sha256_bytes(read_bounded_bytes(root / path, max_bytes=8 * 1024 * 1024)) != item["sha256"]:
            raise PlanRegistryError("admitted requirement source hash mismatch")
    expected_rows = _current_requirement_records(*documents, ledger)
    if (body.get("records") != expected_rows or body.get("record_count") != len(expected_rows)
            or body.get("validation_basis") != "current_implementation"
            or body.get("inherited_implementation_claims") is not False):
        raise PlanRegistryError("requirement trace differs from admitted source assignments")
    return {"valid": True, "path": relative, "requirements": body["record_count"],
            "implementation_verified": 0, "status": "all requirements assigned; implementation pending"}


# --- BASE-004: punch-card ledger ------------------------------------------


@dataclass(frozen=True)
class CardLedgerEntry:
    card_id: str
    title: str
    wave: str
    owner: str
    existing_owners: tuple[str, ...]
    candidate_new_owners: tuple[str, ...]
    depends_on: tuple[str, ...]
    acceptance: tuple[str, ...]
    rollback: str
    source: str
    source_basis: str
    outcome: str

    def to_json(self) -> dict[str, Any]:
        return {
            "card_id": self.card_id,
            "title": self.title,
            "wave": self.wave,
            "owner": self.owner,
            "existing_owners": list(self.existing_owners),
            "candidate_new_owners": list(self.candidate_new_owners),
            "depends_on": list(self.depends_on),
            "acceptance": list(self.acceptance),
            "rollback": self.rollback,
            "source": self.source,
            "source_basis": self.source_basis,
            "outcome": self.outcome,
        }


def load_cards(manifest_path: Path) -> list[CardLedgerEntry]:
    """Read the master plan card manifest into ledger entries.

    The manifest schema has no single ``owner`` key. Authority for a card is
    expressed as the union of its ``existing_owners`` and
    ``candidate_new_owners``: a card is ownerless only when BOTH are empty. An
    earlier parse read a non-existent ``owner`` key and reported all 60 cards as
    ownerless, which was a parser defect rather than a finding about the plan.
    """
    manifest_path = Path(manifest_path)
    from .archive_io import reject_path_links
    from .json_io import read_bounded_bytes
    reject_path_links(manifest_path)
    manifest_bytes = read_bounded_bytes(manifest_path, max_bytes=8 * 1024**2)
    payload = json.loads(manifest_bytes, object_pairs_hook=_unique_object)
    source = "sha256:" + _sha256_bytes(manifest_bytes)
    entries: list[CardLedgerEntry] = []
    for card in payload.get("cards", []):
        existing = tuple(map(str, card.get("existing_owners", ())))
        candidate = tuple(map(str, card.get("candidate_new_owners", ())))
        owner = ", ".join([*existing, *candidate])
        entries.append(
            CardLedgerEntry(
                card_id=str(card.get("id") or ""),
                title=str(card.get("title") or ""),
                wave=str(card.get("wave") or ""),
                owner=owner,
                existing_owners=existing,
                candidate_new_owners=candidate,
                depends_on=tuple(map(str, card.get("depends_on", ()))),
                acceptance=tuple(map(str, card.get("acceptance", ()))),
                rollback=str(card.get("rollback") or ""),
                source=source,
                source_basis=str(card.get("source_basis") or ""),
                outcome=str(card.get("outcome") or ""),
            )
        )
    return entries


def admit_card_manifest(source: Path, repository_root: Path, *, expected_sha256: str) -> Path:
    """Admit exact normative bytes; never substitute a changed reference input."""
    from .archive_io import reject_path_links
    from .json_io import read_bounded_bytes

    reject_path_links(Path(source))
    data = read_bounded_bytes(Path(source), max_bytes=8 * 1024**2)
    if _sha256_bytes(data) != expected_sha256:
        raise PlanRegistryError("card manifest differs from locked planning input")
    # Validate the complete graph before publishing an input or its receipt.
    _require_valid_ledger(build_card_ledger(load_cards(source)))
    target = Path(repository_root) / "registry/planning/rev1xx" / (expected_sha256 + ".json")
    reject_path_links(target)
    if target.exists() and target.read_bytes() != data:
        raise PlanRegistryError("admitted card manifest has been modified")
    # Check the source again: validation must not admit different bytes after a race.
    if Path(source).read_bytes() != data:
        raise PlanRegistryError("card manifest changed during admission")
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        with target.open("xb") as handle:
            handle.write(data)
    return target


def _ledger_manifest(ledger: dict[str, Any]) -> str:
    sources = {row.get("source") for row in ledger.get("cards", [])}
    if len(sources) != 1:
        raise PlanRegistryError("architecture ledger requires one admitted definition source")
    source = next(iter(sources))
    if not isinstance(source, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", source):
        raise PlanRegistryError("architecture ledger definition source is not content-bound")
    return source[7:]


def admit_architecture_decision(root: Path, *, manifest_sha256: str,
                                adr_path: str, rationale: str) -> dict[str, str]:
    """Record a new current decision, with exact prior/new input and ADR bytes."""
    from .archive_io import portable_member_name, reject_path_links
    from .json_io import read_bounded_bytes

    root = Path(root).resolve(strict=True)
    policy = _planning_object(root / "policies/rev1xx-validation.json")
    _require_current_campaign(policy)
    previous = _planning_object(root / LEDGER_RELATIVE)
    _require_valid_ledger(previous)
    prior = _ledger_manifest(previous)
    if prior == manifest_sha256:
        raise PlanRegistryError("decision admission requires an actual definition change")
    target = root / "registry/planning/rev1xx" / (manifest_sha256 + ".json")
    reject_path_links(target)
    raw = read_bounded_bytes(target, max_bytes=8 * 1024**2)
    if _sha256_bytes(raw) != manifest_sha256:
        raise PlanRegistryError("new decision manifest is not admitted")
    _require_valid_ledger(build_card_ledger(load_cards(target)))
    adr = portable_member_name(adr_path, allow_directory=False)
    if adr != adr_path or not adr.startswith("docs/adr/") or not adr.endswith(".md"):
        raise PlanRegistryError("architecture decision requires a repository ADR")
    reject_path_links(root / adr)
    text = read_bounded_bytes(root / adr, max_bytes=1024**2)
    if not text.strip() or prior.encode() not in text or manifest_sha256.encode() not in text:
        raise PlanRegistryError("ADR must name both exact prior and new manifest identities")
    if not isinstance(rationale, str) or not rationale.strip() or len(rationale) > 8192:
        raise PlanRegistryError("architecture decision requires a bounded rationale")
    body = {"schema_version":"px.architecture-decision/1.0",
            "campaign_id":policy["campaign_id"], "authority":policy["authority"],
            "prior_manifest_sha256":prior, "manifest_sha256":manifest_sha256,
            "adr":{"path":adr, "sha256":_sha256_bytes(text)}, "rationale":rationale.strip()}
    if (read_bounded_bytes(target, max_bytes=8 * 1024**2) != raw
            or read_bounded_bytes(root / adr, max_bytes=1024**2) != text
            or _planning_object(root / LEDGER_RELATIVE) != previous
            or _planning_object(root / "policies/rev1xx-validation.json") != policy):
        raise PlanRegistryError("architecture decision inputs changed during admission")
    encoded = (_canonical(body) + "\n").encode()
    digest = _sha256_bytes(encoded)
    relative = "registry/planning/rev1xx/decisions/" + digest + ".json"
    path = root / relative
    reject_path_links(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if read_bounded_bytes(path, max_bytes=1024**2) != encoded:
            raise PlanRegistryError("immutable architecture decision differs")
    else:
        with path.open("xb") as stream:
            stream.write(encoded)
    return {"path":relative, "sha256":digest}


def _architecture_decision(root: Path, binding: dict[str, str], *, prior: str,
                           manifest: str) -> dict[str, Any]:
    from .archive_io import portable_member_name, reject_path_links
    from .json_io import read_bounded_bytes

    if not isinstance(binding, dict) or set(binding) != {"path", "sha256"}:
        raise PlanRegistryError("definition changes require an admitted ADR/ledger decision")
    relative = portable_member_name(binding["path"], allow_directory=False)
    if relative != binding["path"] or not relative.startswith("registry/planning/rev1xx/decisions/"):
        raise PlanRegistryError("architecture decision is outside the admitted namespace")
    reject_path_links(root / relative)
    raw = read_bounded_bytes(root / relative, max_bytes=1024**2)
    if _sha256_bytes(raw) != binding["sha256"] or Path(relative).stem != binding["sha256"]:
        raise PlanRegistryError("architecture decision hash differs")
    body = json.loads(raw, object_pairs_hook=_unique_object)
    policy = _planning_object(root / "policies/rev1xx-validation.json")
    _require_current_campaign(policy)
    if (set(body) != {"schema_version", "campaign_id", "authority", "prior_manifest_sha256", "manifest_sha256", "adr", "rationale"}
            or body["schema_version"] != "px.architecture-decision/1.0"
            or body["campaign_id"] != policy["campaign_id"] or body["authority"] != policy["authority"]
            or body["prior_manifest_sha256"] != prior or body["manifest_sha256"] != manifest):
        raise PlanRegistryError("architecture decision does not bind this campaign and definition change")
    adr = body["adr"]
    if not isinstance(adr, dict) or set(adr) != {"path", "sha256"}:
        raise PlanRegistryError("architecture decision ADR binding is invalid")
    path = portable_member_name(adr["path"], allow_directory=False)
    if path != adr["path"] or not path.startswith("docs/adr/") or not path.endswith(".md"):
        raise PlanRegistryError("architecture decision ADR is outside its owner")
    reject_path_links(root / path)
    text = read_bounded_bytes(root / path, max_bytes=1024**2)
    if _sha256_bytes(text) != adr["sha256"] or prior.encode() not in text or manifest.encode() not in text:
        raise PlanRegistryError("architecture decision ADR bytes or identities differ")
    if not isinstance(body["rationale"], str) or not body["rationale"].strip() or len(body["rationale"]) > 8192:
        raise PlanRegistryError("architecture decision rationale is invalid")
    return body


def write_admitted_card_ledger(repository_root: Path, *, manifest_sha256: str,
                              decision: dict[str, str] | None = None) -> Path:
    """Rebuild only the owned card projection from its exact admitted input."""
    from .archive_io import reject_path_links
    from .json_io import read_bounded_bytes

    policy_path = Path(repository_root) / "policies/rev1xx-validation.json"
    if policy_path.exists():
        _require_current_campaign(_planning_object(policy_path))
    if len(manifest_sha256) != 64 or any(c not in "0123456789abcdef" for c in manifest_sha256):
        raise PlanRegistryError("invalid admitted manifest digest")
    target = Path(repository_root) / "registry/planning/rev1xx" / (manifest_sha256 + ".json")
    reject_path_links(target)
    reject_path_links(Path(repository_root) / LEDGER_RELATIVE)
    data = read_bounded_bytes(target, max_bytes=8 * 1024**2)
    if _sha256_bytes(data) != manifest_sha256:
        raise PlanRegistryError("admitted card manifest digest mismatch")
    ledger = build_card_ledger(load_cards(target))
    _require_valid_ledger(ledger)
    output = Path(repository_root) / LEDGER_RELATIVE
    if output.exists():
        previous_bytes = read_bounded_bytes(output, max_bytes=8 * 1024**2)
        previous = json.loads(previous_bytes, object_pairs_hook=_unique_object)
        prior = _ledger_manifest(previous)
        if prior != manifest_sha256:
            _require_valid_ledger(previous)
            _architecture_decision(Path(repository_root), decision, prior=prior, manifest=manifest_sha256)
            ledger["architecture_decision"] = dict(decision)
            # Retained bytes are rollback material, never an active registry
            # document with independently authoritative count fields.
            history = Path(repository_root) / "registry/planning/rev1xx/ledger-history" / (_sha256_bytes(previous_bytes) + ".retained")
            reject_path_links(history)
            history.parent.mkdir(parents=True, exist_ok=True)
            if history.exists() and history.read_bytes() != previous_bytes:
                raise PlanRegistryError("prior ledger preservation differs")
            if not history.exists():
                with history.open("xb") as stream:
                    stream.write(previous_bytes)
        elif "architecture_decision" in previous:
            binding = previous["architecture_decision"]
            recorded = _planning_object(Path(repository_root) / binding["path"])
            _architecture_decision(Path(repository_root), binding, prior=recorded["prior_manifest_sha256"], manifest=manifest_sha256)
            ledger["architecture_decision"] = dict(binding)
    if "architecture_decision" in ledger:
        ledger.pop("ledger_sha256", None)
        ledger["ledger_sha256"] = _digest(ledger)
    if target.read_bytes() != data:
        raise PlanRegistryError("admitted card manifest changed during generation")
    return _write_digest_bound(output, ledger)


def _topological_order(entries: list[CardLedgerEntry]) -> list[str]:
    """Kahn's algorithm; raises if the dependency graph contains a cycle."""
    indegree = {entry.card_id: 0 for entry in entries}
    dependents: dict[str, list[str]] = {entry.card_id: [] for entry in entries}
    known = set(indegree)
    for entry in entries:
        for dependency in entry.depends_on:
            if dependency not in known:
                raise PlanRegistryError(
                    f"card {entry.card_id} depends on unknown card {dependency}"
                )
            indegree[entry.card_id] += 1
            dependents[dependency].append(entry.card_id)
    ready = sorted(key for key, value in indegree.items() if value == 0)
    order: list[str] = []
    while ready:
        current = ready.pop(0)
        order.append(current)
        for dependent in sorted(dependents[current]):
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                ready.append(dependent)
        ready.sort()
    if len(order) != len(indegree):
        remaining = sorted(set(indegree) - set(order))
        raise PlanRegistryError(f"card dependency graph contains a cycle: {remaining}")
    return order


def build_card_ledger(entries: Iterable[CardLedgerEntry]) -> dict[str, Any]:
    """Build and validate the v1 architecture change ledger."""
    entries = list(entries)
    if not entries:
        raise PlanRegistryError("punch-card ledger requires at least one card")
    identifiers = [entry.card_id for entry in entries]
    duplicates = sorted({item for item in identifiers if identifiers.count(item) > 1})
    if duplicates:
        raise PlanRegistryError(f"duplicate card identifiers: {duplicates}")
    ownerless = sorted(entry.card_id for entry in entries if not entry.owner.strip())
    order = _topological_order(entries)
    by_wave: dict[str, list[str]] = {}
    for entry in entries:
        by_wave.setdefault(entry.wave, []).append(entry.card_id)
    for cards in by_wave.values():
        cards.sort()
    ready = sorted(
        entry.card_id
        for entry in entries
        if all(
            dependency in order
            and order.index(dependency) < order.index(entry.card_id)
            for dependency in entry.depends_on
        )
    )
    body = {
        "schema_version": LEDGER_SCHEMA,
        "card_count": len(entries),
        "ownerless_cards": ownerless,
        "waves": {wave: by_wave[wave] for wave in sorted(by_wave)},
        "topological_order": order,
        "topologically_unblocked_by_graph_shape": ready,
        "cards": [entry.to_json() for entry in sorted(entries, key=lambda item: item.card_id)],
    }
    body["ledger_sha256"] = _digest(body)
    return body


def write_card_ledger(manifest_path: Path, repository_root: Path, *,
                      decision: dict[str, str] | None = None) -> Path:
    if (Path(repository_root) / "policies/rev1xx-validation.json").exists():
        from .json_io import read_bounded_bytes
        raw = read_bounded_bytes(Path(manifest_path), max_bytes=8 * 1024**2)
        digest = _sha256_bytes(raw)
        admit_card_manifest(manifest_path, repository_root, expected_sha256=digest)
        return write_admitted_card_ledger(repository_root, manifest_sha256=digest, decision=decision)
    body = build_card_ledger(load_cards(manifest_path))
    return _write_digest_bound(Path(repository_root) / LEDGER_RELATIVE, body)


def _foundation_invariant_probe(root: Path, manifest: Path, policy: dict[str, Any]) -> dict[str, bool]:
    """Exercise current owners in a registered disposable tree; no build/install.

    Deliberately inconsistent release-state records are negative test inputs,
    never evidence that a product was built, installed or certified.
    """
    import tempfile
    from uuid import uuid4
    from .resource_lifecycle import ResourceManager
    from .release_campaign import (clear_release_identity, release_state_relative,
                                   STAGES, STATE_PATH, _sha, _validate)

    manager = ResourceManager(root / ".agentic_engineering_os_px/resource-lifecycle/ledger.json")
    resource = manager.create_workspace(Path(tempfile.gettempdir()), project_id="pacify-x",
        run_id="foundation-probe-"+uuid4().hex, lane_id="current-foundation",
        creator="runtime.plan_registry", prefix="px-current-foundation-")
    project = Path(resource.path) / "project"
    try:
        (project / "policies").mkdir(parents=True)
        (project / "policies/rev1xx-validation.json").write_text(_canonical(policy), encoding="utf-8")
        processing = project / ".agentic_engineering_os_px/processing-order"
        processing.mkdir(parents=True)
        (processing / "repair-campaign.json").write_text(_canonical({"campaign_id":policy["campaign_id"], "phase":"repair"}), encoding="utf-8")
        source = project / "original.json"
        source.write_bytes(manifest.read_bytes())
        prior = _sha256_bytes(source.read_bytes())
        admit_card_manifest(source, project, expected_sha256=prior)
        ledger = write_admitted_card_ledger(project, manifest_sha256=prior)
        before = ledger.read_bytes()
        value = json.loads(source.read_bytes(), object_pairs_hook=_unique_object)
        value["cards"][0]["outcome"] += " Bounded current negative reproduction."
        changed = project / "changed.json"
        changed.write_text(_canonical(value), encoding="utf-8")
        new = _sha256_bytes(changed.read_bytes())
        admit_card_manifest(changed, project, expected_sha256=new)
        for publish in (lambda:write_admitted_card_ledger(project, manifest_sha256=new),
                        lambda:write_card_ledger(changed, project)):
            try:
                publish()
            except PlanRegistryError:
                if ledger.read_bytes() != before:
                    raise PlanRegistryError("decision rejection changed current ledger bytes")
            else:
                raise PlanRegistryError("architecture decision guard allowed an unapproved definition change")
        cid = "current-negative-reproduction"
        clear_release_identity(project, campaign_id=cid)
        current = project / release_state_relative(project)
        original = json.loads(current.read_bytes())
        for state in ("active", "failed", "certified"):
            body = deepcopy(original)
            body.update(state=state, apply_count=1, repair_campaign_id="inconsistent-other-repair")
            identity = {"schema_version":"px.release-identity-kernel/2.0",
                        "campaign_id":cid, "repair_campaign_id":body["repair_campaign_id"]}
            identity["release_identity_sha256"] = _sha(identity)
            body["identity"] = identity
            body["stages"] = {name:{"status":("passed" if state=="certified" else "failed" if state=="failed" and i==0 else "pending"), "claim_id":None}
                              for i,name in enumerate(STAGES)}
            _validate(body)
            current.write_text(_canonical(body), encoding="utf-8")
            prior_bytes = current.read_bytes()
            try:
                clear_release_identity(project, campaign_id="replacement-negative-reproduction")
            except ValueError:
                if current.read_bytes() != prior_bytes:
                    raise PlanRegistryError("release rejection erased prior state")
            else:
                raise PlanRegistryError("current release owner erased applied state from another repair")
        current.write_text(_canonical(original), encoding="utf-8")
        legacy = project / STATE_PATH
        legacy.write_bytes(prior_bytes)
        clear_release_identity(project, campaign_id=cid)
        if legacy.read_bytes() != prior_bytes:
            raise PlanRegistryError("fresh release owner modified the other namespace")
        return {"decision_guard":True, "terminal_preservation":True, "release_isolation":True}
    finally:
        cleanup = manager.reclaim_ephemeral_path(resource.resource_id, reason="current_foundation_probe_complete")
        if cleanup.resources_reclaimed != 1 or cleanup.errors:
            raise PlanRegistryError("foundation probe workspace did not close")


def foundation_report(root: Path, *, reference_root: Path) -> dict[str, Any]:
    """Current W0 criteria, with exact Git exceptions and no inherited status.

    This is software proof, not an acceptance-state mutation or certification.
    Current status authority can register these independently exercised checks.
    """
    from .release_repository_context import validate_release_gate_repository_context
    from .release_campaign import release_campaign_status, release_state_relative
    from .source_freeze import read_freeze, _versions
    from .json_io import read_bounded_bytes
    from .archive_io import reject_path_links

    root = Path(root).resolve(strict=True)
    policy = _planning_object(root / "policies/rev1xx-validation.json")
    _require_current_campaign(policy)
    ledger = _planning_object(root / LEDGER_RELATIVE)
    _require_valid_ledger(ledger)
    manifest_sha = _ledger_manifest(ledger)
    manifest = root / "registry/planning/rev1xx" / (manifest_sha + ".json")
    reject_path_links(manifest)
    if _sha256_bytes(read_bounded_bytes(manifest, max_bytes=8*1024**2)) != manifest_sha:
        raise PlanRegistryError("current foundation declaration source differs")
    expected = build_card_ledger(load_cards(manifest))
    if any(ledger.get(key) != value for key,value in expected.items() if key != "ledger_sha256"):
        raise PlanRegistryError("foundation ledger differs from admitted definitions")
    if "architecture_decision" in ledger:
        binding = ledger["architecture_decision"]
        decision = _planning_object(root / binding["path"])
        _architecture_decision(root, binding, prior=decision["prior_manifest_sha256"], manifest=manifest_sha)
    waves = wave_report(root)
    if not waves["valid"]:
        raise PlanRegistryError("current foundation wave map is invalid")
    requirement_report(root)
    corpus = inventory_current_corpus(reference_root)
    corpus_path = "registry/planning/rev1xx/corpus-" + corpus["corpus_sha256"] + ".json"
    if _planning_object(root / corpus_path) != corpus:
        raise PlanRegistryError("admitted current corpus differs from live reference bytes")
    context = validate_release_gate_repository_context(root)
    if not context["valid"]:
        raise PlanRegistryError("current foundation source custody is invalid: " + "; ".join(context["errors"]))
    capture = read_freeze(root, relative=Path(policy["source_anchor"]["path"]))
    versions = _versions(root)
    if any(capture["versions"].get(key) != versions.get(key) for key in ("distribution_package", "extension_package")):
        raise PlanRegistryError("current package versions differ from the recorded starting source")
    release = release_campaign_status(root)
    if not release["valid"] or release["repair_campaign_id"] != policy["campaign_id"] or release["path"] != release_state_relative(root).as_posix():
        raise PlanRegistryError("current release namespace is not coherent")
    probe = _foundation_invariant_probe(root, manifest, policy)
    if (_planning_object(root / "policies/rev1xx-validation.json") != policy
            or _planning_object(root / LEDGER_RELATIVE) != ledger
            or release_campaign_status(root) != release):
        raise PlanRegistryError("foundation authority or release inputs changed during verification")
    git_criteria = FOUNDATION_GIT_CRITERIA
    proven = {"BASE-002":{"no mixed old/new release campaign", "terminal campaigns remain terminal"},
              "BASE-003":{"every source pack hash recorded", "duplicate payloads do not create duplicate requirements"},
              "BASE-004":{"zero ownerless cards", "DAG acyclic", "decision changes require ADR/ledger update"}}
    cards = {}
    for card in ledger["cards"]:
        cid = card["card_id"]
        if card["wave"] != "W0":
            continue
        rows = []
        for criterion in card["acceptance"]:
            if criterion in git_criteria.get(cid, set()):
                rows.append({"criterion":criterion, "result":"DEFERRED", "authority":"Explicit owner Git hold; literal Git acceptance remains unsatisfied"})
            elif criterion in proven.get(cid, set()):
                rows.append({"criterion":criterion, "result":"PASS"})
            else:
                raise PlanRegistryError("foundation criterion has no independent registered implementation: " + criterion)
        cards[cid] = rows
    if set(cards) != {"BASE-001", "BASE-002", "BASE-003", "BASE-004"}:
        raise PlanRegistryError("foundation requires exactly the locked four W0 cards")
    if inventory_current_corpus(reference_root) != corpus:
        raise PlanRegistryError("reference inputs changed during foundation verification")
    return {"schema_version":"px.current-foundation-proof/1.0", "valid":True,
            "campaign_id":policy["campaign_id"], "validation_basis":"current_implementation",
            "historical_prerequisites":False, "base_ledger_sha256":ledger["ledger_sha256"],
            "manifest_sha256":manifest_sha, "corpus_sha256":corpus["corpus_sha256"],
            "criteria":cards, "current_replacements":{"source_custody":True, "package_versions":True, **probe},
            "git_acceptance_satisfied":False, "acceptance_state_changed":False,
            "claim_scope":"Current non-Git W0 software checks only; no build, install or certification"}


def build_wave_map(spec: dict[str, Any], ledger: dict[str, Any]) -> dict[str, Any]:
    """Validate the locked twelve-wave order against actual card ownership."""
    _require_valid_ledger(ledger)
    order = [f"W{number}" for number in range(12)]
    if not isinstance(spec, dict) or set(spec) != {"schema_version", "waves"}:
        raise PlanRegistryError("wave specification schema is invalid")
    waves = spec["waves"]
    if spec["schema_version"] != "px.rev1xx-waves/1.0" or not isinstance(waves, list):
        raise PlanRegistryError("wave specification version is invalid")
    if len(waves) != 12 or any(not isinstance(row, dict) for row in waves):
        raise PlanRegistryError("locked plan requires twelve waves W0 through W11")
    if [row.get("id") for row in waves] != order:
        raise PlanRegistryError("wave numbering/order contradicts the locked plan")
    for index, row in enumerate(waves):
        if set(row) != {"id", "name", "goal", "gate", "depends_on", "outputs"}:
            raise PlanRegistryError("wave metadata fields are invalid")
        if any(not isinstance(row[key], str) or not row[key].strip() for key in ("name", "goal", "gate")):
            raise PlanRegistryError("wave metadata requires a name, goal and gate")
        if row["depends_on"] != ([] if index == 0 else [order[index - 1]]):
            raise PlanRegistryError("wave prerequisites contradict the locked sequence")
        outputs = row["outputs"]
        if not isinstance(outputs, list) or not outputs or any(not isinstance(value, str) or not value.strip() for value in outputs):
            raise PlanRegistryError("wave outputs must be nonempty strings")
    cards = {card["card_id"]: card for card in ledger["cards"]}
    membership: dict[str, list[str]] = {}
    for card in cards.values():
        wave = card["wave"]
        if wave not in order:
            raise PlanRegistryError("card belongs to an unknown wave")
        membership.setdefault(wave, []).append(card["card_id"])
        for dependency in card["depends_on"]:
            if order.index(cards[dependency]["wave"]) > order.index(wave):
                raise PlanRegistryError("card dependency points into a later wave")
    if {wave: sorted(ids) for wave, ids in membership.items()} != ledger["waves"]:
        raise PlanRegistryError("ledger wave membership differs from its cards")
    body = {"schema_version": "px.canonical-wave-map/1.0", "wave_order": order,
            "base_ledger_sha256": ledger["ledger_sha256"],
            "waves": [{**deepcopy(row), "cards": sorted(membership.get(row["id"], []))} for row in waves],
            "acceptance_boundary": "Wave metadata is descriptive; current acceptance authority governs advancement"}
    body["wave_map_sha256"] = _digest(body)
    return body


def wave_report(root: Path) -> dict[str, Any]:
    """Read the admitted canonical wave input through the normal runtime seam."""
    from .archive_io import portable_member_name, reject_path_links
    from .json_io import read_bounded_bytes

    try:
        root = Path(root).resolve(strict=True)
        policy_path = root / "policies/rev1xx-validation.json"
        reject_path_links(policy_path)
        policy = json.loads(read_bounded_bytes(policy_path, max_bytes=1024 * 1024), object_pairs_hook=_unique_object)
        binding = policy["canonical_waves"]
        if not isinstance(binding, dict) or set(binding) != {"path", "sha256"}:
            raise PlanRegistryError("canonical wave input binding is invalid")
        relative = portable_member_name(binding["path"], allow_directory=False)
        if relative != binding["path"] or not relative.startswith("registry/planning/rev1xx/"):
            raise PlanRegistryError("canonical waves must be an admitted repository-relative input")
        target = root / relative
        reject_path_links(target)
        raw = read_bounded_bytes(target, max_bytes=1024 * 1024)
        if _sha256_bytes(raw) != binding["sha256"]:
            raise PlanRegistryError("canonical wave input digest mismatch")
        ledger_path = root / LEDGER_RELATIVE
        reject_path_links(ledger_path)
        ledger = json.loads(read_bounded_bytes(ledger_path, max_bytes=8 * 1024 * 1024), object_pairs_hook=_unique_object)
        result = build_wave_map(json.loads(raw, object_pairs_hook=_unique_object), ledger)
        return {"valid": True, "source_sha256": binding["sha256"], **result}
    except (OSError, ValueError, KeyError, TypeError) as error:
        return {"valid": False, "waves": [], "errors": [f"{type(error).__name__}: {error}"]}


@dataclass(frozen=True)
class StatusOwnerDecision:
    """A host-admitted decision scoped to one transition and exact source/plan."""

    card_id: str
    requested_status: str
    campaign_id: str
    source_revision: str
    base_ledger_sha256: str
    authority: str


@dataclass(frozen=True)
class CriterionDeferral:
    """Explicit host-admitted owner exception; never literal acceptance."""

    card_id: str
    criterion: str
    campaign_id: str
    source_revision: str
    base_ledger_sha256: str
    authority: str
    reason: str


@dataclass(frozen=True)
class StatusAuthority:
    """Trusted host inputs, never constructed from an untrusted status overlay.

    Owners register criterion evaluators at the production seam that can prove
    the criterion. There is deliberately no default PASS evaluator. Decision
    IDs and prior states come from admitted owner history. A source callback
    lets each read check the current revision rather than a cached assertion.
    This object is an authority boundary, not a cryptographic JSON signature.
    """

    root: Path
    campaign_id: str
    source_revision: Callable[[], str]
    prior_statuses: dict[str, str] = field(default_factory=dict)
    owner_decisions: dict[str, StatusOwnerDecision] = field(default_factory=dict)
    evaluators: dict[tuple[str, str], Callable[[list[Path]], bool | None]] = field(default_factory=dict)
    blocking_cards: frozenset[str] = frozenset()
    criterion_deferrals: dict[tuple[str, str], CriterionDeferral] = field(default_factory=dict)
    additional_requirements: dict[str, tuple[Callable[[list[Path]], bool | None], ...]] = field(default_factory=dict)


class _StatusView(dict):
    """An in-process validated projection; JSON serialization cannot grant trust."""


_STATUSES = frozenset({
    "planned", "in_progress", "partial_verified", "accepted", "blocked",
    "superseded", "deferred", "rejected",
})
_TRANSITIONS = {
    "planned": {"in_progress", "blocked", "deferred", "rejected"},
    "in_progress": {"partial_verified", "blocked", "deferred", "rejected"},
    "partial_verified": {"partial_verified", "accepted", "in_progress", "blocked", "deferred", "rejected"},
    "accepted": {"superseded", "blocked"},
    "blocked": {"in_progress", "blocked", "deferred", "rejected"},
    "superseded": {"blocked"}, "deferred": {"blocked"}, "rejected": {"blocked"},
}


def _status(value: Any) -> str:
    value = "partial_verified" if value == "narrowly_verified" else value
    if not isinstance(value, str) or value not in _STATUSES:
        raise PlanRegistryError("unknown status vocabulary")
    return value


def _evidence_paths(root: Path, rows: Any) -> dict[str, Path]:
    from .archive_io import portable_member_name, reject_path_links

    if not isinstance(rows, list) or not rows:
        raise PlanRegistryError("status requires hashed evidence")
    found: dict[str, Path] = {}
    identities: set[str] = set()
    remaining = 512 * 1024 * 1024
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"path", "sha256"}:
            raise PlanRegistryError("evidence schema is invalid")
        relative = row["path"]
        if not isinstance(relative, str) or not relative or "\\" in relative:
            raise PlanRegistryError("evidence path must be repository-relative")
        locator = Path(relative)
        if portable_member_name(relative, allow_directory=False) != relative:
            raise PlanRegistryError("evidence path is not canonical")
        if locator.is_absolute() or ":" in relative or any(part in {".", ".."} for part in relative.split("/")):
            raise PlanRegistryError("evidence path escapes the governed root")
        target = root / locator
        reject_path_links(target)
        if not target.resolve().is_relative_to(root) or not target.is_file():
            raise PlanRegistryError("evidence is missing or outside governed root")
        size = target.stat().st_size
        if size <= 0 or size > min(128 * 1024 * 1024, remaining):
            raise PlanRegistryError("evidence byte budget exceeded or empty evidence")
        digest = hashlib.sha256()
        consumed = 0
        with target.open("rb") as stream:
            while chunk := stream.read(min(1024 * 1024, size - consumed + 1)):
                consumed += len(chunk)
                if consumed > size:
                    raise PlanRegistryError("evidence changed during capture")
                digest.update(chunk)
        remaining -= consumed
        if consumed != size or row["sha256"] != digest.hexdigest():
            raise PlanRegistryError("evidence hash mismatch or empty evidence")
        if relative.casefold() in identities:
            raise PlanRegistryError("duplicate evidence reference")
        identities.add(relative.casefold())
        found[relative] = target
    return found


def apply_status(
    ledger: dict[str, Any], status_path: Path, *, authority: StatusAuthority | None = None,
) -> dict[str, Any]:
    """Apply status only through independent, revision-bound host authority.

    Legacy overlays must be migrated with actual evidence; they cannot silently
    become acceptance authority. Readiness rechecks this overlay and its proof.
    """
    _require_valid_ledger(ledger)
    if any("status" in card for card in ledger.get("cards", [])):
        raise PlanRegistryError("status must be applied to a canonical base ledger")
    status_path = Path(status_path)
    if not status_path.is_file():
        return ledger
    if authority is None:
        raise PlanRegistryError("status authority is required; legacy overlays do not unlock dependencies")
    try:
        from .archive_io import read_stream_bytes, reject_path_links

        root = authority.root.resolve(strict=True)
        reject_path_links(status_path)
        if not status_path.resolve().is_relative_to(root):
            raise PlanRegistryError("status overlay is outside the governed root")
        with status_path.open("rb") as stream:
            payload = read_stream_bytes(stream, max_bytes=4 * 1024 * 1024)
        overlay = json.loads(payload.decode("utf-8"), object_pairs_hook=_unique_object)
        fields = {"schema_version", "campaign_id", "base_ledger_sha256", "source_revision", "generator", "timestamp", "cards"}
        if not isinstance(overlay, dict) or set(overlay) != fields or overlay["schema_version"] != STATUS_SCHEMA:
            raise PlanRegistryError("status schema is invalid")
        if overlay["campaign_id"] != authority.campaign_id:
            raise PlanRegistryError("status campaign mismatch")
        if overlay["base_ledger_sha256"] != ledger["ledger_sha256"]:
            raise PlanRegistryError("status base ledger digest mismatch")
        revision = authority.source_revision()
        if not isinstance(revision, str) or len(revision) != 64 or any(c not in "0123456789abcdef" for c in revision) or overlay["source_revision"] != revision:
            raise PlanRegistryError("status source revision mismatch")
        timestamp = datetime.fromisoformat(overlay["timestamp"].replace("Z", "+00:00"))
        if timestamp.tzinfo is None or not isinstance(overlay["generator"], str) or not overlay["generator"].strip():
            raise PlanRegistryError("status requires timestamp and generator identity")
        if not isinstance(overlay["cards"], dict):
            raise PlanRegistryError("status card records must be an object")
        entries = {item["card_id"]: deepcopy(item) for item in ledger.get("cards", [])}
        unknown = sorted(set(overlay["cards"]) - set(entries))
        if unknown:
            raise PlanRegistryError(f"status overlay references unknown cards: {unknown}")
        campaign_conformant: list[str] = []
        deferred_criteria: dict[str, list[str]] = {}
        for card_id, record in overlay["cards"].items():
            required = {"prior_status", "status", "owner_decision", "evidence", "acceptance"}
            if not isinstance(record, dict) or not required.issubset(record) or set(record) - required - {"blocker_resolution", "replacement_decision"}:
                raise PlanRegistryError("status record schema is invalid")
            prior, requested = _status(record["prior_status"]), _status(record["status"])
            if prior != _status(authority.prior_statuses.get(card_id, "planned")):
                raise PlanRegistryError("status prior state mismatch")
            if requested not in _TRANSITIONS[prior]:
                raise PlanRegistryError("illegal status transition")
            decision = authority.owner_decisions.get(record["owner_decision"])
            if not isinstance(decision, StatusOwnerDecision):
                raise PlanRegistryError("status owner decision is not admitted")
            if (
                decision.card_id != card_id or decision.requested_status != requested
                or decision.campaign_id != authority.campaign_id
                or decision.source_revision != revision
                or decision.base_ledger_sha256 != ledger["ledger_sha256"]
                or not isinstance(decision.authority, str) or not decision.authority.strip()
            ):
                raise PlanRegistryError("owner decision does not bind this transition, source and plan")
            evidence = _evidence_paths(root, record["evidence"])
            if prior == "blocked" and requested == "in_progress":
                refs = record.get("blocker_resolution")
                if not isinstance(refs, list) or not refs or any(ref not in evidence for ref in refs):
                    raise PlanRegistryError("blocked transition requires resolution evidence")
            if requested == "superseded" and record.get("replacement_decision") not in authority.owner_decisions:
                raise PlanRegistryError("supersession requires an admitted replacement")
            criteria = record["acceptance"]
            if not isinstance(criteria, list):
                raise PlanRegistryError("acceptance results must be an array")
            results: dict[str, str] = {}
            locked = entries[card_id]["acceptance"]
            for row in criteria:
                if not isinstance(row, dict) or set(row) != {"criterion", "result", "evidence"}:
                    raise PlanRegistryError("acceptance result schema is invalid")
                criterion, result, refs = row["criterion"], row["result"], row["evidence"]
                if criterion not in locked or criterion in results or result not in {"PASS", "FAIL", "BLOCKED", "DEFERRED"}:
                    raise PlanRegistryError("acceptance criterion/result is invalid or duplicated")
                if not isinstance(refs, list) or not refs or any(ref not in evidence for ref in refs):
                    raise PlanRegistryError("acceptance criterion requires bound evidence")
                if result == "PASS":
                    evaluator = authority.evaluators.get((card_id, criterion))
                    if not callable(evaluator):
                        raise PlanRegistryError("acceptance requires a registered evaluator")
                    if evaluator([evidence[ref] for ref in refs]) is not True:
                        raise PlanRegistryError("independent acceptance evaluation failed")
                elif result == "DEFERRED":
                    exemption = authority.criterion_deferrals.get((card_id, criterion))
                    if (not isinstance(exemption, CriterionDeferral)
                            or exemption.card_id != card_id or exemption.criterion != criterion
                            or exemption.campaign_id != authority.campaign_id
                            or exemption.source_revision != revision
                            or exemption.base_ledger_sha256 != ledger["ledger_sha256"]
                            or not isinstance(exemption.authority, str) or not exemption.authority.strip()
                            or not isinstance(exemption.reason, str) or not exemption.reason.strip()):
                        raise PlanRegistryError("criterion deferral requires exact admitted owner authority")
                results[criterion] = result
            if requested == "accepted" and (set(results) != set(locked) or any(result != "PASS" for result in results.values())):
                raise PlanRegistryError("accepted requires every locked acceptance criterion to pass")
            deferred = [criterion for criterion, result in results.items() if result == "DEFERRED"]
            if deferred:
                deferred_criteria[card_id] = sorted(deferred)
            if (requested == "partial_verified" and deferred and set(results) == set(locked)
                    and all(result in {"PASS", "DEFERRED"} for result in results.values())):
                checks = authority.additional_requirements.get(card_id, ())
                if not checks or any(not callable(check) or check(list(evidence.values())) is not True for check in checks):
                    raise PlanRegistryError("campaign conformance requires independent current requirements")
                campaign_conformant.append(card_id)
            # Evaluators may run real validators. Do not publish acceptance if
            # their evidence or source revision changed during evaluation.
            _evidence_paths(root, record["evidence"])
            entries[card_id].update(status=requested, status_evidence=deepcopy(record["evidence"]))
        if authority.source_revision() != revision:
            raise PlanRegistryError("source revision changed during acceptance evaluation")
    except PlanRegistryError:
        raise
    except Exception as error:
        raise PlanRegistryError(f"status validation failed: {type(error).__name__}") from error
    body = deepcopy(ledger)
    body.pop("artifact_sha256", None)
    body["cards"] = [entries[key] for key in sorted(entries)]
    body["status_summary"] = _status_summary(body["cards"])
    body["campaign_conformant_cards"] = sorted(campaign_conformant)
    body["owner_deferred_criteria"] = deferred_criteria
    body["status_authority"] = {
        "schema_version": STATUS_SCHEMA, "campaign_id": authority.campaign_id,
        "base_ledger_sha256": ledger["ledger_sha256"], "source_revision": revision,
        "generator": overlay["generator"], "timestamp": overlay["timestamp"],
    }
    body.pop("ledger_sha256", None)
    body["ledger_sha256"] = _digest(body)
    view = _StatusView(body)
    # Retain a copy of canonical truth. A caller changing the output cannot
    # change the acceptance inputs or grant authority by recomputing a digest.
    base = deepcopy(ledger)
    view._refresh = lambda: apply_status(base, status_path, authority=authority)
    view._blocking_cards = authority.blocking_cards
    return view


def _status_summary(cards: list[dict[str, Any]]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for card in cards:
        key = str(card.get("status") or "planned")
        summary[key] = summary.get(key, 0) + 1
    return dict(sorted(summary.items()))


def validate_ledger(ledger: dict[str, Any]) -> dict[str, Any]:
    """Check content identity before interpreting dependency authority.

    ledger_sha256 covers the entire semantic body, preserving list order.
    Only itself and artifact_sha256 (the optional transport envelope digest)
    are excluded. The latter independently covers everything except itself.
    Serialization uses sorted keys, compact separators, JSON ASCII escapes,
    finite numbers only, and UTF-8 bytes, matching the canonical writer.
    """
    problems: list[str] = []
    semantic = {key: value for key, value in ledger.items()
                if key not in {"ledger_sha256", "artifact_sha256"}}
    observed = ledger.get("ledger_sha256")
    try:
        expected = _digest(semantic)
        if observed != expected:
            problems.append(f"ledger digest mismatch: expected {expected}, observed {observed}")
        if "artifact_sha256" in ledger:
            transport = {key: value for key, value in ledger.items() if key != "artifact_sha256"}
            if ledger["artifact_sha256"] != _digest(transport):
                problems.append("artifact transport digest mismatch")
    except (TypeError, ValueError) as error:
        expected = None
        problems.append(f"ledger digest cannot be computed: {error}")
    cards = {card["card_id"]: card for card in ledger.get("cards", [])}
    if ledger.get("schema_version") != LEDGER_SCHEMA:
        problems.append("ledger schema is invalid")
    for card_id, card in sorted(cards.items()):
        if not str(card.get("owner") or "").strip():
            problems.append(f"{card_id} is ownerless")
        if not str(card.get("rollback") or "").strip():
            problems.append(f"{card_id} has no rollback")
        if not list(card.get("acceptance") or ()):
            problems.append(f"{card_id} has no acceptance criteria")
        for dependency in card.get("depends_on", ()):
            if dependency not in cards:
                problems.append(f"{card_id} depends on unknown card {dependency}")
    order = ledger.get("topological_order") or []
    if sorted(order) != sorted(cards):
        problems.append("topological order does not cover exactly the declared cards")
    else:
        position = {card_id: index for index, card_id in enumerate(order)}
        for card_id, card in sorted(cards.items()):
            for dependency in card.get("depends_on", ()):
                if dependency in position and position[dependency] >= position[card_id]:
                    problems.append(f"{card_id} does not follow its dependency {dependency}")
    return {
        "valid": not problems,
        "expected_ledger_sha256": expected,
        "observed_ledger_sha256": observed,
        "problems": problems,
        "card_count": len(cards),
        "ownerless_count": len(ledger.get("ownerless_cards") or ()),
    }


def _require_valid_ledger(ledger: dict[str, Any]) -> None:
    report = validate_ledger(ledger)
    if not report["valid"]:
        raise PlanRegistryError("; ".join(report["problems"]))


def ready_cards(ledger: dict[str, Any]) -> list[str]:
    """Dependency readiness from currently validated acceptance, never topology."""
    _require_valid_ledger(ledger)
    if isinstance(ledger, _StatusView):
        current = ledger._refresh()
        if _canonical(dict(ledger)) != _canonical(dict(current)):
            raise PlanRegistryError("status authority projection has changed")
    elif any("status" in card for card in ledger.get("cards", [])):
        raise PlanRegistryError("status authority must be revalidated before readiness")
    blocked = getattr(ledger, "_blocking_cards", frozenset())
    implemented = {
        card_id
        for card_id, card in (
            (item["card_id"], item) for item in ledger.get("cards", [])
        )
        if card.get("status") == "accepted" and card_id not in blocked
    }
    if isinstance(ledger, _StatusView):
        implemented.update(set(ledger["campaign_conformant_cards"]) - blocked)
    return sorted(
        card_id
        for card_id, card in (
            (item["card_id"], item) for item in ledger.get("cards", [])
        )
        if card_id not in implemented
        and card_id not in getattr(ledger, "_blocking_cards", frozenset())
        and card.get("status") not in {"blocked", "rejected", "deferred", "superseded"}
        and all(dependency in implemented for dependency in card.get("depends_on", ()))
    )


def readiness_report(root: Path, *, authority: StatusAuthority | None = None) -> dict[str, Any]:
    """Read-only runtime entry point; unavailable acceptance authority blocks.

    The CLI deliberately cannot manufacture owner decisions or evaluators from
    the overlay. Registered runtime consumers can supply their admitted host
    authority; an untrusted JSON projection is never enough to unlock work.
    """
    from .archive_io import read_stream_bytes, reject_path_links

    try:
        root = Path(root).resolve(strict=True)
        if authority is not None and authority.root.resolve(strict=True) != root:
            raise PlanRegistryError("status authority root mismatch")
        target = root / LEDGER_RELATIVE
        reject_path_links(target)
        with target.open("rb") as stream:
            raw = read_stream_bytes(stream, max_bytes=8 * 1024 * 1024)
        ledger = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
        if not isinstance(ledger, dict):
            raise PlanRegistryError("ledger must be an object")
        _require_valid_ledger(ledger)
        status_path = root / "registry/punch_card_status.json"
        policy_path = root / "policies/rev1xx-validation.json"
        if policy_path.is_file():
            policy = _planning_object(policy_path)
            if policy.get("status_overlay") == CURRENT_STATUS_RELATIVE.as_posix():
                _require_current_campaign(policy)
                status_path = root / CURRENT_STATUS_RELATIVE
                if authority is None:
                    # The default host can validate an empty planned campaign.
                    # It grants no decisions/evaluators for claimed acceptance.
                    authority = (_registered_foundation_authority(root, policy)
                        if FOUNDATION_BINDING in policy else
                        StatusAuthority(root, policy["campaign_id"], lambda: planning_input_revision(root)))
        view = apply_status(ledger, status_path, authority=authority)
        ready = ready_cards(view)
        return {
            "valid": True, "execution_ready": ready,
            "accepted_card_count": sum(card.get("status") == "accepted" for card in view["cards"]),
            "accepted_card_ids": sorted(card["card_id"] for card in view["cards"]
                if card.get("status")=="accepted" and card["card_id"] not in getattr(view,"_blocking_cards",frozenset())),
            "campaign_conformant_cards": list(view.get("campaign_conformant_cards", [])),
            "owner_deferred_criteria": deepcopy(view.get("owner_deferred_criteria", {})),
            "base_ledger_sha256": ledger["ledger_sha256"],
            "topological_order": ledger["topological_order"],
            "authority": "Validated current criterion proof and explicit owner exceptions; full acceptance is separate",
        }
    except (OSError, ValueError, KeyError, TypeError) as error:
        return {"valid": False, "execution_ready": [], "accepted_card_count": 0,
                "errors": [f"{type(error).__name__}: {error}"]}


def _planning_object(path: Path) -> dict[str, Any]:
    from .archive_io import reject_path_links
    from .json_io import read_bounded_bytes
    from .project_revision_succession import current_revision_root
    if path.name == "rev1xx-validation.json" and path.parent.name == "policies":
        revision = current_revision_root(path.parent)
        if revision is not None:
            path = revision / "validation-policy.json"
    reject_path_links(path)
    value = json.loads(read_bounded_bytes(path, max_bytes=8 * 1024 * 1024), object_pairs_hook=_unique_object)
    if not isinstance(value, dict):
        raise PlanRegistryError("planning input must be an object")
    return value


def _require_current_campaign(policy: dict[str, Any]) -> None:
    if (policy.get("schema_version") != "px.validation-basis/1.0"
            or policy.get("basis") != "current_implementation"
            or policy.get("authority") != "OWNER-FRESH-VALIDATION-001"
            or not isinstance(policy.get("campaign_id"), str) or not policy["campaign_id"].strip()):
        raise PlanRegistryError("fresh current campaign requires explicit owner authority")


def _foundation_source_revision(root: Path, reference_root: Path) -> str:
    """Current foundation owners and data, excluding their output projections."""
    from .archive_io import reject_path_links
    from .json_io import read_bounded_bytes
    policy = _planning_object(root / "policies/rev1xx-validation.json")
    policy.pop(FOUNDATION_BINDING, None)
    rows = {"policy": _digest(policy)}
    owners = ("plan_registry.py", "release_repository_context.py", "release_campaign.py",
        "source_freeze.py", "source_boundary.py", "world_state.py", "json_io.py",
        "archive_io.py", "bounded_walk.py", "paths.py")
    paths = {"engine:" + name: Path(__file__).parent / name for name in owners}
    paths[LEDGER_RELATIVE.as_posix()] = root / LEDGER_RELATIVE
    for name in ("pyproject.toml", "extension/package.json"):
        paths[name] = root / name
    from .release_campaign import release_state_relative
    release_path = release_state_relative(root)
    paths[release_path.as_posix()] = root / release_path
    for path in (root / "registry/planning/rev1xx").glob("*.json"):
        if path.name != CURRENT_STATUS_RELATIVE.name:
            paths[path.relative_to(root).as_posix()] = path
    for key in ("source_anchor", "requirement_trace", "canonical_waves"):
        binding = policy.get(key)
        if isinstance(binding, dict):
            paths[binding["path"]] = root / binding["path"]
    ledger = _planning_object(root / LEDGER_RELATIVE)
    if "architecture_decision" in ledger:
        name = ledger["architecture_decision"]["path"]
        paths[name] = root / name
    for name, path in sorted(paths.items()):
        reject_path_links(path)
        rows[name] = _sha256_bytes(read_bounded_bytes(path, max_bytes=8 * 1024**2))
    rows["reference_corpus"] = inventory_current_corpus(reference_root)["corpus_sha256"]
    return _digest(rows)


def _foundation_owned_write(root: Path, relative: str, payload: bytes) -> None:
    """Register prepared-image custody before bounded atomic publication."""
    import os
    from uuid import uuid4
    from .archive_io import portable_member_name, reject_path_links
    from .resource_lifecycle import ResourceManager, RunState
    if (portable_member_name(relative, allow_directory=False) != relative
            or not (relative.startswith(FOUNDATION_NAMESPACE) or relative in {
                CURRENT_STATUS_RELATIVE.as_posix(), "policies/rev1xx-validation.json"})
            or not 0 < len(payload) <= 8 * 1024**2):
        raise PlanRegistryError("foundation publication escapes its bounded owner")
    target = root / relative
    reject_path_links(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name("." + target.name + "." + uuid4().hex + ".prepared")
    manager = ResourceManager(root / ".agentic_engineering_os_px/resource-lifecycle/ledger.json")
    run_id = "foundation-publication-" + uuid4().hex
    record = manager.register_path(temporary, allowed_cleanup_root=target.parent,
        project_id="rev1xx-foundation", run_id=run_id, lane_id="foundation-authority",
        creator=__name__, retention_required=True)
    try:
        with temporary.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        reject_path_links(target)
        os.replace(temporary, target)
        manager.update(record.resource_id, retention_required=False)
        closed = manager.reclaim_ephemeral_path(record.resource_id, reason="foundation_image_published")
        if closed.errors or closed.resources_reclaimed != 1:
            raise PlanRegistryError("foundation prepared-image custody did not close")
    except BaseException:
        manager.mark_run_ended(run_id, RunState.FAILED,
            retain_reason="foundation_publication_requires_reconciliation")
        raise


def _foundation_store(root: Path, prefix: str, value: dict[str, Any]) -> dict[str, str]:
    from .archive_io import reject_path_links
    from .json_io import read_bounded_bytes
    data = (_canonical(value) + "\n").encode("utf-8")
    digest = _sha256_bytes(data)
    relative = FOUNDATION_NAMESPACE + prefix + "-" + digest + ".json"
    target = root / relative
    reject_path_links(target)
    if target.exists():
        if read_bounded_bytes(target, max_bytes=8 * 1024**2) != data:
            raise PlanRegistryError("immutable foundation image differs")
    else:
        _foundation_owned_write(root, relative, data)
    return {"path": relative, "sha256": digest}


def _foundation_bound_object(root: Path, binding: dict[str, str]) -> tuple[Path, dict[str, Any]]:
    from .archive_io import portable_member_name
    from .json_io import read_bounded_bytes
    if not isinstance(binding, dict) or set(binding) != {"path", "sha256"}:
        raise PlanRegistryError("foundation host binding is malformed")
    name = portable_member_name(binding["path"], allow_directory=False)
    if name != binding["path"] or not name.startswith(FOUNDATION_NAMESPACE):
        raise PlanRegistryError("foundation host binding escapes its namespace")
    path = root / name
    body = _planning_object(path)
    if _sha256_bytes(read_bounded_bytes(path, max_bytes=8 * 1024**2)) != binding["sha256"]:
        raise PlanRegistryError("foundation host binding hash differs")
    return path, body


def _registered_foundation_authority(root: Path, policy: dict[str, Any]) -> StatusAuthority:
    """Host-owned registration is separate from the untrusted status overlay.

    Saved proof never substitutes for executing the native current verifier.
    Only the four W0 owners are registered here; other cards gain no authority.
    """
    from .json_io import read_bounded_bytes
    _, registration = _foundation_bound_object(root, policy[FOUNDATION_BINDING])
    required = {"schema_version", "campaign_id", "base_ledger_sha256", "source_revision",
        "reference_root", "git_deferral_authority", "proof", "prior_status_image",
        "decisions", "status_image_sha256"}
    if set(registration) != required or registration["schema_version"] != "px.foundation-host-registration/1.0":
        raise PlanRegistryError("foundation registration schema differs")
    reference_root = Path(registration["reference_root"])
    if not reference_root.is_absolute():
        raise PlanRegistryError("foundation reference lookup requires an explicit host location")
    revision = _foundation_source_revision(root, reference_root)
    if (registration["campaign_id"] != policy["campaign_id"]
            or registration["source_revision"] != revision):
        raise PlanRegistryError("foundation registration has stale or foreign inputs")
    current = read_bounded_bytes(root / CURRENT_STATUS_RELATIVE, max_bytes=4 * 1024**2)
    if _sha256_bytes(current) != registration["status_image_sha256"]:
        raise PlanRegistryError("status image differs from its admitted host transition")
    proof_path, proof = _foundation_bound_object(root, registration["proof"])
    actual = foundation_report(root, reference_root=reference_root)
    if (actual != proof or actual.get("valid") is not True
            or actual.get("base_ledger_sha256") != registration["base_ledger_sha256"]
            or actual.get("historical_prerequisites") is not False
            or actual.get("git_acceptance_satisfied") is not False
            or actual.get("acceptance_state_changed") is not False
            or set(actual.get("criteria", {})) != {"BASE-001", "BASE-002", "BASE-003", "BASE-004"}):
        raise PlanRegistryError("native current foundation proof differs or failed")
    _, prior_image = _foundation_bound_object(root, registration["prior_status_image"])
    decisions = registration["decisions"]
    if not isinstance(decisions, dict) or len(decisions) != 4:
        raise PlanRegistryError("foundation registration requires exactly four decisions")
    authority = StatusAuthority(root, policy["campaign_id"],
        lambda: _foundation_source_revision(root, reference_root),
        prior_statuses={cid: prior_image["cards"].get(cid, {}).get("status", "planned")
            for cid in actual["criteria"]},
        owner_decisions={key: StatusOwnerDecision(**value) for key, value in decisions.items()})

    def verified(paths):
        return proof_path in paths and _planning_object(proof_path) == actual

    for cid, rows in actual["criteria"].items():
        for row in rows:
            key = (cid, row["criterion"])
            expected = "DEFERRED" if row["criterion"] in FOUNDATION_GIT_CRITERIA.get(cid, ()) else "PASS"
            if row["result"] != expected:
                raise PlanRegistryError("foundation exception exceeds the exact owner Git decision")
            if row["result"] == "PASS":
                authority.evaluators[key] = verified
            elif row["result"] == "DEFERRED":
                authority.criterion_deferrals[key] = CriterionDeferral(cid, row["criterion"],
                    policy["campaign_id"], revision, registration["base_ledger_sha256"],
                    registration["git_deferral_authority"], "Explicit owner Git hold; literal Git criterion remains unsatisfied")
            else:
                raise PlanRegistryError("foundation criteria are not independently proven or owner-deferred")
    required_replacements = {"source_custody", "package_versions", "decision_guard", "terminal_preservation", "release_isolation"}
    def replacements(paths):
        values = actual.get("current_replacements", {})
        return verified(paths) and all(values.get(key) is True for key in required_replacements)
    authority.additional_requirements.update({cid: (replacements,) for cid in ("BASE-001", "BASE-002")})
    return authority


def register_foundation_readiness(root: Path, *, reference_root: Path,
                                  git_deferral_authority: str) -> dict[str, Any]:
    """Perform real current transitions under explicit host owner authority."""
    from .file_lock import FileLock
    from .archive_io import reject_path_links
    from .json_io import read_bounded_bytes
    if (not isinstance(git_deferral_authority, str) or not git_deferral_authority.strip()
            or len(git_deferral_authority) > 512):
        raise PlanRegistryError("explicit owner Git deferral authority is required")
    reject_path_links(root)
    root = Path(root).resolve(strict=True)
    reference_root = Path(reference_root).resolve(strict=True)
    lock = root / FOUNDATION_NAMESPACE / "registration.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(lock, timeout_seconds=10):
        policy = _planning_object(root / "policies/rev1xx-validation.json")
        _require_current_campaign(policy)
        ledger = _planning_object(root / LEDGER_RELATIVE)
        _require_valid_ledger(ledger)
        prior = _planning_object(root / CURRENT_STATUS_RELATIVE)
        actual = foundation_report(root, reference_root=reference_root)
        if actual.get("valid") is not True or actual.get("base_ledger_sha256") != ledger["ledger_sha256"]:
            raise PlanRegistryError("actual current foundation verification failed")
        replacements = actual.get("current_replacements", {})
        if any(replacements.get(key) is not True for key in (
                "source_custody", "package_versions", "decision_guard", "terminal_preservation", "release_isolation")):
            raise PlanRegistryError("actual current foundation replacement requirements failed")
        for cid, rows in actual["criteria"].items():
            if any(row["result"] != ("DEFERRED" if row["criterion"] in FOUNDATION_GIT_CRITERIA.get(cid, ()) else "PASS") for row in rows):
                raise PlanRegistryError("foundation exception exceeds the exact owner Git decision")
        revision = _foundation_source_revision(root, reference_root)
        proof = _foundation_store(root, "proof", actual)
        if prior["cards"]:
            if FOUNDATION_BINDING not in policy:
                raise PlanRegistryError("existing progress requires its original admitted host registration")
            _, previous = _foundation_bound_object(root, policy[FOUNDATION_BINDING])
            if (set(prior["cards"]) != set(actual["criteria"])
                    or previous["status_image_sha256"] != _sha256_bytes(read_bounded_bytes(root / CURRENT_STATUS_RELATIVE, max_bytes=4 * 1024**2))
                    or previous["git_deferral_authority"] != git_deferral_authority):
                raise PlanRegistryError("refusing to overwrite unregistered or foreign campaign progress")
            if previous["source_revision"] == revision and previous["proof"] == proof:
                report = readiness_report(root)
                if not report["valid"]:
                    raise PlanRegistryError("existing current foundation registration is invalid")
                return {"valid": True, "idempotent": True, "readiness": report,
                    "proof": proof, "build_or_install_performed": False,
                    "claim_scope": "Current W0 software conformance only; Git remains deferred"}
            previous_image = previous["prior_status_image"]
            targets = [{cid: row["status"] for cid, row in prior["cards"].items()}]
        else:
            previous_image = None
            targets = [{cid: "in_progress" for cid in actual["criteria"]},
                {cid: "partial_verified" for cid in actual["criteria"]},
                {cid: ("partial_verified" if cid in {"BASE-001", "BASE-002"} else "accepted")
                    for cid in actual["criteria"]}]
        for targets_by_card in targets:
            if previous_image is None:
                prior_binding = _foundation_store(root, "status-history", prior)
                prior_states = {cid: prior["cards"].get(cid, {}).get("status", "planned") for cid in targets_by_card}
            else:
                prior_binding = previous_image
                _, origin = _foundation_bound_object(root, prior_binding)
                prior_states = {cid: origin["cards"].get(cid, {}).get("status", "planned") for cid in targets_by_card}
                _foundation_store(root, "revalidation-history", prior)
            image = {"schema_version": STATUS_SCHEMA, "campaign_id": policy["campaign_id"],
                "base_ledger_sha256": ledger["ledger_sha256"], "source_revision": revision,
                "generator": "runtime.plan_registry.register_foundation_readiness",
                "timestamp": datetime.now(timezone.utc).isoformat(), "cards": {}}
            decisions = {}
            for cid, requested in targets_by_card.items():
                decision = {"card_id": cid, "requested_status": requested,
                    "campaign_id": policy["campaign_id"], "source_revision": revision,
                    "base_ledger_sha256": ledger["ledger_sha256"], "authority": git_deferral_authority}
                key = "foundation-host:" + _digest({**decision, "prior_status": prior_states[cid], "proof": proof})
                decisions[key] = decision
                image["cards"][cid] = {"prior_status": prior_states[cid], "status": requested,
                    "owner_decision": key, "evidence": [proof],
                    "acceptance": [{"criterion": row["criterion"], "result": row["result"],
                        "evidence": [proof["path"]]} for row in actual["criteria"][cid]]}
            data = (_canonical(image) + "\n").encode("utf-8")
            registration = {"schema_version": "px.foundation-host-registration/1.0",
                "campaign_id": policy["campaign_id"], "base_ledger_sha256": ledger["ledger_sha256"],
                "source_revision": revision, "reference_root": str(reference_root),
                "git_deferral_authority": git_deferral_authority, "proof": proof,
                "prior_status_image": prior_binding, "decisions": decisions,
                "status_image_sha256": _sha256_bytes(data)}
            if _foundation_source_revision(root, reference_root) != revision:
                raise PlanRegistryError("foundation inputs changed before publication")
            policy[FOUNDATION_BINDING] = _foundation_store(root, "authority", registration)
            _foundation_owned_write(root, "policies/rev1xx-validation.json", (_canonical(policy) + "\n").encode("utf-8"))
            _foundation_owned_write(root, CURRENT_STATUS_RELATIVE.as_posix(), data)
            report = readiness_report(root)
            if not report["valid"]:
                raise PlanRegistryError("registered foundation readiness failed: " + "; ".join(report["errors"]))
            prior = image
        return {"valid": True, "claim_scope": "Current W0 software conformance only; Git remains deferred",
            "readiness": report, "proof": proof, "build_or_install_performed": False}


def planning_input_revision(root: Path) -> str:
    """Fence the planned-only view to current plan, policy and wave inputs.

    Feature acceptance requires host-registered evaluators and their actual
    software/source revision callback; this planned-only host has neither.
    """
    from .archive_io import reject_path_links
    from .json_io import read_bounded_bytes

    policy = _planning_object(root / "policies/rev1xx-validation.json")
    _require_current_campaign(policy)
    relative = policy["canonical_waves"]["path"]
    if not isinstance(relative, str) or not relative.startswith("registry/planning/rev1xx/") or ".." in Path(relative).parts:
        raise PlanRegistryError("current campaign wave binding is invalid")
    paths = [LEDGER_RELATIVE, Path("policies/rev1xx-validation.json"), Path(relative)]
    rows = []
    for path in paths:
        target = root / path
        reject_path_links(target)
        rows.append({"path": path.as_posix(), "sha256": _sha256_bytes(read_bounded_bytes(target, max_bytes=8 * 1024 * 1024))})
    return _digest(rows)


def begin_plan_campaign(root: Path) -> dict[str, Any]:
    """Start fresh without carrying legacy status or erasing current progress."""
    root = Path(root).resolve(strict=True)
    policy_path = root / "policies/rev1xx-validation.json"
    policy = _planning_object(policy_path)
    _require_current_campaign(policy)
    ledger = _planning_object(root / LEDGER_RELATIVE)
    _require_valid_ledger(ledger)
    if not wave_report(root)["valid"]:
        raise PlanRegistryError("current campaign requires the canonical wave map")
    target = root / CURRENT_STATUS_RELATIVE
    previous = _planning_object(target) if target.exists() else None
    if previous is not None and (previous.get("schema_version") != STATUS_SCHEMA or previous.get("cards") != {}):
        raise PlanRegistryError("refusing to reset current campaign progress")
    already_current = (previous is not None
                       and policy.get("status_overlay") == CURRENT_STATUS_RELATIVE.as_posix()
                       and previous.get("source_revision") == planning_input_revision(root)
                       and previous.get("base_ledger_sha256") == ledger["ledger_sha256"]
                       and previous.get("campaign_id") == policy["campaign_id"])
    if already_current:
        report = readiness_report(root)
        if not report["valid"]:
            raise PlanRegistryError("current campaign validation failed")
        return {"valid": True, "campaign_id": policy["campaign_id"],
                "planned_card_count": ledger["card_count"], "accepted_card_count": 0,
                "execution_ready": report["execution_ready"], "idempotent": True,
                "legacy_status_role": "preserved_reference_only"}
    # Preserve superseded empty current status. Legacy files remain untouched
    # in their existing custody; they are never read or needed to start fresh.
    from .archive_io import reject_path_links
    from .json_io import read_bounded_bytes

    for source in ([target] if previous is not None else []):
        if not source.is_file():
            continue
        reject_path_links(source)
        data = read_bounded_bytes(source, max_bytes=4 * 1024 * 1024)
        archive = root / "registry/planning/rev1xx/status-history" / (_sha256_bytes(data) + ".json")
        reject_path_links(archive)
        archive.parent.mkdir(parents=True, exist_ok=True)
        if archive.exists():
            if read_bounded_bytes(archive, max_bytes=4 * 1024 * 1024) != data:
                raise PlanRegistryError("preserved status bytes have been modified")
        else:
            with archive.open("xb") as handle:
                handle.write(data)
    policy["status_overlay"] = CURRENT_STATUS_RELATIVE.as_posix()
    rendered_policy = json.dumps(policy, indent=2) + "\n"
    if policy_path.read_text(encoding="utf-8") != rendered_policy:
        prepared = policy_path.with_name(policy_path.name + ".new")
        prepared.write_text(rendered_policy, encoding="utf-8")
        prepared.replace(policy_path)
    revision = planning_input_revision(root)
    idempotent = previous is not None and previous.get("source_revision") == revision and previous.get("base_ledger_sha256") == ledger["ledger_sha256"] and previous.get("campaign_id") == policy["campaign_id"]
    if not idempotent:
        body = {"schema_version": STATUS_SCHEMA, "campaign_id": policy["campaign_id"],
                "base_ledger_sha256": ledger["ledger_sha256"], "source_revision": revision,
                "generator": "runtime.plan_registry.begin_plan_campaign",
                "timestamp": datetime.now(timezone.utc).isoformat(), "cards": {}}
        reject_path_links(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        prepared = target.with_name(target.name + ".new")
        prepared.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
        prepared.replace(target)
    report = readiness_report(root)
    if not report["valid"]:
        raise PlanRegistryError("current campaign initialization failed validation")
    return {"valid": True, "campaign_id": policy["campaign_id"],
            "planned_card_count": ledger["card_count"], "accepted_card_count": 0,
            "execution_ready": report["execution_ready"], "idempotent": idempotent,
            "legacy_status_role": "preserved_reference_only"}
