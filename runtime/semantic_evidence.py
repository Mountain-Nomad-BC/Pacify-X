"""Expanded, multi-channel evidence extraction for the SEM-003 ontology census.

Scope is the whole governed semantic corpus, not just Python and JavaScript
symbols. The first census answered "what is the ontology of .py and .js files";
this one asks "what is the ontology of PX".

Surfaces included
-----------------
runtime modules, extension sources, contracts and schemas, tests, registries and
registers, policies and governance, skills, workflows, orchestrations, agents,
manifests, providers, memory and learning structures, and reusable evidence
definitions. Generated, vendored and cache material is EXCLUDED unless it is
itself a canonical entity, and the exclusion is explicit rather than incidental.

Evidence channels
-----------------
Lexical similarity alone is weak. Each observation therefore carries what is
actually available per surface:

* name tokens, docstring or leading comment, path, AST type
* imports for Python modules
* inheritance and decorator facts
* references FROM tests, which is a strong ownership signal
* registry or manifest membership
* contract/schema declarations

Uncertainty is preserved deliberately. An entity that no channel resolves stays
UNRESOLVED, AMBIGUOUS or NOVEL_TERM. A low RESOLVED percentage is evidence about
vocabulary maturity, not a score to optimize.
"""

from __future__ import annotations

import ast
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

CENSUS_SCHEMA = "px.semantic-census/2.0"

RESOLVED = "RESOLVED"
UNRESOLVED = "UNRESOLVED"
AMBIGUOUS = "AMBIGUOUS"
NOVEL_TERM = "NOVEL_TERM"
OUTCOMES = (RESOLVED, UNRESOLVED, AMBIGUOUS, NOVEL_TERM)

_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")

# Surfaces that carry PX entities. Each entry maps a path prefix to a surface
# name; anything not matched by this table and not in a known ignore prefix is
# reported as uncovered rather than silently ignored.
SEMANTIC_SURFACES: tuple[tuple[str, str], ...] = (
    ("runtime", "runtime"),
    ("extension/src", "extension"),
    ("extension/scripts", "extension"),
    ("extension/media/dashboard", "operator_surface"),
    ("extension/server", "server"),
    ("contracts", "contract"),
    ("schemas", "contract"),
    ("policies", "policy"),
    ("governance", "policy"),
    ("skills", "skill"),
    (".px/skills", "skill"),
    ("workflows", "workflow"),
    ("orchestrations", "orchestration"),
    ("agents", "agent"),
    ("providers", "provider"),
    ("registry", "registry"),
    ("registers", "registry"),
    ("memory", "memory"),
    ("learning", "learning"),
    ("evidence", "evidence"),
    ("scripts", "tooling"),
)

# Explicitly excluded from the ontology. Generated, vendored or cache material is
# not a canonical entity unless separately declared as one.
IGNORE_PREFIXES = (
    "node_modules", "__pycache__", ".git", "dist", "build",
    ".ruff_cache", ".pytest_cache", "python", "preserved-extension-installations",
    ".venv", "vendor",
)
# Generated projections are excluded by the declared source boundary.
IGNORE_EXACT = (
    "pyproject.toml", "extension/node_modules", "docs/architecture/data",
    "docs/architecture/ATLAS_OFFLINE.html", "docs/architecture/graph_data.js",
)

_CODE_SUFFIXES = {".py", ".js", ".mjs", ".ts", ".cjs"}
_DOC_SUFFIXES = {".md", ".mdx"}
_DATA_SUFFIXES = {".json", ".jsonl", ".yaml", ".yml"}


@dataclass
class Observation:
    """One entity candidate with every evidence channel we can actually obtain."""

    key: str
    surface: str
    path: str
    symbol: str
    kind: str
    ast_type: str = ""
    doc: str = ""
    imports: tuple[str, ...] = ()
    base_names: tuple[str, ...] = ()
    decorators: tuple[str, ...] = ()
    referenced_by_tests: int = 0
    registry_members: int = 0
    channels: tuple[str, ...] = ()

    def feature_text(self) -> str:
        return " ".join(
            [
                self.path.replace("/", " ").replace("\\", " ").replace(".", " ").replace("_", " "),
                _CAMEL.sub(" ", self.symbol).replace("_", " "),
                self.doc[:240].replace("\n", " "),
                " ".join(self.base_names[:8]),
                " ".join(self.decorators[:6]),
            ]
        )

    def channel_weight(self) -> int:
        return len(self.channels)


