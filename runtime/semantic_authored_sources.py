"""Bounded extraction owners and reviewed dispositions for authored source formats.

The accountable source census must account for every authored file. Before this
module, any authored file without an admitted extractor was recorded only as
"No admitted extraction owner", which hid two very different situations:

1. real source-bearing formats with no extraction owner (CSS, HTML, SVG,
   TypeScript, SQL, dependency pins, ignore/packaging pattern lists, ownership
   policy, editor configuration, environment templates); and
2. authored files that are genuinely not PX semantic entities (legal
   attribution text and binary image assets).

This module owns the second distinction explicitly and implements bounded,
non-executing metadata extraction for the first group. It never executes,
imports or resolves observed content, never reads outside the acquired byte
image, and never drops a file from the census denominator.

Reviewed non-semantic families are recorded as ``intentionally_unclassified``
with a stable policy identifier and reason. That disposition is terminal for
file accounting but is NOT extraction completeness: a census with any such row
remains explicitly incomplete.
"""

from __future__ import annotations

import configparser
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Callable, Iterable

from runtime.semantic_taxonomy import SurfaceEntity, tokenize

SCHEMA = "px.authored-source-owners/1.0"
MAX_SOURCE_BYTES = 8 * 1024 * 1024
MAX_DECLARATIONS = 4096
MAX_NAME_CHARS = 512
MAX_TEXT_CHARS = 240

# One acquisition budget shared with the census owner. Callers pass the exact
# byte image they already read so this module never re-reads observed source.
_IDENTIFIER = r"[A-Za-z_$][\w$]*"


class AuthoredSourceError(ValueError):
    """Base class for authored-source extraction failures."""


class AuthoredSourceParseError(AuthoredSourceError):
    """The acquired image is not the complete structure it claims to be."""


class AuthoredSourceBudgetError(AuthoredSourceError):
    """A complete file exceeds its declared extraction budget."""


class AuthoredSourceStructureError(AuthoredSourceError):
    """The parsed structure carries no admitted declaration."""


@dataclass(frozen=True)
class FormatOwner:
    """One reviewed authored-format extraction owner."""

    format_id: str
    suffixes: tuple[str, ...]
    names: tuple[str, ...]
    kind: str
    surface: str
    extract: Callable[[str, str], list[SurfaceEntity]]


@dataclass(frozen=True)
class ReviewedNonEntity:
    """One explicitly reviewed family that is authored but not a PX entity.

    These files stay in the census denominator with a real hash. The policy
    identifier and reason are part of the census record so the classification is
    reviewable and attributable, never a silent filter.
    """

    policy_id: str
    reason: str
    suffixes: tuple[str, ...] = ()
    names: tuple[str, ...] = ()
    prefixes: tuple[str, ...] = ()


# --------------------------------------------------------------------------
# Reviewed non-entity families. Legal text stays HUMAN_REVIEW: this policy
# classifies the file as non-semantic metadata only and asserts nothing about
# licence meaning, obligation or compliance.
# --------------------------------------------------------------------------

