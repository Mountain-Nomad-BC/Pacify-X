"""Multi-surface observers for the full governed semantic corpus.

Covers every entity-bearing surface the census must consider, not only Python
and JavaScript symbols: runtime modules, extension sources, contracts and
schemas, skills and skill packages, registries and manifests, policies,
provider and agent definitions, and documentation.

Each observer records the evidence channels available for that surface. A
surface that carries no graph evidence contributes fewer channels rather than
being padded with zeros, so a low channel count means "unknown", not "absent".
"""

from __future__ import annotations

import ast
import json
import re
import hashlib
import tomllib
import yaml
import copy
import fnmatch
from functools import lru_cache
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable

from runtime.semantic_taxonomy import SurfaceEntity, tokenize
from runtime.json_io import decode_json_value, read_bounded_bytes
from .bounded_walk import _is_junction

# Surfaces included in the governed corpus, with their proposed global kinds.
CORPUS_SURFACES: dict[str, dict[str, str]] = {
    "runtime": {"glob": "runtime/**/*.py", "kind": "module", "surface": "runtime"},
    "contracts": {"glob": "contracts/**/*.json", "kind": "contract", "surface": "contracts"},
    "policies": {"glob": "policies/**/*.json", "kind": "policy", "surface": "policies"},
    "skills": {"glob": ".px/skills/**/*.md", "kind": "skill", "surface": "skills"},
    "skill_packages": {"glob": "registry/skill_packages/**/*.json", "kind": "skill", "surface": "skills"},
    "registries": {"glob": "registry/*.json", "kind": "registry", "surface": "registry"},
    "security_graph": {"glob": "registry/security_capabilities/graph.jsonl", "kind": "record", "surface": "registry"},
    "source_manifests": {"glob": "registry/source_skill_manifests/**/*.json", "kind": "manifest", "surface": "registry"},
    "orchestrations": {"glob": "registry/orchestrations/**/*.json", "kind": "orchestration", "surface": "registry"},
    "providers": {"glob": "providers/**/*.json", "kind": "agent", "surface": "providers"},
    "provider_docs": {"glob": "providers/**/*.md", "kind": "documentation", "surface": "providers"},
    "documentation": {"glob": "docs/**/*.md", "kind": "documentation", "surface": "documentation"},
    "extension": {"glob": "extension/src/**/*.js", "kind": "module", "surface": "extension"},
    "tests": {"glob": "tests/**/*.py", "kind": "test", "surface": "tests"},
    "bootstrap": {"glob": ".agentic_engineering_os_px/**/*.json", "kind": "manifest", "surface": "governance"},
    "authored_python": {"glob": "**/*.py", "kind": "module", "surface": "source"},
    "authored_javascript": {"glob": "**/*.js", "kind": "module", "surface": "source"},
    "authored_mjs": {"glob": "**/*.mjs", "kind": "module", "surface": "source"},
    "authored_json": {"glob": "**/*.json", "kind": "document", "surface": "source"},
    "authored_markdown": {"glob": "**/*.md", "kind": "documentation", "surface": "source"},
    "authored_yaml": {"glob": "**/*.yaml", "kind": "manifest", "surface": "source"},
    "authored_yml": {"glob": "**/*.yml", "kind": "manifest", "surface": "source"},
    "authored_toml": {"glob": "**/*.toml", "kind": "manifest", "surface": "source"},
    "authored_jsonl": {"glob": "**/*.jsonl", "kind": "record", "surface": "source"},
    "authored_powershell": {"glob": "**/*.ps1", "kind": "module", "surface": "source"},
}

FALLBACK_SURFACES = frozenset(name for name in CORPUS_SURFACES if name.startswith("authored_"))

_GENERATED_PREFIXES = (
    "node_modules/",
    "registry/operational_gap_ledger.deltas",
    "registry/source-freeze",
)


def _is_generated(relative: str) -> bool:
    return any(relative.startswith(prefix) for prefix in _GENERATED_PREFIXES)