def _tokens(text: str) -> list[str]:
    spaced = _CAMEL.sub(" ", text.replace("_", " ").replace("-", " "))
    return [t.lower() for t in re.findall(r"[a-z][a-z0-9]*", spaced) if len(t) > 1]


def _ignored(path: Path, root: Path) -> bool:
    relative = path.relative_to(root).as_posix()
    if any(part in IGNORE_PREFIXES for part in Path(relative).parts):
        return True
    for prefix in IGNORE_EXACT:
        if relative == prefix or relative.startswith(prefix.rstrip("/") + "/"):
            return True
    return False


def _surface_of(relative: str) -> tuple[str, str] | None:
    for prefix, surface in SEMANTIC_SURFACES:
        if relative == prefix or relative.startswith(prefix.rstrip("/") + "/"):
            return surface, prefix
    return None


# --- per-surface extraction -------------------------------------------------


def _observe_python(path: Path, root: Path, surface: str, test_refs: dict[str, int]) -> list[Observation]:
    relative = path.relative_to(root).as_posix()
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source)
    except (SyntaxError, ValueError, OSError):
        return []
    module_doc = ast.get_docstring(tree) or ""
    imports: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            imports.extend(a.name for a in node.names[:24])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    stem = path.stem
    channels = ["name", "path", "ast_type", "doc"]
    if imports:
        channels.append("imports")
    if test_refs.get(stem):
        channels.append("test_references")
    out = [
        Observation(
            key=f"py:module:{relative}",
            surface=surface, path=relative, symbol=stem, kind="module",
            ast_type="Module", doc=module_doc[:240],
            imports=tuple(imports[:24]),
            base_names=tuple(sorted({i.split(".")[-1] for i in imports})),
            referenced_by_tests=test_refs.get(stem, 0),
            channels=tuple(channels),
        )
    ]
    for node in tree.body:
        targets = [node]
        if isinstance(node, ast.ClassDef):
            targets = node.body
        for child in targets:
            if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            is_class = isinstance(child, ast.ClassDef)
            decorators = tuple(
                getattr(item, "id", None) or getattr(getattr(item, "attr", None), "__str__", lambda: "")()
                for item in getattr(child, "decorator_list", [])
            )
            bases = tuple(
                getattr(base, "id", "") for base in getattr(child, "bases", []) if getattr(base, "id", None)
            ) if is_class else ()
            channels = ["name", "path", "ast_type"]
            child_doc = ast.get_docstring(child) or ""
            if child_doc:
                channels.append("doc")
            if decorators:
                channels.append("decorators")
            if bases:
                channels.append("inheritance")
            out.append(
                Observation(
                    key=f"py:{'class' if is_class else 'function'}:{relative}:{child.lineno}:{child.name}",
                    surface=surface, path=relative, symbol=child.name,
                    kind="class" if is_class else "function",
                    ast_type=type(child).__name__,
                    doc=child_doc[:240],
                    base_names=bases,
                    decorators=tuple(d for d in decorators if d),
                    channels=tuple(channels),
                )
            )
    return out


_JS_FUNC = re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)", re.M)
_JS_CLASS = re.compile(r"^\s*(?:export\s+)?class\s+([A-Za-z_$][\w$]*)", re.M)
_JS_CONST = re.compile(r"^\s*(?:export\s+)?const\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\(", re.M)


