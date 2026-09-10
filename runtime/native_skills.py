"""PX-native skill custody, manifests, domain isolation, and bounded retrieval."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
from typing import Iterable, Mapping

from .bounded_walk import WalkLimits, bounded_walk
from .json_io import decode_json_object, load_json_object, read_bounded_bytes


INDEX_SCHEMA = "px.native-skill-index/1.0"
PACKAGE_SCHEMA = "px.native-skill-package/1.0"
BACKUP_SCHEMA = "px.skill-custody-backup/1.0"
DOMAINS = frozenset({"px-standard", "microsoft-vendor", "enterprise-restricted", "user-preserved"})
DEFAULT_DOMAINS = frozenset({"px-standard"})
MAX_CANDIDATES = 3
MAX_COMPARISON_FILES = 512
MAX_COMPARISON_BYTES = 16 * 1024 * 1024
MAX_COMPARISON_CHANGES = 100
MAX_BODY_BYTES = 512_000
MAX_CUSTODY_BYTES = 512 * 1024 * 1024
_WORD = re.compile(r"[a-z0-9][a-z0-9._+-]*", re.I)
_DESCRIPTION = re.compile(r"(?m)^description:\s*[\"']?(.*?)[\"']?\s*$")


def _sha(path: Path) -> str:
    return hashlib.sha256(read_bounded_bytes(path, max_bytes=MAX_BODY_BYTES)).hexdigest()


def _body_hash_matches(path: Path, expected: str) -> bool:
    if not expected:
        return False
    raw = read_bounded_bytes(path, max_bytes=MAX_BODY_BYTES)
    normalized = raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    return expected in {hashlib.sha256(raw).hexdigest(), hashlib.sha256(normalized.encode("utf-8")).hexdigest()}


def _custody_bytes_candidate(
    path: Path, expected_size: object, expected_sha: object
) -> bytes | None:
    """Return the exact bytes bound by custody, including pre-Git CRLF bytes."""
    if type(expected_size) is not int or not 0 <= expected_size <= MAX_CUSTODY_BYTES:
        return None
    if type(expected_sha) is not str or re.fullmatch(r"[0-9a-f]{64}", expected_sha) is None:
        return None
    expected = expected_sha
    try:
        size = expected_size
        raw = bytes(read_bounded_bytes(path, max_bytes=max(1, size)))
    except (OSError, TypeError, ValueError):
        return None
    candidates = [raw]
    try:
        normalized = raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    except UnicodeDecodeError:
        normalized = None
    if normalized is not None:
        candidates.append(normalized.replace("\n", "\r\n").encode("utf-8"))
    return next(
        (
            candidate
            for candidate in candidates
            if len(candidate) == size
            and hashlib.sha256(candidate).hexdigest() == expected
        ),
        None,
    )


def _custody_bytes_match(path: Path, expected_size: object, expected_sha: object) -> bool:
    """Verify raw bytes or the exact CRLF form retained by pre-Git custody."""

    return _custody_bytes_candidate(path, expected_size, expected_sha) is not None


def _json_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def inventory_tree(root: Path, *, limits: WalkLimits | None = None) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    if not root.is_dir():
        return records
    walk = bounded_walk(root, limits=limits or WalkLimits(max_files=100_000, max_bytes=MAX_CUSTODY_BYTES))
    for entry in walk.entries:
        if entry.kind != "file":
            continue
        # Metadata limits are checked for the whole tree before any hash read.
        # Growth between enumeration and reading fails within one probe byte.
        digest = hashlib.sha256()
        consumed = 0
        with entry.path.open("rb") as stream:
            while True:
                data = stream.read(min(65_536, entry.size + 1 - consumed))
                if not data:
                    break
                consumed += len(data)
                if consumed > entry.size:
                    raise ValueError("skill custody file grew during bounded acquisition")
                digest.update(data)
        if consumed != entry.size:
            raise ValueError("skill custody file shrank during bounded acquisition")
        records.append({"path": entry.relative, "size_bytes": consumed, "sha256": digest.hexdigest()})
    return records


def tree_hash(records: Iterable[Mapping[str, object]]) -> str:
    stable = [{"path": row["path"], "size_bytes": row["size_bytes"], "sha256": row["sha256"]} for row in records]
    return _json_hash(stable)


def build_skill_index(
    records: Iterable[Mapping[str, object]],
    *,
    template: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Build every derived index field from one immutable record set.

    Callers may preserve non-derived metadata through ``template`` but cannot
    supply counts, a record denominator, or a revision independently.
    """
    canonical = sorted(
        (dict(record) for record in records), key=lambda row: str(row.get("id", ""))
    )
    ids = [str(row.get("id") or "") for row in canonical]
    if not all(ids) or len(ids) != len(set(ids)):
        raise ValueError("skill index requires unique non-empty record IDs")
    unknown = sorted(
        {str(row.get("domain") or "") for row in canonical} - set(DOMAINS)
    )
    if unknown:
        raise ValueError(f"skill index contains unknown domains: {unknown}")
    payload = {
        key: value
        for key, value in dict(template or {}).items()
        if key not in {"records", "record_count", "counts", "revision"}
    }
    payload.setdefault("schema_version", INDEX_SCHEMA)
    payload.setdefault(
        "loading_rule",
        "metadata-only; maximum three candidates; exactly one body after explicit selection",
    )
    payload.setdefault("default_domains", ["px-standard"])
    counts = {
        domain: sum(str(row["domain"]) == domain for row in canonical)
        for domain in sorted(DOMAINS)
    }
    payload.update(
        {
            "records": canonical,
            "record_count": len(canonical),
            "counts": counts,
            "revision": _json_hash(canonical),
        }
    )
    validate_skill_index(payload, require_derived=True)
    return payload


