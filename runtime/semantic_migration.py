"""Deterministic, identity-bound physical remap planning and reference compilation.

This owner performs no rename, build, install or Git operation. Its proposal is
the input to an explicitly admitted transaction, never transaction authority.
"""
from __future__ import annotations

import ast
import hashlib
from pathlib import Path
import re
from typing import Mapping

from .archive_io import portable_member_name, reject_path_links
from .json_io import bounded_canonical_json_bytes, read_bounded_bytes
from .semantic_entity import EntityRegistry
from .semantic_locator import LocatorRegistry
from .source_boundary import authored_paths

MAX_PLAN_BYTES = 32 * 1024 * 1024
MAX_FILE_BYTES = 8 * 1024 * 1024
TEXT_SUFFIXES = {".py", ".js", ".cjs", ".mjs", ".ts", ".tsx", ".json", ".jsonl", ".yaml", ".yml", ".toml", ".md", ".ps1", ".txt", ".html", ".css"}


def _hash(value):
    return hashlib.sha256(bounded_canonical_json_bytes(value, max_bytes=MAX_PLAN_BYTES)).hexdigest()


def _path(root, relative):
    portable_member_name(relative, allow_directory=False, max_bytes=1024)
    path = root / relative
    reject_path_links(path)
    if not path.resolve().is_relative_to(root):
        raise ValueError("migration path escapes preserved root")
    return path


def _module(path):
    parts = Path(path).with_suffix("").parts
    if parts[-1] == "__init__":
        parts = parts[:-1]
    if not parts or any(not part.isidentifier() for part in parts):
        return None
    return ".".join(parts)


#: Reference classes produced by the compiler. A class is a factual statement
#: about what could be proven mechanically, never a guess:
#:   * mechanically_proven  - the exact reference is rewritten deterministically;
#:   * dynamically_unresolved - a runtime/dynamic form that cannot be proven;
#:   * ambiguous            - a literal that matches more than one remap target;
#:   * manual_blocker       - a form requiring human review before rewrite.
REFERENCE_CLASSES = ("mechanically_proven", "dynamically_unresolved", "ambiguous", "manual_blocker")

_JS_IMPORT = re.compile(
    r"(?P<lead>\b(?:import|export)\b[^;\n]*?\bfrom\s*|\brequire\s*\(\s*|\bimport\s*\(\s*)(?P<q>['\"])(?P<spec>[^'\"]+)(?P=q)"
)
_JS_BARE_DYNAMIC = re.compile(
    r"\b(?:require|import)\s*\(\s*(?!['\"])(?P<expr>[^)]{1,200})\)"
)
_MD_LINK = re.compile(r"(?P<open>\]\(|<)(?P<href>[^)\s<>]+)(?P<close>\)|>)")
_JSON_REF_KEYS = ("$ref", "reference", "path", "file", "source", "target", "include", "extends")


def _classify_literal(reference, paths):
    """Classify one literal reference against the remap set without rewriting.

    A literal that is exactly a remapped source (or a ``./``-relative suffix of
    one) is mechanically proven; a literal that matches more than one candidate is
    ambiguous; anything else is not a remap reference at all.
    """
    hits = []
    normalized = reference.replace("\\", "/")
    for old, new in paths.items():
        if normalized == old or normalized == old.lstrip("./") or normalized.endswith("/" + old.lstrip("./")):
            hits.append((old, new))
    if len(hits) > 1:
        return "ambiguous", None
    if len(hits) == 1:
        return "mechanically_proven", hits[0]
    return None, None


def _rewrite_js_imports(text, paths, *, relative):
    """Rewrite mechanically-provable JS/TS import/require/export specifiers.

    Only literal specifiers are touched. A dynamic specifier (a computed
    expression) is reported, never rewritten.
    """
    unresolved = []
    for match in _JS_BARE_DYNAMIC.finditer(text):
        unresolved.append({"path": relative, "reference": match.group("expr")[:120],
                           "reason": "dynamic-import-review"})

    def replace(match):
        spec = match.group("spec")
        klass, hit = _classify_literal(spec, paths)
        if klass == "mechanically_proven":
            old, new = hit
            new_spec = spec.replace(old, new)
            return match.group(0).replace(match.group("q") + spec + match.group("q"),
                                          match.group("q") + new_spec + match.group("q"))
        if klass == "ambiguous":
            unresolved.append({"path": relative, "reference": spec, "reason": "ambiguous-reference"})
        return match.group(0)

    return _JS_IMPORT.sub(replace, text), unresolved