def observe_python(path: Path, root: Path, *, surface: str, kind: str, max_symbols: int | None = None, source_image: str | None = None) -> list[SurfaceEntity]:
    relative = path.relative_to(root).as_posix()
    try:
        source = source_image if source_image is not None else path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source)
    except (SyntaxError, ValueError, OSError):
        return []
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names[:20])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    module_doc = (ast.get_docstring(tree) or "")[:240]
    out: list[SurfaceEntity] = [
        SurfaceEntity(
            key=f"{surface}:module:{relative}",
            surface=surface,
            kind=kind,
            name=path.stem,
            source_path=relative,
            doc=module_doc,
            tokens=tokenize(path.stem),
            imports=tuple(imports[:24]),
        )
    ]
    count = 0
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        child_kind = "class" if isinstance(node, ast.ClassDef) else "function"
        decorators = []
        for decorator in getattr(node, "decorator_list", []) or []:
            try:
                decorators.append(ast.unparse(decorator)[:80])
            except Exception:  # pragma: no cover - unparse is best effort
                decorators.append("")
        bases = []
        for base in getattr(node, "bases", []) or []:
            try:
                bases.append(ast.unparse(base)[:80])
            except Exception:  # pragma: no cover
                bases.append("")
        out.append(
            SurfaceEntity(
                key=f"{surface}:{child_kind}:{relative}:{node.lineno}:{node.name}",
                surface=surface,
                kind=child_kind,
                name=node.name,
                source_path=relative,
                doc=(ast.get_docstring(node) or "")[:240],
                tokens=tokenize(node.name),
                decorators=tuple(item for item in decorators if item),
                imports=tuple(item for item in bases if item),
                line=node.lineno,
            )
        )
        count += 1
        if max_symbols is not None and count >= max_symbols:
            break
    return out


_JSON_TITLE_KEYS = ("title", "name", "id", "$id", "schema_version", "kind", "type", "description")

MAX_JSONL_RECORDS = 10_000


class MetadataParseError(ValueError):
    """Strict structured metadata cannot be parsed completely."""


class MetadataStructureError(ValueError):
    """The parsed value has no supported object metadata declaration."""


class MetadataBudgetError(ValueError):
    """A complete file exceeds its declared extraction budget."""


class MetadataUnavailableError(ValueError):
    """A required native syntax observer is not available on this host."""


def observe_powershell(path: Path, root: Path, *, surface: str, kind: str,
                       source_image: str | None = None, provenance: dict | None = None) -> list[SurfaceEntity]:
    from runtime.semantic_powershell_source import (
        parse_powershell_source, PowerShellSyntaxError, PowerShellBudgetError,
        PowerShellUnavailable, PowerShellSourceError,
    )
    text = source_image if source_image is not None else read_bounded_bytes(path, max_bytes=MAX_SOURCE_BYTES).decode("utf-8-sig")
    try:
        report = parse_powershell_source(root, text)
    except PowerShellSyntaxError as exc:
        raise MetadataParseError(str(exc)) from exc
    except PowerShellBudgetError as exc:
        raise MetadataBudgetError(str(exc)) from exc
    except (PowerShellUnavailable, PowerShellSourceError) as exc:
        raise MetadataUnavailableError(str(exc)) from exc
    relative = path.relative_to(root).as_posix()
    rows = [SurfaceEntity(key=f"{surface}:module:{relative}", surface=surface,
                          kind=kind, name=path.stem, source_path=relative,
                          tokens=tokenize(path.stem))]
    for symbol in report["symbols"]:
        rows.append(SurfaceEntity(
            key=f"{surface}:{symbol['kind']}:{relative}:{symbol['start_offset']}:{symbol['name']}",
            surface=surface, kind=symbol["kind"], name=symbol["name"],
            source_path=relative, line=symbol["line"], tokens=tokenize(symbol["name"]),
        ))
    if provenance is not None:
        provenance.update({k: report[k] for k in ("schema_version", "parser_version", "source_sha256", "parser_executable_sha256")})
    return rows