def validate_skill_index(
    payload: Mapping[str, object], *, require_derived: bool = True
) -> dict[str, object]:
    """Refuse index publication or consumption when denominators drift."""
    if payload.get("schema_version") != INDEX_SCHEMA:
        raise ValueError("unsupported PX native skill index")
    records = [dict(row) for row in payload.get("records", ())]
    canonical = build_skill_index(records) if not require_derived else None
    if not require_derived:
        return canonical or {}
    ids = [str(row.get("id") or "") for row in records]
    if not all(ids) or len(ids) != len(set(ids)):
        raise ValueError("skill index requires unique non-empty record IDs")
    unknown = sorted({str(row.get("domain") or "") for row in records} - set(DOMAINS))
    if unknown:
        raise ValueError(f"skill index contains unknown domains: {unknown}")
    expected_counts = {
        domain: sum(str(row["domain"]) == domain for row in records)
        for domain in sorted(DOMAINS)
    }
    declared_counts = payload.get("counts")
    if declared_counts != expected_counts:
        raise ValueError(
            f"skill index denominator drift: declared={declared_counts} expected={expected_counts}"
        )
    if payload.get("record_count") != len(records):
        raise ValueError(
            f"skill index record denominator drift: declared={payload.get('record_count')} expected={len(records)}"
        )
    expected_revision = _json_hash(
        sorted(records, key=lambda row: str(row.get("id", "")))
    )
    if payload.get("revision") != expected_revision:
        raise ValueError("skill index revision does not match its record set")
    return {
        "valid": True,
        "record_count": len(records),
        "counts": expected_counts,
        "revision": expected_revision,
    }


def copy_verified(source: Path, target: Path) -> dict[str, object]:
    if target.exists():
        raise FileExistsError(f"custody target already exists: {target}")
    source_records = inventory_tree(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target, symlinks=False)
    target_records = inventory_tree(target)
    if source_records != target_records:
        raise RuntimeError(f"skill custody verification mismatch: {source} -> {target}")
    return {"source": str(source.resolve()), "backup": target.as_posix(), "file_count": len(source_records), "size_bytes": sum(int(row["size_bytes"]) for row in source_records), "tree_sha256": tree_hash(source_records), "files": source_records}


def _snapshot_path(root: Path, value: object) -> Path:
    if type(value) is not str or not value or len(value) > 4096 or "\\" in value:
        raise ValueError("invalid custody relative path")
    relative = PurePosixPath(value)
    if relative.is_absolute() or any(part in {"..", "."} for part in relative.parts) or ":" in value:
        raise ValueError("invalid custody relative path")
    target = (root / value).resolve()
    if target == root or not target.is_relative_to(root):
        raise ValueError("custody path escapes snapshot root")
    return target


def verify_backup(snapshot_root: Path) -> dict[str, object]:
    return _inspect_backup(snapshot_root)[0]