def _rewrite_markdown_links(text, paths, *, relative):
    unresolved = []

    def replace(match):
        href = match.group("href")
        klass, hit = _classify_literal(href, paths)
        if klass == "mechanically_proven":
            old, new = hit
            return match.group(0).replace(href, href.replace(old, new))
        if klass == "ambiguous":
            unresolved.append({"path": relative, "reference": href, "reason": "ambiguous-reference"})
        return match.group(0)

    return _MD_LINK.sub(replace, text), unresolved


def _rewrite_structured_references(text, paths, *, relative):
    """Rewrite structured JSON/YAML references under known reference keys.

    A structured document is parsed as JSON when possible so only real reference
    values are touched. YAML/TOML without a JSON parser falls back to a bounded
    line-scoped key match; anything not matched stays a manual blocker.
    """
    unresolved = []
    try:
        import json as _json
        document = _json.loads(text)
    except (ValueError, TypeError):
        # Not JSON (e.g. YAML/TOML). Only rewrite an exact quoted reference on a
        # line that names a known reference key; everything else is untouched.
        lines = []
        for line in text.splitlines(keepends=True):
            matched = False
            for key in _JSON_REF_KEYS:
                for quote in ('"', "'"):
                    for old, new in paths.items():
                        needle = key + ": " + quote + old + quote
                        if needle in line:
                            line = line.replace(quote + old + quote, quote + new + quote)
                            matched = True
            if not matched and any(key + ":" in line for key in _JSON_REF_KEYS):
                unresolved.append({"path": relative, "reason": "unparsed-structured-reference"})
            lines.append(line)
        return "".join(lines), unresolved

    changed = False

    def walk(node):
        nonlocal changed
        if isinstance(node, dict):
            for key, value in list(node.items()):
                if key in _JSON_REF_KEYS and isinstance(value, str):
                    klass, hit = _classify_literal(value, paths)
                    if klass == "mechanically_proven":
                        old, new = hit
                        node[key] = value.replace(old, new)
                        changed = True
                    elif klass == "ambiguous":
                        unresolved.append({"path": relative, "reference": value, "reason": "ambiguous-reference"})
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(document)
    if not changed:
        return text, unresolved
    import json as _json
    return _json.dumps(document, indent=2, sort_keys=True) + "\n", unresolved