def observe_jsonl(path: Path, root: Path, *, surface: str, kind: str,
                  source_image: str | None = None) -> list[SurfaceEntity]:
    return _observe_jsonl_metadata(path, root, surface=surface, kind=kind,
                                  source_image=source_image, record_limit=MAX_JSONL_RECORDS)


def observe_security_graph(path: Path, root: Path, *, surface: str, kind: str,
                           source_image: str | None = None) -> list[SurfaceEntity]:
    """Reuse the established decoder for this exact source owner; metadata only."""
    from runtime.cybersecurity_provider import decode_security_jsonl, MAX_SECURITY_JSONL_RECORDS
    raw = (source_image.encode("utf-8") if source_image is not None
           else read_bounded_bytes(path, max_bytes=MAX_SOURCE_BYTES))
    if len(raw) > MAX_SOURCE_BYTES:
        raise MetadataBudgetError("Security graph exceeds shared source acquisition budget")
    try:
        records = decode_security_jsonl(raw)
    except ValueError as exc:
        if "budget" in str(exc):
            raise MetadataBudgetError(str(exc)) from exc
        raise MetadataParseError(str(exc)) from exc
    return _observe_jsonl_metadata(path, root, surface=surface, kind=kind,
        source_image=raw.decode("utf-8"), record_limit=MAX_SECURITY_JSONL_RECORDS,
        decoded_records=records)