def _inspect_backup(snapshot_root: Path) -> tuple[dict, dict, dict]:
    """Validate the complete declared source set before reading source trees."""
    manifest_path = snapshot_root / "manifest.json"
    try:
        root = snapshot_root.resolve(strict=True)
        payload = load_json_object(_snapshot_path(root, "manifest.json"), max_bytes=2 * 1024 * 1024)
        sources = payload.get("sources")
        if payload.get("schema_version") != BACKUP_SCHEMA or type(sources) is not list or not 1 <= len(sources) <= 64:
            raise ValueError("backup requires its exact schema and a nonempty bounded source set")
        seen = set()
        inventories = {}
        for source in sources:
            if type(source) is not dict:
                raise ValueError("backup source must be an object")
            identifier = source.get("id")
            if type(identifier) is not str or not identifier.strip() or len(identifier) > 256 or identifier in seen:
                raise ValueError("backup source IDs must be nonempty and unique")
            seen.add(identifier)
            backup = _snapshot_path(root, source.get("relative_backup"))
            if not backup.is_dir():
                raise ValueError("backup source directory is missing")
            count = source.get("file_count")
            if type(count) is not int or not 0 <= count <= 100_000:
                raise ValueError("backup file count is invalid")
            if type(source.get("tree_sha256")) is not str or re.fullmatch(r"[0-9a-f]{64}", source["tree_sha256"]) is None:
                raise ValueError("backup tree hash is invalid")
            if "inventory" in source:
                inventory = _snapshot_path(root, source["inventory"])
                raw = bytes(read_bounded_bytes(inventory, max_bytes=64 * 1024 * 1024))
                rows = decode_json_object(raw)["files"]
                if type(rows) is not list or len(rows) != count:
                    raise ValueError("backup inventory denominator mismatch")
                paths = set()
                for row in rows:
                    if type(row) is not dict:
                        raise ValueError("backup inventory row must be an object")
                    relative = row.get("path")
                    _snapshot_path(backup, relative)
                    if relative in paths:
                        raise ValueError("duplicate backup inventory path")
                    paths.add(relative)
                    if type(row.get("size_bytes")) is not int or not 0 <= row["size_bytes"] <= MAX_CUSTODY_BYTES:
                        raise ValueError("invalid backup inventory size")
                    if type(row.get("sha256")) is not str or re.fullmatch(r"[0-9a-f]{64}", row["sha256"]) is None:
                        raise ValueError("invalid backup inventory hash")
                if type(source.get("inventory_sha256")) is not str or re.fullmatch(r"[0-9a-f]{64}", source["inventory_sha256"]) is None:
                    raise ValueError("invalid inventory custody hash")
                if "inventory_size_bytes" in source and (
                    type(source["inventory_size_bytes"]) is not int
                    or not 0 <= source["inventory_size_bytes"] <= 64 * 1024 * 1024
                ):
                    raise ValueError("invalid inventory custody size")
                normalized = raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
                images = (raw, normalized.replace("\n", "\r\n").encode("utf-8"))
                if not any(
                    hashlib.sha256(image).hexdigest() == source["inventory_sha256"]
                    and ("inventory_size_bytes" not in source or len(image) == source["inventory_size_bytes"])
                    for image in images
                ):
                    raise ValueError(f"inventory-hash:{identifier}")
                inventories[identifier] = rows
        return _verify_backup_sources(root, payload, inventories), payload, inventories
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return {"valid": False, "errors": [str(exc)], "manifest": manifest_path.as_posix(), "sources": 0}, {}, {}