def plan_remap(root, entities, locators, requests, *, compact_addresses, allowed_roots,
               max_windows_path=240):
    """Pin actual source images and stable canonical identity before any move."""
    reject_path_links(Path(root))
    root = Path(root).resolve(strict=True)
    if type(entities) is not EntityRegistry or type(locators) is not LocatorRegistry:
        raise TypeError("migration requires native entity and locator owners")
    requests = tuple(requests)
    if not 1 <= len(requests) <= 1000 or not isinstance(compact_addresses, Mapping):
        raise ValueError("bounded exact remap and compact address binding required")
    scopes = tuple(portable_member_name(scope, allow_directory=False) for scope in allowed_roots)
    if not scopes or type(max_windows_path) is not int or not 80 <= max_windows_path <= 32760:
        raise ValueError("explicit repository layout and Windows path policy required")
    inventory = authored_paths(root)
    occupied = {name.casefold(): name for name in inventory}
    rows, issues = [], []
    seen_entities, seen_sources, seen_targets = set(), set(), set()
    for request in sorted(requests, key=lambda item: item["entity_id"]):
        if set(request) != {"entity_id", "target", "reason"}:
            raise ValueError("remap request must contain exact entity, target and reason")
        entity_id, target, reason = request["entity_id"], request["target"], request["reason"]
        entity = entities.get(entity_id)
        locator = locators.get(entity_id, "file")
        if entity is None or entity.lifecycle_state != "accepted" or locator is None:
            raise ValueError("remap requires accepted canonical identity and current file locator")
        source = locator.reference
        if entity_id in seen_entities or source.casefold() in seen_sources or target.casefold() in seen_targets:
            raise ValueError("duplicate migration identity or case-insensitive path collision")
        seen_entities.add(entity_id); seen_sources.add(source.casefold()); seen_targets.add(target.casefold())
        source_path, target_path = _path(root, source), _path(root, target)
        if source not in inventory or not source_path.is_file():
            raise ValueError("only canonical authored files may be remapped")
        if not any(target == scope or target.startswith(scope + "/") for scope in scopes):
            raise ValueError("target outside explicit repository layout policy")
        if type(reason) is not str or not reason.strip() or len(reason) > 512 or target == source:
            raise ValueError("bounded remap reason and different target required")
        address = compact_addresses.get(entity_id)
        if not isinstance(address, Mapping) or address.get("entity_id") != entity_id:
            raise ValueError("exact existing compact address required")
        risks = []
        if target.casefold() in occupied or target_path.exists(): risks.append("occupied-target")
        if source.casefold() == target.casefold(): risks.append("case-only-rename")
        if len(str(target_path)) > max_windows_path: risks.append("windows-path-length")
        if source_path.suffix == ".py" and _module(target) is None: risks.append("invalid-python-module")
        if source_path.name == "__init__.py": risks.append("package-boundary-review")
        raw = bytes(read_bounded_bytes(source_path, max_bytes=MAX_FILE_BYTES))
        row = {"entity_id": entity_id, "source": source, "target": target,
               "locator_id": locator.locator_id, "locator_revision": locator.revision,
               "source_sha256": hashlib.sha256(raw).hexdigest(), "source_bytes": len(raw),
               "compact_address": dict(address), "reason": reason, "risks": risks,
               "review_required": bool(risks)}
        rows.append(row)
        issues.extend({"entity_id": entity_id, "reason": risk} for risk in risks)
    body = {"schema_version": "px.semantic-remap-proposal/1.0", "mappings": rows,
            "entity_snapshot_sha256": hashlib.sha256(entities.snapshot_bytes()).hexdigest(),
            "locator_snapshot_sha256": hashlib.sha256(locators.snapshot_bytes()).hexdigest(),
            "inventory_sha256": _hash(inventory), "allowed_roots": list(scopes),
            "max_windows_path": max_windows_path, "blocking_issues": issues,
            "git_starting_commit": "explicitly deferred by owner decision for this campaign",
            "authority_granted": False}
    return {**body, "proposal_sha256": _hash(body)}