def _observe_jsonl_metadata(path: Path, root: Path, *, surface: str, kind: str,
                           source_image: str | None, record_limit: int,
                           decoded_records: tuple[dict, ...] | None = None) -> list[SurfaceEntity]:
    """Propose every object record with its actual line; never admit execution.

    Line-shaped keys are observation locators, not canonical entity identities.
    A malformed/unsupported tail or budget failure rejects the entire file.
    """
    relative = path.relative_to(root).as_posix()
    text = source_image if source_image is not None else read_bounded_bytes(path, max_bytes=MAX_SOURCE_BYTES).decode("utf-8")
    if len(text.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise MetadataBudgetError("JSONL source acquisition budget exceeded")
    # JSONL separates records with LF, not Unicode separators inside strings.
    lines = text.split("\n")
    if lines[-1] == "":
        lines.pop()
    if len(lines) > record_limit:
        raise MetadataBudgetError("JSONL record count exceeds complete-file extraction budget")
    if decoded_records is not None and len(decoded_records) != len(lines):
        raise MetadataParseError("Native graph decoder records differ from source line geometry")
    # An empty stream has a real file container and zero experience records.
    # This is source inventory metadata, never fabricated journal history.
    rows = [SurfaceEntity(key=f"{surface}:container:{relative}", surface=surface,
        kind="document", name=path.stem, source_path=relative,
        doc="JSONL file container; records are separate proposed metadata observations.",
        tokens=tokenize(path.stem))]
    for line_number, line in enumerate(lines, 1):
        if not line.strip() or line.startswith("\ufeff"):
            raise MetadataParseError(f"JSONL line {line_number} is blank or contains a BOM")
        try:
            document = (decoded_records[line_number - 1] if decoded_records is not None
                        else decode_json_value(line.encode("utf-8"), max_bytes=MAX_SOURCE_BYTES))
        except ValueError as exc:
            raise MetadataParseError(f"JSONL line {line_number}: {exc}") from exc
        if type(document) is not dict:
            raise MetadataStructureError(f"JSONL line {line_number} is not an object")
        title = next((document[key].strip()[:120] for key in _JSON_TITLE_KEYS
                      if isinstance(document.get(key), str) and document[key].strip()),
                     f"{path.stem} record {line_number}")
        description = document.get("description")
        refs = tuple(value for key, value in document.items()
                     if key in {"$ref", "schema", "contract", "ref"} and type(value) is str)
        if any(len(value.encode("utf-8")) > 512 for value in refs):
            raise MetadataBudgetError("JSONL reference metadata exceeds complete-record budget")
        rows.append(SurfaceEntity(key=f"{surface}:{kind}:{relative}:jsonl:{line_number}",
            surface=surface, kind=kind, name=title, source_path=relative,
            doc=description[:240] if type(description) is str else "",
            tokens=tokenize(title) + tokenize(path.stem), referenced_schemas=refs, line=line_number))
    return rows


def observe_json(path: Path, root: Path, *, surface: str, kind: str, source_image: str | None = None) -> list[SurfaceEntity]:
    relative = path.relative_to(root).as_posix()
    if _is_generated(relative):
        return []
    try:
        raw = source_image if source_image is not None else path.read_text(encoding="utf-8-sig")
    except OSError:
        return []
    try:
        document = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(document, dict):
        return []
    title = ""
    for key in _JSON_TITLE_KEYS:
        value = document.get(key)
        if isinstance(value, str) and value.strip():
            title = value.strip()[:120]
            break
    if not title:
        title = path.stem
    description = str(document.get("description") or "")[:240]
    return [
        SurfaceEntity(
            key=f"{surface}:{kind}:{relative}",
            surface=surface,
            kind=kind,
            name=title,
            source_path=relative,
            doc=description,
            tokens=tokenize(title) + tokenize(path.stem),
            referenced_schemas=tuple(
                str(value)[:100] for value in _collect_refs(document)[:8]
            ),
        )
    ]


def _collect_refs(value: object, depth: int = 0) -> list[str]:
    """Collect schema references without walking unbounded structures."""
    if depth > 4:
        return []
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(key, str) and key in {"$ref", "schema", "contract", "ref"} and isinstance(item, str):
                found.append(item)
            found.extend(_collect_refs(item, depth + 1))
    elif isinstance(value, list):
        for item in value[:200]:
            found.extend(_collect_refs(item, depth + 1))
    return found


def observe_markdown(path: Path, root: Path, *, surface: str, kind: str, source_image: str | None = None) -> list[SurfaceEntity]:
    relative = path.relative_to(root).as_posix()
    try:
        text = (source_image if source_image is not None else path.read_text(encoding="utf-8-sig"))[:4000]
    except OSError:
        return []
    heading = ""
    for line in text.splitlines():
        if line.strip().startswith("#"):
            heading = line.strip().lstrip("#").strip()[:120]
            break
    name = heading or path.stem
    body = " ".join(text.split())[:240]
    return [
        SurfaceEntity(
            key=f"{surface}:{kind}:{relative}",
            surface=surface,
            kind=kind,
            name=name,
            source_path=relative,
            doc=body,
            tokens=tokenize(name) + tokenize(path.stem),
        )
    ]


def observe_javascript(path: Path, root: Path, *, surface: str, kind: str, source_image: str | None = None) -> list[SurfaceEntity]:
    relative = path.relative_to(root).as_posix()
    try:
        text = source_image if source_image is not None else path.read_text(encoding="utf-8-sig")
    except OSError:
        return []
    out = [
        SurfaceEntity(
            key=f"{surface}:module:{relative}",
            surface=surface,
            kind="module",
            name=path.stem,
            source_path=relative,
            tokens=tokenize(path.stem),
        )
    ]
    pattern = re.compile(
        r"^(?:export\s+)?(?:async\s+)?(?:function|class)\s+([A-Za-z_$][\w$]*)", re.MULTILINE
    )
    for match in pattern.finditer(text):
        name = match.group(1)
        line = text.count("\n", 0, match.start()) + 1
        out.append(
            SurfaceEntity(
                key=f"{surface}:symbol:{relative}:{line}:{name}",
                surface=surface,
                kind="function",
                name=name,
                source_path=relative,
                tokens=tokenize(name),
                line=line,
            )
        )
    return out


CENSUS_GENERATOR = "px.semantic-surfaces/2.4"
SOURCE_BINDING_SCHEMA = Path(__file__).resolve().parents[1] / "contracts/semantic/source-census-binding.schema.json"
MAX_SOURCE_BYTES = 8 * 1024 * 1024


def _authored_source_policy_sha256() -> str:
    from runtime.semantic_authored_sources import policy_sha256
    return policy_sha256()


from runtime.hash_utils import json_utf8_hash as _digest


def _current_source_binding(report: dict) -> dict | None:
    """Bind source observations without discarding the separate physical audit."""
    from runtime.source_boundary import AUTHORED
    if not report["accounting_complete"] or not report["source_revision_complete"]:
        return None
    fields = (
        "source_revision", "generator", "generator_sha256", "generator_dependencies",
        "taxonomy_seed_sha256", "source_boundary_sha256", "worthiness_policy_sha256",
        "authored_source_policy_sha256", "owner_set", "exclusion_rules", "surface_limit",
        "entities_observed",
        "entities_sha256", "accounting_complete", "source_revision_complete",
        "extraction_complete", "canonical_identity_authority", "execution_authority",
    )
    binding = {key: copy.deepcopy(report[key]) for key in fields}
    binding["schema_version"] = "px.source-census-binding/1.0"
    binding["binding_schema_sha256"] = hashlib.sha256(SOURCE_BINDING_SCHEMA.read_bytes()).hexdigest()
    binding["authored_files"] = [copy.deepcopy(row) for row in report["files"] if row["classification"] == AUTHORED]
    from runtime.contracts import validate_instance
    validate_instance(binding, SOURCE_BINDING_SCHEMA)
    return binding


def _source_glob_matches(relative: str, pattern: str) -> bool:
    """Segment-aware recursive globs on every supported Python (3.11+)."""
    parts, patterns = relative.split("/"), pattern.split("/")
    @lru_cache(maxsize=None)
    def match(index: int, pattern_index: int) -> bool:
        if pattern_index == len(patterns):
            return index == len(parts)
        if patterns[pattern_index] == "**":
            return match(index, pattern_index + 1) or (
                index < len(parts) and match(index + 1, pattern_index))
        return index < len(parts) and fnmatch.fnmatch(parts[index], patterns[pattern_index]) and match(index + 1, pattern_index + 1)
    return match(0, 0)


@dataclass(frozen=True)
class CorpusSnapshot:
    _entities: tuple[SurfaceEntity, ...]
    _report_json: str

    @property
    def entities(self) -> tuple[SurfaceEntity, ...]:
        return copy.deepcopy(self._entities)

    def report(self) -> dict:
        """Return a defensive copy; report hashes describe proposals, not authority."""
        return json.loads(self._report_json)


def collect_corpus_snapshot(
    root: Path,
    *,
    surfaces: Iterable[str] | None = None,
    per_surface_limit: int | None = None,
) -> CorpusSnapshot:
    """Account every source file, including failed or unsupported extraction.

    Optional surface budgets are explicit samples. They never establish complete
    extraction. Unconfigured authored files remain in the denominator without
    receiving guessed semantic identities.
    """
    from runtime.source_boundary import classify_path, AUTHORED, agent_experience_directories
    from runtime.bounded_walk import bounded_walk, WalkLimits
    from runtime.semantic_entity_worthiness import assess_entity_worthiness
    root = Path(root).resolve(strict=True)
    agent_directories = agent_experience_directories(root)
    chosen = list(CORPUS_SURFACES) if surfaces is None else list(surfaces)
    if len(chosen) != len(set(chosen)) or any(name not in CORPUS_SURFACES for name in chosen):
        raise ValueError("Unknown or duplicate census surface")
    if per_surface_limit is not None and (type(per_surface_limit) is not int or per_surface_limit < 1):
        raise ValueError("Surface limit must be a positive integer or None")
    limits = WalkLimits(max_files=50000, max_bytes=2 * 1024 * 1024 * 1024,
                        max_duration_seconds=60)
    # The canonical bounded walker fails closed on links, inaccessible trees
    # and resource exhaustion rather than returning a silently partial census.
    inventory = bounded_walk(root, limits=limits)
    matched = {entry.relative: [name for name in chosen
               if _source_glob_matches(entry.relative, CORPUS_SURFACES[name]["glob"])]
               for entry in inventory.files}
    for relative, names in matched.items():
        primary = [name for name in names if name not in FALLBACK_SURFACES]
        matched[relative] = primary or names
    collected: list[SurfaceEntity] = []
    dispositions = []
    source_metadata_seen = {}
    produced = {name: 0 for name in chosen}
    # The canonical classifier owns the source boundary, not the glob catalog.
    for entry in sorted(inventory.files, key=lambda entry: entry.relative):
        path, relative = entry.path, entry.relative
        classification = classify_path(relative, agent_directories=agent_directories)
        names = matched.get(relative, [])
        if not names and classification["classification"] != AUTHORED:
            continue
        row = {"path": relative, "classification": classification["classification"],
               "owner": classification["owner"], "surfaces": names, "sha256": None,
               "entity_count": 0, "disposition": "pending", "reason": ""}
        dispositions.append(row)
        if classification["classification"] != AUTHORED:
            row.update(disposition="excluded", reason=classification["reason"])
            continue
        try:
            # Reject links in ancestors too; never follow an external source.
            if any(p.is_symlink() or _is_junction(p) for p in (path, *path.parents) if p != root.parent):
                row.update(disposition="unsafe_link", reason="Link or junction is not an admitted source image")
                continue
            info = path.stat()
            source_metadata_seen[relative] = (info.st_dev, info.st_ino, info.st_size,
                                              info.st_mtime_ns, info.st_ctime_ns)
            with path.open("rb") as stream:
                raw = stream.read(MAX_SOURCE_BYTES + 1)
            if len(raw) > MAX_SOURCE_BYTES:
                row.update(disposition="budget_exhausted", reason="Source exceeds bounded read budget; hash unavailable")
                continue
            row["sha256"] = hashlib.sha256(raw).hexdigest()
            if _is_generated(relative):
                row.update(disposition="excluded", reason="Explicit generated exclusion")
                continue
            if not names:
                # No glob catalog owns this path. A reviewed format owner or an
                # explicit non-entity policy may still resolve it; otherwise the
                # row stays honestly unresolved in the denominator.
                from runtime.semantic_authored_sources import (
                    AuthoredSourceParseError, AuthoredSourceStructureError,
                    extract_owned, format_owner, reviewed_non_entity,
                )
                if format_owner(relative) is None:
                    policy = reviewed_non_entity(relative)
                    if policy is not None:
                        row.update(disposition="intentionally_unclassified",
                                   reason=f"{policy.policy_id}: {policy.reason}",
                                   unclassified_policy_id=policy.policy_id)
                    else:
                        row.update(disposition="unsupported_surface",
                                   reason="No admitted extraction owner")
                    continue
                try:
                    owner, rows = extract_owned(relative, raw)
                except AuthoredSourceParseError as exc:
                    row.update(disposition="parse_error", reason=str(exc))
                    continue
                except AuthoredSourceStructureError as exc:
                    row.update(disposition="unsupported_structure", reason=str(exc))
                    continue
                with path.open("rb") as stream:
                    after = stream.read(MAX_SOURCE_BYTES + 1)
                if after != raw:
                    row.update(disposition="source_drift", reason="Source changed during extraction")
                    continue
                if not rows:
                    row.update(disposition="extraction_error", reason="Observer produced no declaration")
                    continue
                collected.extend(rows)
                produced[owner.format_id] = produced.get(owner.format_id, 0) + len(rows)
                row.update(disposition="observed", entity_count=len(rows),
                           extractor_format_id=owner.format_id)
                continue
            name = names[0]
            if len(names) > 1:
                row.update(disposition="conflicting_surface", reason="Multiple extraction owners")
                continue
            config = CORPUS_SURFACES[name]
            worthiness = assess_entity_worthiness(root, relative, config["kind"], surface=config["surface"])
            if config["kind"] != "skill" and not worthiness.admitted:
                row.update(disposition="excluded", reason=worthiness.reason)
                continue
            text = raw.decode("utf-8-sig", errors="strict")
            suffix = path.suffix.lower()
            if suffix == ".py":
                ast.parse(text)
                observer = observe_python
            elif suffix == ".json":
                if not isinstance(json.loads(text), dict):
                    row.update(disposition="unsupported_structure", reason="JSON root has no admitted entity declaration")
                    continue
                observer = observe_json
            elif suffix == ".jsonl":
                if raw.startswith(b"\xef\xbb\xbf"):
                    raise MetadataParseError("JSONL BOM is not permitted")
                observer = observe_security_graph if name == "security_graph" else observe_jsonl
            elif suffix in {".toml", ".yaml", ".yml"}:
                document = tomllib.loads(text) if suffix == ".toml" else yaml.safe_load(text)
                if not isinstance(document, dict):
                    row.update(disposition="unsupported_structure", reason="Structured root has no admitted entity declaration")
                    continue
                # Only mapping metadata is proposed; YAML never creates an
                # executable workflow or canonical identity from its presence.
                metadata = {key: value for key, value in document.items()
                            if key in _JSON_TITLE_KEYS and isinstance(value, str)}
                text = json.dumps(metadata)
                observer = observe_json
            elif suffix in {".md", ".markdown"}:
                observer = observe_markdown
            elif suffix in {".js", ".mjs"}:
                observer = observe_javascript
            elif suffix == ".ps1":
                observer = observe_powershell
            else:
                row.update(disposition="unsupported_surface", reason="No format extractor")
                continue
            observer_options = {"source_image": text}
            if suffix == ".ps1":
                row["extractor_provenance"] = {}
                observer_options["provenance"] = row["extractor_provenance"]
            rows = observer(path, root, surface=config["surface"], kind=config["kind"], **observer_options)
            with path.open("rb") as stream:
                after = stream.read(MAX_SOURCE_BYTES + 1)
            if after != raw:
                row.update(disposition="source_drift", reason="Source changed during extraction")
                continue
            if not rows:
                row.update(disposition="extraction_error", reason="Observer produced no declaration")
                continue
            if per_surface_limit is not None and produced[name] + len(rows) > per_surface_limit:
                row.update(disposition="budget_exhausted", reason="Whole-file extraction exceeds selected surface sample budget")
                continue
            collected.extend(rows)
            produced[name] += len(rows)
            row.update(disposition="observed", entity_count=len(rows))
            if suffix == ".jsonl":
                row["record_count"] = len(rows) - 1
        except MetadataBudgetError as exc:
            row.update(disposition="budget_exhausted", reason=str(exc))
        except MetadataStructureError as exc:
            row.update(disposition="unsupported_structure", reason=str(exc))
        except MetadataParseError as exc:
            row.update(disposition="parse_error", reason=str(exc))
        except MetadataUnavailableError as exc:
            row.update(disposition="extractor_unavailable", reason=str(exc))
        except (SyntaxError, json.JSONDecodeError, tomllib.TOMLDecodeError, yaml.YAMLError) as exc:
            row.update(disposition="parse_error", reason=type(exc).__name__)
        except UnicodeError:
            row.update(disposition="encoding_error", reason="Source is not strict UTF-8")
        except OSError as exc:
            row.update(disposition="read_error", reason=type(exc).__name__)
    keys = [entity.key for entity in collected]
    if len(keys) != len(set(keys)):
        raise ValueError("Duplicate extracted entity key")
    final_inventory = bounded_walk(root, limits=limits)
    def source_metadata(entries):
        return [(entry.relative, entry.size) for entry in entries
                if classify_path(entry.relative, agent_directories=agent_directories)["classification"] == AUTHORED]
    inventory_stable = (source_metadata(inventory.files) == source_metadata(final_inventory.files)
                        and agent_directories == agent_experience_directories(root))
    authored_rows = {row["path"]: row for row in dispositions if row["classification"] == AUTHORED}
    for entry in final_inventory.files:
        if entry.relative not in source_metadata_seen:
            continue
        try:
            info = entry.path.stat()
            if source_metadata_seen[entry.relative] != (info.st_dev, info.st_ino, info.st_size,
                                                       info.st_mtime_ns, info.st_ctime_ns):
                inventory_stable = False
            row = authored_rows[entry.relative]
            if row["sha256"] is not None:
                # Stat metadata is a hint: same-size rewrites may retain or
                # restore timestamps. Recheck the bounded actual byte image.
                with entry.path.open("rb") as stream:
                    latest = stream.read(MAX_SOURCE_BYTES + 1)
                if len(latest) > MAX_SOURCE_BYTES or hashlib.sha256(latest).hexdigest() != row["sha256"]:
                    inventory_stable = False
                    row.update(disposition="source_drift", reason="Source content changed after extraction")
        except OSError as exc:
            inventory_stable = False
            authored_rows[entry.relative].update(disposition="source_drift", reason=f"Final source verification failed: {type(exc).__name__}")
    revision_complete = inventory_stable and all(r["sha256"] is not None
                        for r in dispositions if r["classification"] == AUTHORED)
    report = {"schema_version": "px.source-extraction-census/1.0", "generator": CENSUS_GENERATOR,
              "generator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "taxonomy_seed_sha256": hashlib.sha256(Path(__file__).with_name("semantic_taxonomy.py").read_bytes()).hexdigest(),
              "source_boundary_sha256": hashlib.sha256(Path(__file__).with_name("source_boundary.py").read_bytes()).hexdigest(),
              "worthiness_policy_sha256": hashlib.sha256(Path(__file__).with_name("semantic_entity_worthiness.py").read_bytes()).hexdigest(),
              "authored_source_policy_sha256": _authored_source_policy_sha256(),
              "owner_set": chosen, "exclusion_rules": list(_GENERATED_PREFIXES),
              "surface_limit": per_surface_limit, "files": dispositions,
              "source_revision": _digest([(r["path"], r["sha256"], r["classification"]) for r in dispositions if r["classification"] == AUTHORED]) if revision_complete else None,
              "source_revision_complete": revision_complete,
              "accounting_complete": inventory_stable,
              "extraction_complete": revision_complete and all(r["disposition"] in {"observed", "excluded"} for r in dispositions) and surfaces is None,
              "execution_authority": False, "canonical_identity_authority": False,
              "entities_observed": len(collected),
              "entities_sha256": _digest([asdict(e) for e in collected])}
    report["generator_dependencies"] = {"runtime/semantic_authored_sources.py":
        hashlib.sha256(Path(__file__).with_name("semantic_authored_sources.py").read_bytes()).hexdigest()}
    if "security_graph" in chosen:
        report["generator_dependencies"]["runtime/cybersecurity_provider.py"] = hashlib.sha256(
            Path(__file__).with_name("cybersecurity_provider.py").read_bytes()).hexdigest()
    if "authored_powershell" in chosen:
        report["generator_dependencies"]["runtime/semantic_powershell_source.py"] = hashlib.sha256(
            Path(__file__).with_name("semantic_powershell_source.py").read_bytes()).hexdigest()
    report["source_binding"] = _current_source_binding(report)
    report["source_binding_sha256"] = _digest(report["source_binding"]) if report["source_binding"] is not None else None
    report["result_sha256"] = _digest(report)
    return CorpusSnapshot(tuple(collected), json.dumps(report, sort_keys=True, ensure_ascii=False))


def collect_corpus(root: Path, *, surfaces: Iterable[str] | None = None,
                   per_surface_limit: int | None = None) -> list[SurfaceEntity]:
    """Compatibility entity view; completeness lives in the snapshot report."""
    return list(collect_corpus_snapshot(root, surfaces=surfaces, per_surface_limit=per_surface_limit).entities)