def _verify_backup_sources(snapshot_root: Path, payload: dict, inventories: dict) -> dict[str, object]:
    manifest_path = snapshot_root / "manifest.json"
    errors: list[str] = []
    for source in payload.get("sources", ()):
        records = inventory_tree(snapshot_root / str(source["relative_backup"]))
        expected_records = None
        inventory_matches = not source.get("inventory")
        if source.get("inventory"):
            expected_records = inventories[source["id"]]
            expected_by_path = {
                str(row.get("path", "")): row for row in expected_records or ()
            }
            actual_paths = {str(row["path"]) for row in records}
            inventory_matches = (
                expected_records is not None
                and actual_paths == set(expected_by_path)
                and all(
                    _custody_bytes_match(
                        _snapshot_path(_snapshot_path(snapshot_root, source["relative_backup"]), relative),
                        row.get("size_bytes"),
                        row.get("sha256"),
                    )
                    for relative, row in expected_by_path.items()
                )
            )
            if not inventory_matches:
                errors.append(f"file-inventory:{source['id']}")
        if len(records) != int(source["file_count"]):
            errors.append(f"file-count:{source['id']}")
        custody_records = expected_records if source.get("inventory") else records
        if not inventory_matches or tree_hash(custody_records) != source["tree_sha256"]:
            errors.append(f"tree-hash:{source['id']}")
    return {"valid": not errors, "errors": errors, "manifest": manifest_path.as_posix(), "sources": len(payload.get("sources", ())) }


def restore_backup(snapshot_root: Path, source_id: str, destination: Path) -> dict[str, object]:
    verification, payload, inventories = _inspect_backup(snapshot_root)
    if not verification["valid"]:
        raise RuntimeError(f"backup custody verification failed: {verification['errors']}")
    record = next((row for row in payload.get("sources", ()) if row.get("id") == source_id), None)
    if record is None:
        raise KeyError(f"unknown backup source: {source_id}")
    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError("restore destination must be absent or empty")
    source = _snapshot_path(snapshot_root.resolve(), record["relative_backup"])
    receipt = copy_verified(source, destination)
    if record.get("inventory"):
        expected_records = inventories[source_id]
        for expected in expected_records:
            restored = _snapshot_path(destination.resolve(), expected["path"])
            custody_bytes = _custody_bytes_candidate(
                restored, expected.get("size_bytes"), expected.get("sha256")
            )
            if custody_bytes is None:
                raise RuntimeError(
                    f"restored custody file does not match inventory: {expected['path']}"
                )
            if bytes(read_bounded_bytes(restored, max_bytes=max(1, len(custody_bytes)))) != custody_bytes:
                restored.write_bytes(custody_bytes)
        actual_records = inventory_tree(destination)
        actual_by_path = {str(row["path"]): row for row in actual_records}
        expected_paths = [str(row["path"]) for row in expected_records]
        if set(actual_by_path) != set(expected_paths):
            raise RuntimeError("restored skill tree paths do not match custody manifest")
        # A custody tree hash binds the inventory's retained record order.  That
        # order can differ from host Path ordering (notably Windows vs POSIX),
        # so reconstruct the receipt in manifest order after exact-byte checks.
        restored_records = [actual_by_path[path] for path in expected_paths]
        receipt.update(
            file_count=len(restored_records),
            size_bytes=sum(int(row["size_bytes"]) for row in restored_records),
            tree_sha256=tree_hash(restored_records),
            files=restored_records,
        )
    if receipt["tree_sha256"] != record["tree_sha256"]:
        raise RuntimeError("restored skill tree does not match custody manifest")
    return {"restored": True, "source_id": source_id, "destination": str(destination.resolve()), "tree_sha256": receipt["tree_sha256"]}


def _description(body: Path) -> str:
    text = read_bounded_bytes(body, max_bytes=MAX_BODY_BYTES).decode("utf-8")
    match = _DESCRIPTION.search(text)
    return match.group(1).strip() if match else ""


def _tokens(value: object) -> set[str]:
    return {token.casefold() for token in _WORD.findall(str(value or "")) if len(token) > 1}


def _domain_allowed(domain: str, requested: set[str], grants: set[str]) -> bool:
    if domain not in requested:
        return False
    if domain == "microsoft-vendor":
        return "allow-microsoft-vendor" in grants
    if domain == "enterprise-restricted":
        return "allow-enterprise-restricted" in grants
    if domain == "user-preserved":
        return "allow-user-preserved" in grants
    return domain == "px-standard"


def _record_selectable(record: Mapping[str, object], grants: set[str]) -> bool:
    status = str(record.get("admission") or record.get("status") or "candidate")
    if status in {"active", "admitted"}:
        return True
    return "allow-unadmitted-skill-metadata" in grants


def load_index(root: Path) -> dict[str, object]:
    payload = load_json_object(root.resolve() / ".px" / "skill-index.json", max_bytes=8 * 1024 * 1024)
    validate_skill_index(payload, require_derived=True)
    return payload