def compile_remap(root, proposal):
    """Compile exact references; uncertain dynamic uses remain blocking items."""
    reject_path_links(Path(root)); root = Path(root).resolve(strict=True)
    unsigned = {key: value for key, value in proposal.items() if key != "proposal_sha256"}
    if proposal.get("proposal_sha256") != _hash(unsigned) or proposal.get("authority_granted") is not False:
        raise ValueError("intact non-authoritative remap proposal required")
    inventory = authored_paths(root)
    if _hash(inventory) != proposal["inventory_sha256"]:
        raise ValueError("migration source inventory changed")
    mappings = proposal["mappings"]
    changes, unresolved, observed = [], list(proposal["blocking_issues"]), []
    paths = {row["source"]: row["target"] for row in mappings}
    modules = {_module(old): _module(new) for old, new in paths.items()
               if old.endswith(".py") and _module(old) and _module(new)}
    total = 0
    for relative in inventory:
        path = _path(root, relative)
        if not path.is_file(): continue
        raw = bytes(read_bounded_bytes(path, max_bytes=MAX_FILE_BYTES))
        total += len(raw)
        if total > 512 * 1024 * 1024: raise ValueError("migration inventory byte budget exhausted")
        before = hashlib.sha256(raw).hexdigest()
        observed.append({"path": relative, "sha256": before, "bytes": len(raw)})
        if path.suffix.lower() not in TEXT_SUFFIXES: continue
        try: text = raw.decode("utf-8")
        except UnicodeError:
            unresolved.append({"path": relative, "reason": "non-utf8-reference-owner"}); continue
        candidate = text
        # Quoted exact paths are mechanical references. Free text, path prefixes,
        # escaped Windows spellings and generated/dynamic names require review.
        for old, new in paths.items():
            for quote in ('"', "'"):
                candidate = candidate.replace(quote + old + quote, quote + new + quote)
            if old in candidate or old.replace("/", "\\") in candidate:
                unresolved.append({"path": relative, "reference": old, "reason": "nonliteral-or-prefix-reference"})
        if path.suffix == ".py":
            try:
                tree = ast.parse(candidate)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Call) and ((isinstance(node.func, ast.Name) and node.func.id == "__import__") or
                            (isinstance(node.func, ast.Attribute) and node.func.attr in {"import_module", "spec_from_file_location"})):
                        unresolved.append({"path": relative, "line": node.lineno, "reason": "dynamic-import-review"})
                for old, new in sorted(modules.items(), key=lambda item: -len(item[0])):
                    candidate = re.sub(r"(?m)^(\s*(?:from|import)\s+)" + re.escape(old) + r"(?=[\s.,]|$)",
                                       lambda match: match.group(1) + new, candidate)
                ast.parse(candidate)
                for old in modules:
                    if re.search(r"\b" + re.escape(old) + r"\b", candidate):
                        unresolved.append({"path": relative, "reference": old, "reason": "uncompiled-python-reference"})
            except SyntaxError:
                unresolved.append({"path": relative, "reason": "python-syntax-review"})
        elif path.suffix.lower() in {".js", ".cjs", ".mjs", ".ts", ".tsx"}:
            candidate, js_unresolved = _rewrite_js_imports(candidate, paths, relative=relative)
            unresolved.extend(js_unresolved)
        elif path.suffix.lower() in {".json", ".jsonl", ".yaml", ".yml", ".toml"}:
            candidate, structured_unresolved = _rewrite_structured_references(candidate, paths, relative=relative)
            unresolved.extend(structured_unresolved)
        elif path.suffix.lower() in {".md", ".html"}:
            candidate, md_unresolved = _rewrite_markdown_links(candidate, paths, relative=relative)
            unresolved.extend(md_unresolved)
        # Any literal that still names a remapped source after the format-specific
        # pass is an uncompiled/prefix reference requiring review. This is the
        # safety net that keeps an unhandled form from silently passing.
        for old, new in paths.items():
            if old in candidate or old.replace("/", "\\") in candidate:
                unresolved.append({"path": relative, "reference": old, "reason": "nonliteral-or-prefix-reference"})
        if candidate != text:
            image = candidate.encode("utf-8")
            if len(image) > MAX_FILE_BYTES: raise ValueError("compiled candidate exceeds byte budget")
            changes.append({"path": relative, "target_path": paths.get(relative, relative),
                            "before_sha256": before, "after_sha256": hashlib.sha256(image).hexdigest(),
                            "content": candidate})
    source_by_path = {row["path"]: row for row in observed}
    for row in mappings:
        if source_by_path.get(row["source"], {}).get("sha256") != row["source_sha256"]:
            raise ValueError("remap source image changed before compilation")
    body = {"schema_version": "px.semantic-remap-compilation/1.0", "proposal_sha256": proposal["proposal_sha256"],
            "source_manifest": observed, "source_manifest_sha256": _hash(observed),
            "changes": changes, "unresolved": unresolved, "mechanically_ready": not unresolved,
            "reference_classes": _summarize_reference_classes(unresolved, changes),
            "authority_granted": False}
    return {**body, "compilation_sha256": _hash(body)}


def _summarize_reference_classes(unresolved, changes):
    """Classify every observed reference into the four factual classes.

    This is accounting, not acceptance: it makes the mechanically-proven set and
    each unresolved class explicit so an unresolved dynamic/ambiguous reference is
    never mistaken for a completed rewrite.
    """
    dynamic = sum(1 for row in unresolved if "dynamic" in str(row.get("reason", "")))
    ambiguous = sum(1 for row in unresolved if row.get("reason") == "ambiguous-reference")
    manual = len(unresolved) - dynamic - ambiguous
    return {
        "mechanically_proven": len(changes),
        "dynamically_unresolved": dynamic,
        "ambiguous": ambiguous,
        "manual_blocker": manual,
    }