def _observe_js(path: Path, root: Path, surface: str) -> list[Observation]:
    relative = path.relative_to(root).as_posix()
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    stem = path.stem
    out = [
        Observation(
            key=f"js:module:{relative}", surface=surface, path=relative,
            symbol=stem, kind="module", ast_type="Module",
            channels=("name", "path", "ast_type"),
        )
    ]
    for pattern, kind, ast_type in (
        (_JS_FUNC, "function", "FunctionDeclaration"),
        (_JS_CLASS, "class", "ClassDeclaration"),
        (_JS_CONST, "function", "VariableDeclaration"),
    ):
        for match in pattern.finditer(source):
            name = match.group(1)
            out.append(
                Observation(
                    key=f"js:{kind}:{relative}:{name}", surface=surface, path=relative,
                    symbol=name, kind=kind, ast_type=ast_type,
                    channels=("name", "path", "ast_type"),
                )
            )
    return out


def _observe_declared(path: Path, root: Path, surface: str, registry_refs: dict[str, int]) -> list[Observation]:
    """A schema, contract, policy, manifest or registry is itself an entity."""
    relative = path.relative_to(root).as_posix()
    doc = ""
    kind = "contract"
    if path.suffix in _DATA_SUFFIXES:
        kind = "manifest"
        try:
            payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
            doc = str(payload.get("title") or payload.get("description") or "")[:240]
        except (json.JSONDecodeError, OSError):
            doc = ""
    elif path.suffix in _DOC_SUFFIXES:
        kind = "skill" if surface == "skill" else "policy"
        try:
            doc = path.read_text(encoding="utf-8", errors="replace")[:240]
        except OSError:
            doc = ""
    stem = path.stem
    return [
        Observation(
            key=f"declared:{kind}:{relative}", surface=surface, path=relative,
            symbol=stem, kind=kind, ast_type="Declaration", doc=doc,
            registry_members=registry_refs.get(stem, 0),
            channels=tuple(
                ("name", "path", "ast_type") + (("doc",) if doc else ())
                + (("registry_reference",) if registry_refs.get(stem) else ())
            ),
        )
    ]


def collect(
    root: Path,
    *,
    max_per_surface: int = 2500,
    surfaces: Iterable[str] | None = None,
) -> tuple[list[Observation], dict[str, Any]]:
    """Walk the whole governed corpus and gather observations with evidence."""
    root = Path(root).resolve(strict=True)
    wanted = set(surfaces) if surfaces else None

    test_refs: Counter[str] = Counter()
    registry_refs: Counter[str] = Counter()
    for candidate in list(root.glob("tests/**/*.py")) + list(root.glob("tests/**/*.js")):
        try:
            text = candidate.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for token in set(re.findall(r"[A-Za-z_][A-Za-z0-9_]{3,}", text)):
            test_refs[token] += 1
    for candidate in list(root.glob("registry/*.json")) + list(root.glob("contracts/**/*.json")):
        try:
            text = candidate.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for token in set(re.findall(r"[A-Za-z_][A-Za-z0-9_\-]{3,}", text)):
            registry_refs[token] += 1

    observations: list[Observation] = []
    per_surface: Counter[str] = Counter()
    uncovered: Counter[str] = Counter()
    files_seen = 0

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if _ignored(path, root):
            continue
        relative = path.relative_to(root).as_posix()
        matched = _surface_of(relative)
        if matched is None:
            uncovered[relative.split("/")[0]] += 1
            continue
        surface = matched[0]
        if wanted and surface not in wanted:
            continue
        if per_surface[surface] >= max_per_surface:
            continue
        files_seen += 1
        if path.suffix == ".py":
            rows = _observe_python(path, root, surface, test_refs)
        elif path.suffix in _CODE_SUFFIXES:
            rows = _observe_js(path, root, surface)
        elif path.suffix in _DOC_SUFFIXES or path.suffix in _DATA_SUFFIXES:
            rows = _observe_declared(path, root, surface, registry_refs)
        else:
            continue
        for row in rows:
            if per_surface[surface] >= max_per_surface:
                break
            observations.append(row)
            per_surface[surface] += 1

    coverage = {
        "files_scanned": files_seen,
        "observations": len(observations),
        "per_surface": dict(sorted(per_surface.items())),
        "uncovered_top_level": dict(sorted(uncovered.items())[:25]),
        "excluded_prefixes": list(IGNORE_PREFIXES),
        "excluded_exact": list(IGNORE_EXACT),
        "evidence_channels": sorted({c for o in observations for c in o.channels}),
    }
    return observations, coverage