def _preserved_records(root: Path, records: Iterable[Mapping[str, object]]) -> list[dict[str, object]]:
    """Expose immutable backup bodies through a separate, opt-in domain.

    The derived records are deliberately not written back to the canonical index:
    the original record and its admission state remain authoritative while the
    preserved copy gets a distinct query boundary.
    """
    project = root.resolve()
    preserved: list[dict[str, object]] = []
    for source in records:
        backup_value = source.get("backup")
        if not backup_value:
            continue
        backup = (project / str(backup_value)).resolve()
        body = backup / "SKILL.md"
        if project != body and project not in body.parents:
            continue
        if not body.is_file():
            continue
        preserved.append(
            {
                **dict(source),
                "domain": "user-preserved",
                "origin": f"preserved-original:{source.get('origin') or 'unknown'}",
                "body": body.relative_to(project).as_posix(),
                "body_available": True,
                "body_sha256": _sha(body),
                "package_root": backup.relative_to(project).as_posix(),
                "native": False,
                "adapted": False,
                "default_eligible": False,
                "admission": "preserved-read-only",
                "status": "preserved-read-only",
                "preserved_original": True,
            }
        )
    return preserved


def _comparison_tree(package: Path) -> tuple[list[dict[str, object]], str]:
    records = inventory_tree(package, limits=WalkLimits(
        max_files=MAX_COMPARISON_FILES, max_bytes=MAX_COMPARISON_BYTES,
        max_depth=32, max_entries=4096, max_directories=2048,
    ))
    size_bytes = sum(int(row["size_bytes"]) for row in records)
    if len(records) > MAX_COMPARISON_FILES or size_bytes > MAX_COMPARISON_BYTES:
        raise ValueError(
            "skill comparison package exceeds bounded file or byte limit"
        )
    return records, tree_hash(records)