REVIEWED_NON_ENTITIES: tuple[ReviewedNonEntity, ...] = (
    ReviewedNonEntity(
        policy_id="px.reviewed/legal-attribution-text",
        reason=(
            "Legal attribution text is owner-reserved legal content, not a PX "
            "semantic entity; classification asserts no licence interpretation"
        ),
        names=("LICENSE", "LICENCE", "COPYING", "NOTICE", "AUTHORS"),
        prefixes=("LICENSES/", "licenses/"),
    ),
    ReviewedNonEntity(
        policy_id="px.reviewed/binary-image-asset",
        reason=(
            "Binary raster image asset carries no extractable text declaration; "
            "it remains hashed and accounted, never silently excluded"
        ),
        suffixes=(".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".bmp"),
    ),
)

# Owner names that appear inside CODEOWNERS are observed verbatim as text.
# They are attribution metadata, not an authorization decision.
_CODEOWNERS_OWNER = re.compile(r"@[A-Za-z0-9][\w.-]*(?:/[\w.-]+)*")
_IGNORE_PATTERN = re.compile(r"^[^\s#].*$")
_ENV_KEY = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=")
_REQUIREMENT = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)\s*(?P<extras>\[[^\]]*\])?\s*==\s*(?P<version>[^\s;#]+)"
)
_CSS_CUSTOM_PROPERTY = re.compile(r"^\s*(--[A-Za-z0-9_-]+)\s*:")
_CSS_SELECTOR = re.compile(r"(?m)^\s*(@[A-Za-z-]+[^{]*|[^{}@][^{}]*?)\s*\{")
_SQL_DECLARATION = re.compile(
    r"(?im)^\s*create\s+(?:or\s+replace\s+)?(?:unique\s+)?"
    r"(table|function|index|view|policy|trigger|schema|extension|type|sequence)\s+"
    r"(?:if\s+not\s+exists\s+)?(?P<name>[A-Za-z_][\w.$-]*)"
)
_HTML_ELEMENT = re.compile(r"(?i)<\s*(?P<tag>[a-z][a-z0-9-]*)\b(?P<attributes>[^>]*)>")
_HTML_ID = re.compile(r"(?i)\bid\s*=\s*[\"']([^\"']+)[\"']")
_HTML_REFERENCE = re.compile(
    r"(?i)<(?:script[^>]*\ssrc|link[^>]*\shref|img[^>]*\ssrc)\s*=\s*[\"']([^\"']+)[\"']"
)
_SVG_ID = re.compile(r"(?i)\bid\s*=\s*[\"']([^\"']+)[\"']")
_TYPESCRIPT_DECLARATION = re.compile(
    r"(?m)^\s*(?:export\s+)?(?:default\s+)?(?:declare\s+)?"
    r"(?:async\s+)?(?P<kind>function|class|interface|type|enum|const|let|var)\s+"
    r"(?P<name>" + _IDENTIFIER + r")"
)
_MARKDOWN_RULE_FRONTMATTER = re.compile(r"\A---\r?\n(?P<frontmatter>.*?)\r?\n---\r?\n", re.S)


def _bounded_name(value: str) -> str:
    name = value.strip()
    if len(name) > MAX_NAME_CHARS:
        raise AuthoredSourceBudgetError("Declaration name exceeds the bounded name budget")
    return name


def _lines(text: str, *, budget: int = MAX_DECLARATIONS) -> list[tuple[int, str]]:
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    if len(lines) > budget:
        raise AuthoredSourceBudgetError("Declaration count exceeds complete-file extraction budget")
    return list(enumerate(lines, 1))


def _decode(raw: bytes) -> str:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise AuthoredSourceParseError("Source is not strict UTF-8") from exc
    if len(raw) > MAX_SOURCE_BYTES:
        raise AuthoredSourceBudgetError("Source exceeds the shared acquisition budget")
    if text.startswith("\ufeff"):
        raise AuthoredSourceParseError("A decoded BOM is not permitted in observed source")
    return text


def _entity(surface: str, kind: str, relative: str, suffix_key: str, name: str,
            *, line: int = 0, doc: str = "") -> SurfaceEntity:
    return SurfaceEntity(
        key=f"{surface}:{kind}:{relative}:{suffix_key}",
        surface=surface, kind=kind, name=name, source_path=relative,
        doc=doc[:MAX_TEXT_CHARS], tokens=tokenize(name) + tokenize(pathlib_name(relative)),
        line=line,
    )


def pathlib_name(relative: str) -> str:
    return relative.rsplit("/", 1)[-1]


# --------------------------------------------------------------------------
# Extraction owners
# --------------------------------------------------------------------------


def extract_css(text: str, relative: str) -> list[SurfaceEntity]:
    """Propose stylesheet layers, selectors and custom properties.

    CSS carries real presentation identity: a layer or token set is an owned
    declaration that downstream theming and the extension UI depend on.
    """
    rows = [_entity("source", "stylesheet", relative, "stylesheet",
                    pathlib_name(relative), doc=f"stylesheet {_layers(text)}")]
    for line_number, line in _lines(text):
        if not line.strip():
            continue
        layer = re.match(r"\s*@layer\s+([A-Za-z0-9_.\-]+)", line)
        if layer:
            rows.append(_entity("source", "layer", relative, f"layer:{line_number}",
                                _bounded_name(layer.group(1)), line=line_number,
                                doc="CSS cascade layer declaration"))
            continue
        token_match = _CSS_CUSTOM_PROPERTY.match(line)
        if token_match:
            rows.append(_entity("source", "design_token", relative,
                                f"token:{line_number}", _bounded_name(token_match.group(1)),
                                line=line_number, doc="CSS custom property declaration"))
            continue
        if line.lstrip().startswith(("/*", "*", "//")):
            continue
        selector = _CSS_SELECTOR.match(line)
        if selector:
            candidate = " ".join(selector.group(1).split())[:MAX_NAME_CHARS]
            if candidate:
                rows.append(_entity("source", "selector", relative, f"selector:{line_number}",
                                    candidate, line=line_number, doc="CSS rule selector"))
        if len(rows) > MAX_DECLARATIONS:
            raise AuthoredSourceBudgetError("Stylesheet declaration count exceeds budget")
    return rows


def _layers(text: str) -> str:
    names = re.findall(r"@layer\s+([A-Za-z0-9_.\-]+)", text)
    return ", ".join(sorted(set(names))[:16])


def extract_html(text: str, relative: str) -> list[SurfaceEntity]:
    """Propose document identity, element ids and local resource references."""
    title = re.search(r"(?is)<title[^>]*>(.*?)</title>", text)
    name = _bounded_name(" ".join(title.group(1).split())) if title else pathlib_name(relative)
    rows = [_entity("source", "document", relative, "document", name,
                    doc="HTML document; observed metadata only, never executed")]
    seen_ids: set[str] = set()
    for line_number, line in _lines(text):
        for identifier in _HTML_ID.findall(line):
            value = _bounded_name(identifier)
            if value in seen_ids:
                raise AuthoredSourceParseError(f"Duplicate element id {value!r} at line {line_number}")
            seen_ids.add(value)
            rows.append(_entity("source", "element", relative, f"id:{line_number}:{value}",
                                value, line=line_number, doc="Addressable HTML element id"))
        for reference in _HTML_REFERENCE.findall(line):
            rows.append(_entity("source", "reference", relative, f"ref:{line_number}:{reference}",
                                _bounded_name(reference), line=line_number,
                                doc="Local markup resource reference; not a fetched authority"))
        if len(rows) > MAX_DECLARATIONS:
            raise AuthoredSourceBudgetError("Markup declaration count exceeds budget")
    if len(rows) == 1:
        tags = sorted({match.group("tag").lower() for match in _HTML_ELEMENT.finditer(text)})
        if not tags:
            raise AuthoredSourceStructureError("HTML image declares no element or reference")
    return rows


def extract_svg(text: str, relative: str) -> list[SurfaceEntity]:
    """Propose SVG root identity and named graphical elements.

    The image is parsed as text; no renderer, script or external reference is
    resolved. A document type declaration is refused because XML entity
    resolution is not an admitted observation.
    """
    if re.search(r"(?i)<!doctype", text):
        raise AuthoredSourceParseError("SVG document type declarations are not admitted")
    if "<svg" not in text.lower():
        raise AuthoredSourceStructureError("SVG image declares no root element")
    rows = [_entity("source", "image", relative, "image", pathlib_name(relative),
                    doc="SVG vector image; text-level metadata only")]
    for line_number, line in _lines(text):
        for identifier in _SVG_ID.findall(line):
            rows.append(_entity("source", "element", relative, f"id:{line_number}:{identifier}",
                                _bounded_name(identifier), line=line_number,
                                doc="Addressable SVG element id"))
        if len(rows) > MAX_DECLARATIONS:
            raise AuthoredSourceBudgetError("Vector declaration count exceeds budget")
    return rows


def extract_typescript(text: str, relative: str) -> list[SurfaceEntity]:
    """Propose declared TypeScript names.

    TypeScript is observed as declared source text. It is never compiled,
    transpiled, imported or executed, and no type is resolved.
    """
    rows = [_entity("source", "module", relative, "module", pathlib_name(relative),
                    doc="TypeScript module declaration; observed metadata only")]
    for line_number, line in _lines(text):
        match = _TYPESCRIPT_DECLARATION.match(line)
        if not match:
            continue
        rows.append(_entity("source", match.group("kind"), relative,
                            f"{match.group('kind')}:{line_number}",
                            _bounded_name(match.group("name")), line=line_number,
                            doc=f"declared {match.group('kind')}"))
        if len(rows) > MAX_DECLARATIONS:
            raise AuthoredSourceBudgetError("TypeScript declaration count exceeds budget")
    return rows


def extract_sql(text: str, relative: str) -> list[SurfaceEntity]:
    """Propose declared SQL objects without connecting to or mutating a database."""
    rows = [_entity("source", "script", relative, "script", pathlib_name(relative),
                    doc="SQL script; declared object metadata only, never executed")]
    for line_number, line in _lines(text):
        match = _SQL_DECLARATION.match(line)
        if not match:
            continue
        rows.append(_entity("source", match.group(1), relative,
                            f"{match.group(1)}:{line_number}:{match.group('name')}",
                            _bounded_name(match.group("name")), line=line_number,
                            doc=f"declared SQL {match.group(1)}"))
        if len(rows) > MAX_DECLARATIONS:
            raise AuthoredSourceBudgetError("SQL declaration count exceeds budget")
    if len(rows) == 1:
        raise AuthoredSourceStructureError("SQL script declares no object")
    return rows


def extract_requirements(text: str, relative: str) -> list[SurfaceEntity]:
    """Propose exact release dependency pins.

    Only fully pinned ``name[extras]==version`` requirements with hashes or
    markers become entities. Anything else is refused rather than guessed.
    """
    rows = [_entity("source", "manifest", relative, "manifest", pathlib_name(relative),
                    doc="Pinned release dependency declaration")]
    names: set[str] = set()
    joined: list[str] = []
    for line_number, line in _lines(text):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.endswith("\\"):
            joined.append(stripped[:-1].strip())
            continue
        candidate = " ".join([*joined, stripped]).strip()
        joined = []
        if candidate.startswith(("-r", "--requirement", "--index-url", "-c", "--constraint")):
            continue
        match = _REQUIREMENT.match(candidate)
        if not match:
            raise AuthoredSourceParseError(
                f"Requirement line {line_number} is not an exact pinned requirement"
            )
        name = _bounded_name(match.group("name").lower())
        if name in names:
            raise AuthoredSourceParseError(f"Duplicate requirement {name!r} at line {line_number}")
        names.add(name)
        rows.append(_entity("source", "dependency", relative, f"requirement:{name}",
                            name, line=line_number,
                            doc=f"pinned release dependency {match.group('version')}"))
    if len(rows) > MAX_DECLARATIONS:
        raise AuthoredSourceBudgetError("Requirement count exceeds budget")
    if len(rows) == 1:
        raise AuthoredSourceStructureError("Requirements file declares no pinned dependency")
    return rows


def _pattern_rows(text: str, relative: str) -> list[SurfaceEntity]:
    rows = [_entity("source", "policy", relative, "policy", pathlib_name(relative),
                    doc="Path pattern policy list; no file is ignored or included by this census")]
    for line_number, line in _lines(text):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not _IGNORE_PATTERN.match(stripped):
            continue
        rows.append(_entity("source", "pattern", relative, f"pattern:{line_number}",
                            _bounded_name(stripped), line=line_number,
                            doc="Declared path pattern"))
        if len(rows) > MAX_DECLARATIONS:
            raise AuthoredSourceBudgetError("Pattern count exceeds budget")
    if len(rows) == 1:
        raise AuthoredSourceStructureError("Pattern list declares no pattern")
    return rows


def extract_codeowners(text: str, relative: str) -> list[SurfaceEntity]:
    """Propose ownership policy paths and their declared review owners.

    Owners are recorded verbatim as observed attribution metadata. This census
    neither grants nor revokes any review authority.
    """
    rows = [_entity("source", "policy", relative, "policy", pathlib_name(relative),
                    doc="Ownership policy; observed attribution metadata only")]
    for line_number, line in _lines(text):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split()
        owners = _CODEOWNERS_OWNER.findall(stripped)
        if not owners:
            raise AuthoredSourceParseError(f"CODEOWNERS line {line_number} declares no owner")
        path = _bounded_name(parts[0] if not parts[0].startswith("@") else stripped)
        for owner in owners[:16]:
            rows.append(_entity("source", "ownership", relative,
                                f"ownership:{line_number}:{owner}", _bounded_name(path),
                                line=line_number,
                                doc=f"declared review owner {_bounded_name(owner)}"))
        if len(rows) > MAX_DECLARATIONS:
            raise AuthoredSourceBudgetError("Ownership declaration count exceeds budget")
    if len(rows) == 1:
        raise AuthoredSourceStructureError("CODEOWNERS declares no ownership rule")
    return rows


def extract_ini(text: str, relative: str) -> list[SurfaceEntity]:
    """Propose declared sections and keys of an INI-style configuration."""
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    parser.optionxform = str  # type: ignore[method-assign]
    try:
        parser.read_string(text)
    except configparser.Error as exc:
        raise AuthoredSourceParseError(f"INI configuration is not well formed: {exc}") from exc
    rows = [_entity("source", "configuration", relative, "configuration", pathlib_name(relative),
                    doc="INI-style configuration declaration")]
    for section in parser.sections():
        rows.append(_entity("source", "section", relative, f"section:{section}",
                            _bounded_name(section), doc="declared configuration section"))
        for key in parser[section]:
            rows.append(_entity("source", "setting", relative, f"setting:{section}:{key}",
                                _bounded_name(key), doc=f"declared setting in [{section}]"))
        if len(rows) > MAX_DECLARATIONS:
            raise AuthoredSourceBudgetError("Configuration declaration count exceeds budget")
    if len(rows) == 1:
        raise AuthoredSourceStructureError("Configuration declares no section")
    return rows


def extract_json_document(text: str, relative: str) -> list[SurfaceEntity]:
    """Propose a JSON document identity and its declared member names."""
    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AuthoredSourceParseError(f"JSON document is not well formed: {exc}") from exc
    if not isinstance(document, dict):
        raise AuthoredSourceStructureError("JSON root has no admitted declaration")
    rows = [_entity("source", "document", relative, "document", pathlib_name(relative),
                    doc="JSON configuration document")]
    for key in sorted(document)[:MAX_DECLARATIONS]:
        rows.append(_entity("source", "member", relative, f"member:{key}",
                            _bounded_name(key), doc="declared document member"))
    return rows


def extract_environment_template(text: str, relative: str) -> list[SurfaceEntity]:
    """Propose environment variable NAMES declared by a template.

    Values are never proposed. A template may hold placeholders today; copying
    a value into a semantic record would turn example content into asserted
    configuration, and a future real secret into a published artifact.
    """
    rows = [_entity("source", "template", relative, "template", pathlib_name(relative),
                    doc="Environment template; variable names only, never values")]
    names: set[str] = set()
    for line_number, line in _lines(text):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _ENV_KEY.match(stripped)
        if not match:
            raise AuthoredSourceParseError(
                f"Environment template line {line_number} declares no variable name"
            )
        name = _bounded_name(match.group(1))
        if name in names:
            raise AuthoredSourceParseError(f"Duplicate environment variable {name!r}")
        names.add(name)
        rows.append(_entity("source", "variable", relative, f"variable:{name}", name,
                            line=line_number, doc="declared environment variable name"))
        if len(rows) > MAX_DECLARATIONS:
            raise AuthoredSourceBudgetError("Environment declaration count exceeds budget")
    if len(rows) == 1:
        raise AuthoredSourceStructureError("Environment template declares no variable")
    return rows


_CHECKSUM_LINE = re.compile(r"^(?P<digest>[a-f0-9]{64})\s+\*?(?P<member>\S.*)$")


def extract_checksum_manifest(text: str, relative: str) -> list[SurfaceEntity]:
    """Propose the digests a checksum manifest declares for its members.

    The declared digest is observed as recorded metadata only. This census
    never resolves, fetches or verifies the named member: verification is a
    packaging concern and remains under the owner's build hold.
    """
    rows = [_entity("source", "manifest", relative, "manifest", pathlib_name(relative),
                    doc="Checksum manifest; declared digests only, never verified here")]
    seen: set[str] = set()
    for line_number, line in _lines(text):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _CHECKSUM_LINE.match(stripped)
        if not match:
            raise AuthoredSourceParseError(
                f"Checksum manifest line {line_number} is not a digest member record"
            )
        member = _bounded_name(match.group("member"))
        if member in seen:
            raise AuthoredSourceParseError(f"Duplicate checksum member {member!r}")
        seen.add(member)
        rows.append(_entity("source", "checksum", relative, f"member:{member}", member,
                            line=line_number,
                            doc=f"declared sha256 {match.group('digest')}"))
        if len(rows) > MAX_DECLARATIONS:
            raise AuthoredSourceBudgetError("Checksum member count exceeds budget")
    if len(rows) == 1:
        raise AuthoredSourceStructureError("Checksum manifest declares no member")
    return rows


def extract_editor_rule(text: str, relative: str) -> list[SurfaceEntity]:
    """Propose an editor rule document's declared identity and body."""
    match = _MARKDOWN_RULE_FRONTMATTER.match(text)
    frontmatter: dict[str, str] = {}
    if match:
        body = text[match.end():]
        for line in match.group("frontmatter").splitlines():
            if ":" in line and not line.strip().startswith("#"):
                key, _, value = line.partition(":")
                if key.strip() and value.strip():
                    frontmatter[key.strip()] = value.strip()
    else:
        body = text
    # Declared front matter is the rule's own identity; a heading is only a
    # fallback for a document that declares none.
    name = frontmatter.get("description", "").strip() or pathlib_name(relative)
    if not name:
        raise AuthoredSourceStructureError("Rule document declares no identity")
    rows = [_entity("source", "rule", relative, "rule", _bounded_name(name),
                    doc=" ".join(body.split())[:MAX_TEXT_CHARS])]
    for key in sorted(frontmatter):
        rows.append(_entity("source", "rule_setting", relative, f"setting:{key}",
                            _bounded_name(key), doc="declared rule front matter"))
    if not rows:
        raise AuthoredSourceStructureError("Rule document declares no identity")
    return rows


FORMAT_OWNERS: tuple[FormatOwner, ...] = (
    FormatOwner("px.format/pattern-list", (".gitignore", ".gitattributes", ".vscodeignore",
                                           ".dockerignore"), ("MANIFEST.in",),
                "policy", "source", _pattern_rows),
    FormatOwner("px.format/requirements", (), ("requirements-release.txt",),
                "manifest", "source", extract_requirements),
    FormatOwner("px.format/codeowners", (), ("CODEOWNERS",), "policy", "source",
                extract_codeowners),
    FormatOwner("px.format/css", (".css",), (), "stylesheet", "source", extract_css),
    FormatOwner("px.format/html", (".html", ".htm"), (), "document", "source", extract_html),
    FormatOwner("px.format/svg", (".svg",), (), "image", "source", extract_svg),
    FormatOwner("px.format/typescript", (".ts", ".mts", ".cts"), (), "module", "source",
                extract_typescript),
    FormatOwner("px.format/sql", (".sql",), (), "script", "source", extract_sql),
    FormatOwner("px.format/ini", (".coveragerc", ".editorconfig", ".flake8"),
                (), "configuration", "source", extract_ini),
    FormatOwner("px.format/editor-config", (".code-workspace",), (), "configuration", "source",
                extract_json_document),
    FormatOwner("px.format/environment-template", (), (".env.example",), "template", "source",
                extract_environment_template),
    FormatOwner("px.format/checksum-manifest", (), ("SHA256SUMS.txt", "SHA256SUMS"),
                "manifest", "source", extract_checksum_manifest),
    FormatOwner("px.format/editor-rule", (".mdc",), (), "rule", "source", extract_editor_rule),
)

_OWNER_BY_SUFFIX: dict[str, FormatOwner] = {}
_OWNER_BY_NAME: dict[str, FormatOwner] = {}
for _owner in FORMAT_OWNERS:
    for _suffix in _owner.suffixes:
        _OWNER_BY_SUFFIX.setdefault(_suffix, _owner)
    for _name in _owner.names:
        _OWNER_BY_NAME.setdefault(_name, _owner)


def format_owner(relative: str) -> FormatOwner | None:
    """Return the admitted extraction owner for one authored relative path.

    An exact filename owner wins over a suffix owner. An unowned path returns
    None so the caller keeps its honest unresolved disposition.
    """
    name = pathlib_name(relative)
    if name in _OWNER_BY_NAME:
        return _OWNER_BY_NAME[name]
    suffix = _name_suffix(relative)
    return _OWNER_BY_SUFFIX.get(suffix) if suffix else None


def _name_suffix(relative: str) -> str:
    name = pathlib_name(relative)
    if name.startswith("."):
        # Dotfiles such as .gitignore carry their whole name as the marker.
        return name.lower()
    return "." + name.rsplit(".", 1)[1].lower() if "." in name else ""


def reviewed_non_entity(relative: str) -> ReviewedNonEntity | None:
    """Return the reviewed non-entity policy for one authored path, if any.

    Legal attribution is matched by exact declared name and by the same name
    carrying a text suffix (``LICENSE.txt``, ``NOTICE.md``), because the
    vendored attribution trees in this repository use that form. Matching by
    suffix alone would misclassify unrelated text, so no bare suffix is used.
    """
    name = pathlib_name(relative)
    for policy in REVIEWED_NON_ENTITIES:
        if name in policy.names:
            return policy
        stem, dot, extension = name.rpartition(".")
        if dot and f".{extension.lower()}" in {".txt", ".md", ".markdown", ".rst"}:
            if stem.upper() in {declared.upper() for declared in policy.names}:
                return policy
    for policy in REVIEWED_NON_ENTITIES:
        if policy.suffixes and _name_suffix(relative) in policy.suffixes:
            return policy
        if any(relative.startswith(prefix) for prefix in policy.prefixes):
            return policy
    return None


def extract_owned(relative: str, raw: bytes) -> tuple[FormatOwner, list[SurfaceEntity]]:
    """Extract one owned format from an already acquired byte image."""
    owner = format_owner(relative)
    if owner is None:
        raise AuthoredSourceStructureError("No admitted extraction owner for this format")
    return owner, owner.extract(_decode(raw), relative)


def policy_snapshot() -> dict:
    """Exact reviewed policy content, bound into the source binding."""
    return {
        "schema_version": SCHEMA,
        "format_owners": [
            {"format_id": owner.format_id, "suffixes": list(owner.suffixes),
             "names": list(owner.names), "kind": owner.kind, "surface": owner.surface}
            for owner in FORMAT_OWNERS
        ],
        "reviewed_non_entities": [
            {"policy_id": policy.policy_id, "reason": policy.reason,
             "suffixes": list(policy.suffixes), "names": list(policy.names)}
            for policy in REVIEWED_NON_ENTITIES
        ],
    }


def policy_sha256() -> str:
    canonical = json.dumps(policy_snapshot(), sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def declared_policy_paths() -> Iterable[str]:
    for owner in FORMAT_OWNERS:
        yield from owner.suffixes
        yield from owner.names
    for policy in REVIEWED_NON_ENTITIES:
        yield from policy.suffixes
        yield from policy.names