def compare_skill(root: Path, skill_id: str) -> dict[str, object]:
    """Compare one PX-standard package to its immutable preserved original."""

    project = root.resolve()
    identifier = str(skill_id).strip()
    if not re.fullmatch(r"[a-z0-9][a-z0-9._:-]{1,127}", identifier):
        raise ValueError("skill comparison requires a valid exact skill ID")
    records = [dict(row) for row in load_index(project).get("records", ())]
    canonical = next(
        (
            row for row in records
            if row.get("id") == identifier
            and row.get("domain") == "px-standard"
            and row.get("native") is True
        ),
        None,
    )
    if canonical is None:
        raise KeyError(f"PX-standard skill is absent: {identifier}")
    backup_value = canonical.get("backup")
    package_value = canonical.get("package_root")
    if not backup_value or not package_value:
        raise ValueError("skill comparison requires both canonical and backup roots")
    package = (project / str(package_value)).resolve()
    backup = (project / str(backup_value)).resolve()
    for candidate in (package, backup):
        if project != candidate and project not in candidate.parents:
            raise ValueError("skill comparison root escapes PX custody")
        if not candidate.is_dir():
            raise FileNotFoundError(f"skill comparison root is unavailable: {candidate}")

    canonical_files, canonical_tree = _comparison_tree(package)
    preserved_files, preserved_tree = _comparison_tree(backup)
    canonical_by_path = {str(row["path"]): row for row in canonical_files}
    preserved_by_path = {str(row["path"]): row for row in preserved_files}
    changes: list[dict[str, object]] = []
    unchanged = 0
    for path in sorted(set(canonical_by_path) | set(preserved_by_path)):
        current = canonical_by_path.get(path)
        original = preserved_by_path.get(path)
        if current is None:
            state = "removed_from_px"
        elif original is None:
            state = "added_to_px"
        elif current["sha256"] != original["sha256"]:
            state = "modified_in_px"
        else:
            unchanged += 1
            continue
        changes.append(
            {
                "path": path,
                "state": state,
                "px_sha256": current.get("sha256") if current else None,
                "preserved_sha256": original.get("sha256") if original else None,
                "px_size_bytes": current.get("size_bytes") if current else None,
                "preserved_size_bytes": original.get("size_bytes") if original else None,
            }
        )

    preserved_body = backup / "SKILL.md"
    preserved_body_sha = preserved_by_path.get("SKILL.md", {}).get("sha256")
    canonical_view = {
        "id": identifier,
        "domain": canonical.get("domain"),
        "origin": canonical.get("origin"),
        "version": canonical.get("version"),
        "status": canonical.get("status"),
        "admission": canonical.get("admission"),
        "description": canonical.get("description"),
        "tags": list(canonical.get("tags", ())),
        "body_sha256": canonical.get("body_sha256"),
        "package_root": package.relative_to(project).as_posix(),
        "package_tree_sha256": canonical_tree,
        "file_count": len(canonical_files),
        "size_bytes": sum(int(row["size_bytes"]) for row in canonical_files),
        "native": True,
        "adapted": bool(canonical.get("adapted")),
    }
    preserved_view = {
        "id": identifier,
        "domain": "user-preserved",
        "origin": f"preserved-original:{canonical.get('origin') or 'unknown'}",
        "version": canonical.get("version"),
        "status": "preserved-read-only",
        "admission": "preserved-read-only",
        "description": _description(preserved_body) if preserved_body.is_file() else None,
        "tags": list(canonical.get("tags", ())),
        "body_sha256": preserved_body_sha,
        "package_root": backup.relative_to(project).as_posix(),
        "package_tree_sha256": preserved_tree,
        "file_count": len(preserved_files),
        "size_bytes": sum(int(row["size_bytes"]) for row in preserved_files),
        "native": False,
        "adapted": False,
    }
    metadata_changes = [
        {
            "field": field,
            "px": canonical_view.get(field),
            "preserved": preserved_view.get(field),
        }
        for field in (
            "version", "description", "body_sha256", "package_tree_sha256",
            "file_count", "size_bytes",
        )
        if canonical_view.get(field) != preserved_view.get(field)
    ]
    return {
        "schema_version": "px.skill-comparison/1.0",
        "skill_id": identifier,
        "comparison_mode": "verified-package-trees-and-metadata",
        "body_hydrated": False,
        "read_only": True,
        "px": canonical_view,
        "preserved": preserved_view,
        "metadata_changes": metadata_changes,
        "file_comparison": {
            "px_file_count": len(canonical_files),
            "preserved_file_count": len(preserved_files),
            "unchanged_file_count": unchanged,
            "changed_file_count": len(changes),
            "returned_change_count": min(len(changes), MAX_COMPARISON_CHANGES),
            "changes_truncated": len(changes) > MAX_COMPARISON_CHANGES,
            "changes": changes[:MAX_COMPARISON_CHANGES],
        },
        "identical": canonical_tree == preserved_tree,
        "authority": (
            "Read-only PX custody comparison; neither package was hydrated, "
            "executed, admitted, promoted, overwritten, or deleted."
        ),
    }


def query_skills(
    root: Path,
    query: str = "",
    *,
    skill_id: str | None = None,
    domains: Iterable[str] = DEFAULT_DOMAINS,
    grants: Iterable[str] = (),
    limit: int = MAX_CANDIDATES,
) -> dict[str, object]:
    requested = {str(value) for value in domains}
    unknown = requested - DOMAINS
    if unknown:
        raise ValueError(f"unknown skill domains: {sorted(unknown)}")
    bounded_limit = max(1, min(MAX_CANDIDATES, int(limit)))
    grant_set = {str(value) for value in grants}
    records = [dict(row) for row in load_index(root).get("records", ())]
    if "user-preserved" in requested:
        records.extend(_preserved_records(root, records))
    visible = [row for row in records if _domain_allowed(str(row.get("domain")), requested, grant_set)]
    denied_domains = sorted(domain for domain in requested if not _domain_allowed(domain, {domain}, grant_set))
    if skill_id:
        exact = [row for row in visible if row.get("id") == skill_id]
        for row in exact:
            row["selection_eligible"] = _record_selectable(row, grant_set)
        return {"schema_version": "px.skill-query/1.0", "mode": "specific", "query": query, "requested_id": skill_id, "requested_domains": sorted(requested), "denied_domains": denied_domains, "candidates": exact[:1], "candidate_limit": bounded_limit, "hydrated": 0}
    query_tokens = _tokens(query)
    ranked: list[tuple[float, str, dict[str, object]]] = []
    for row in visible:
        id_tokens = _tokens(str(row.get("id", "")).replace("-", " "))
        description_tokens = _tokens(row.get("description"))
        tags = _tokens(" ".join(str(value) for value in row.get("tags", ())))
        overlap = len(query_tokens & id_tokens) * 5 + len(query_tokens & tags) * 3 + len(query_tokens & description_tokens)
        if query_tokens and overlap == 0:
            continue
        preference = 0.5 if row.get("native") else 0.0
        score = float(overlap) + preference
        selectable = _record_selectable(row, grant_set)
        if row.get("domain") == "px-standard" and not selectable:
            continue
        candidate = {**row, "selection_eligible": selectable, "score": score, "selection_rationale": f"semantic-overlap={overlap}; native-preference={preference}; domain={row.get('domain')}; selectable={selectable}"}
        ranked.append((-score, str(row.get("id")), candidate))
    candidates = [row for _, _, row in sorted(ranked)[:bounded_limit]]
    return {"schema_version": "px.skill-query/1.0", "mode": "semantic", "query": query, "requested_id": None, "requested_domains": sorted(requested), "denied_domains": denied_domains, "candidates": candidates, "candidate_limit": bounded_limit, "hydrated": 0}


def hydrate_skill(root: Path, skill_id: str, *, domains: Iterable[str] = DEFAULT_DOMAINS, grants: Iterable[str] = ()) -> dict[str, object]:
    decision = query_skills(root, skill_id=skill_id, domains=domains, grants=grants, limit=1)
    if not decision["candidates"]:
        raise PermissionError(f"skill is absent or ineligible: {skill_id}")
    record = decision["candidates"][0]
    if not record.get("selection_eligible"):
        raise PermissionError(f"skill is visible metadata but is not admitted: {skill_id}")
    if not record.get("body_available"):
        raise PermissionError(f"skill is metadata-only and cannot be hydrated: {skill_id}")
    body = (root.resolve() / str(record["body"])).resolve()
    if root.resolve() != body and root.resolve() not in body.parents:
        raise ValueError("skill body escapes PX root")
    raw = read_bounded_bytes(body, max_bytes=MAX_BODY_BYTES)
    content = raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    expected = record["body_sha256"]
    if expected not in {hashlib.sha256(raw).hexdigest(), hashlib.sha256(content.encode("utf-8")).hexdigest()}:
        raise ValueError("skill body hash mismatch")
    return {"schema_version": "px.skill-hydration/1.0", "id": skill_id, "domain": record["domain"], "origin": record["origin"], "body": content, "body_sha256": record["body_sha256"], "hydrated_count": 1, "references_loaded": 0}


def validate_native_packages(root: Path) -> dict[str, object]:
    root = root.resolve()
    errors: list[str] = []
    records = load_index(root).get("records", ())
    native = [row for row in records if row.get("native")]
    for row in native:
        package = root / str(row["package_root"])
        for relative in ("SKILL.md", "capability.json", "skill.yaml", "contracts", "tests", "resources"):
            if not (package / relative).exists():
                errors.append(f"missing:{row['id']}:{relative}")
        try:
            capability = json.loads((package / "capability.json").read_text(encoding="utf-8"))
            yaml_compatible = json.loads((package / "skill.yaml").read_text(encoding="utf-8"))
            if capability != yaml_compatible or capability.get("id") != row.get("id") or capability.get("domain") != row.get("domain"):
                errors.append(f"manifest-mismatch:{row['id']}")
        except (OSError, json.JSONDecodeError):
            errors.append(f"manifest-invalid:{row['id']}")
        try:
            resources = json.loads((package / "resources" / "index.json").read_text(encoding="utf-8"))
            if resources.get("schema_version") != "px.skill-resources/1.0" or not isinstance(resources.get("resources"), list):
                errors.append(f"resource-index-invalid:{row['id']}")
            else:
                for relative in resources["resources"]:
                    target = (package / str(relative)).resolve()
                    if package.resolve() not in target.parents or not target.is_file():
                        errors.append(f"resource-missing:{row['id']}:{relative}")
        except (OSError, json.JSONDecodeError):
            errors.append(f"resource-index-invalid:{row['id']}")
        if (package / "SKILL.md").is_file() and not _body_hash_matches(package / "SKILL.md", str(row.get("body_sha256") or "")):
            errors.append(f"body-hash:{row['id']}")
    return {"valid": not errors, "errors": errors, "native_packages": len(native), "records": len(records), "maximum_candidates": MAX_CANDIDATES}
