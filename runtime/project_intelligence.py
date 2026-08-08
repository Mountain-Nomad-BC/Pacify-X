"""Deterministic, local-first project intelligence mapping for PACIFY-X.

The mapper turns a bounded repository walk into a persistent, evidence-backed
project model. It intentionally stores structure and identifiers rather than
raw secret values. Existing maps are archived instead of deleted, and unchanged
file facts are reused when their content hash and adapter version match.
"""

from __future__ import annotations

from ast import AST
import ast
from collections import Counter, defaultdict
from datetime import datetime, timezone
import fnmatch
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tomllib
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlparse
import uuid

from .bounded_walk import FilesystemWalkError, WalkLimits, bounded_walk


SCHEMA_VERSION = "1.1"
MAPPER_VERSION = "0.3.0"
ADAPTER_VERSION = "2026-08-06.1"

DEFAULT_EXCLUDES = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "node_modules",
    "build",
    "dist",
    "__pycache__",
    ".engineering-bootstrap",
    "quarantine",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".idea",
}

SENSITIVE_FILE_NAMES = {
    ".env",
    ".git-credentials",
    ".netrc",
    ".npmrc",
    ".pypirc",
    "credentials.json",
    "service-account.json",
    "service_account.json",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "id_rsa",
}
SENSITIVE_FILE_SUFFIXES = {
    ".jks",
    ".key",
    ".keystore",
    ".p12",
    ".pfx",
    ".pem",
}

LANGUAGE_BY_SUFFIX = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".cs": "csharp",
    ".rb": "ruby",
    ".php": "php",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".swift": "swift",
    ".c": "c",
    ".h": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".sql": "sql",
    ".graphql": "graphql",
    ".gql": "graphql",
    ".proto": "protobuf",
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".scss": "scss",
    ".sass": "sass",
    ".md": "markdown",
    ".rst": "rst",
    ".json": "json",
    ".toml": "toml",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".xml": "xml",
    ".sh": "shell",
    ".ps1": "powershell",
}

TEXT_SUFFIXES = set(LANGUAGE_BY_SUFFIX) | {
    ".txt",
    ".cfg",
    ".conf",
    ".ini",
    ".env",
    ".properties",
    ".gradle",
    ".dockerfile",
    ".lock",
    ".csv",
    ".tsv",
}
TEXT_NAMES = {
    "dockerfile",
    "makefile",
    "jenkinsfile",
    "procfile",
    "codeowners",
    "requirements.txt",
    "go.mod",
    "go.sum",
    "cargo.toml",
    "cargo.lock",
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "pyproject.toml",
    "setup.cfg",
    "tox.ini",
    ".gitignore",
    ".dockerignore",
}

SOURCE_LANGUAGES = {
    "python",
    "javascript",
    "typescript",
    "go",
    "rust",
    "java",
    "csharp",
    "ruby",
    "php",
    "kotlin",
    "swift",
    "c",
    "cpp",
}

SENSITIVE_KEY = re.compile(
    r"(?i)(password|passwd|secret|token|api[_-]?key|private[_-]?key|credential|connection[_-]?string|database[_-]?url|dsn|cookie|session[_-]?key)"
)
URL_RE = re.compile(r"\bhttps?://[^\s\"'<>]+", re.IGNORECASE)
IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_./:-]{1,100}")
TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_./:-]{1,80}")

ROUTE_METHODS = {
    "get",
    "post",
    "put",
    "patch",
    "delete",
    "options",
    "head",
    "websocket",
}

INTEGRATION_HINTS = {
    "postgres": "database",
    "psycopg": "database",
    "asyncpg": "database",
    "sqlalchemy": "database",
    "mysql": "database",
    "pymysql": "database",
    "mongodb": "database",
    "pymongo": "database",
    "redis": "cache_or_queue",
    "celery": "queue_or_worker",
    "rabbitmq": "queue",
    "kafka": "event_stream",
    "boto3": "aws",
    "azure": "azure",
    "google.cloud": "gcp",
    "supabase": "supabase",
    "requests": "http_client",
    "httpx": "http_client",
    "aiohttp": "http_client",
    "axios": "http_client",
    "fastapi": "web_framework",
    "flask": "web_framework",
    "django": "web_framework",
    "express": "web_framework",
    "next": "web_framework",
    "react": "ui_framework",
    "vue": "ui_framework",
    "n8n": "workflow_automation",
    "openai": "ai_provider",
    "anthropic": "ai_provider",
    "ollama": "local_model_runtime",
    "prometheus": "observability",
    "opentelemetry": "observability",
}

QUERY_ALIASES = {
    "api": ["endpoint", "route", "handler", "controller"],
    "endpoint": ["api", "route", "handler"],
    "db": ["database", "sql", "storage", "repository"],
    "database": ["db", "sql", "storage", "repository"],
    "auth": ["authentication", "authorization", "login", "token", "security"],
    "config": ["configuration", "settings", "environment", "env"],
    "env": ["environment", "configuration", "settings"],
    "test": ["tests", "spec", "coverage", "fixture"],
    "worker": ["job", "queue", "task", "scheduler"],
    "queue": ["worker", "job", "event", "message"],
    "ui": ["frontend", "component", "page", "view"],
    "service": ["runtime", "container", "process", "daemon"],
    "schema": ["contract", "model", "type", "interface"],
    "owner": ["ownership", "codeowners", "maintainer"],
}

REQUIRED_MAP_FILES = (
    "project-manifest.json",
    "file-inventory.jsonl",
    "file-facts.jsonl",
    "symbol-index.jsonl",
    "dependency-graph.json",
    "call-graph.json",
    "architecture-graph.json",
    "runtime-topology.json",
    "data-flow-map.json",
    "integration-map.json",
    "configuration-map.json",
    "ownership-map.json",
    "contract-map.json",
    "test-coverage-map.json",
    "traceability-map.json",
    "risk-and-gap-map.json",
    "retrieval-index.json",
    "map-summary.md",
    "map-receipt.json",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    ).encode("utf-8")


def _stable_hash(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True, default=str)
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _write_jsonl(path: Path, records: Iterable[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(
                json.dumps(
                    record,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    default=str,
                )
            )
            stream.write("\n")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not path.is_file():
        return records
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as error:
                raise ValueError(
                    f"invalid JSONL at {path}:{number}: {error}"
                ) from error
    return records


def _language(path: Path) -> str:
    name = path.name.casefold()
    if name == "dockerfile" or name.endswith(".dockerfile"):
        return "dockerfile"
    return LANGUAGE_BY_SUFFIX.get(path.suffix.casefold(), "unknown")


def _exclusion_category(relative: str) -> str | None:
    """Classify a path before inventory, hashing, parsing, or indexing."""
    path = Path(relative)
    parts = tuple(part.casefold() for part in path.parts)
    if any(part in DEFAULT_EXCLUDES for part in parts):
        return "default"
    name = path.name.casefold()
    if name in SENSITIVE_FILE_NAMES or name.startswith(".env."):
        return "sensitive_file"
    if path.suffix.casefold() in SENSITIVE_FILE_SUFFIXES:
        return "sensitive_key_material"
    if any(part in {".secrets", ".credentials"} for part in parts):
        return "sensitive_directory"
    return None


def _excluded_source(relative: str) -> bool:
    return _exclusion_category(relative) is not None


def _role(relative: str, language: str) -> str:
    low = relative.casefold()
    name = Path(relative).name.casefold()
    if (
        any(
            part in {"test", "tests", "spec", "specs", "__tests__"}
            for part in Path(low).parts
        )
        or name.startswith("test_")
        or name.endswith(("_test.py", ".test.ts", ".spec.ts", ".test.js", ".spec.js"))
    ):
        return "test"
    if low.startswith((".github/workflows/", ".gitlab/")) or name in {
        "jenkinsfile",
        "azure-pipelines.yml",
        ".gitlab-ci.yml",
    }:
        return "ci"
    if "migration" in Path(low).parts or "migrations" in Path(low).parts:
        return "migration"
    if name in {
        "dockerfile",
        "docker-compose.yml",
        "docker-compose.yaml",
        "compose.yml",
        "compose.yaml",
        "makefile",
    }:
        return "build_or_runtime"
    if name in {
        "package.json",
        "pyproject.toml",
        "go.mod",
        "cargo.toml",
        "requirements.txt",
        "setup.cfg",
        "tox.ini",
    } or Path(relative).suffix.casefold() in {
        ".toml",
        ".yaml",
        ".yml",
        ".ini",
        ".cfg",
        ".env",
    }:
        return "configuration"
    if Path(relative).suffix.casefold() in {
        ".json",
        ".yaml",
        ".yml",
        ".proto",
        ".graphql",
        ".gql",
    } and any(term in low for term in ("schema", "openapi", "swagger", "contract")):
        return "contract"
    if language in {"markdown", "rst"}:
        return "documentation"
    if language in SOURCE_LANGUAGES:
        return "source"
    if language in {"html", "css", "scss", "sass"}:
        return "ui_asset"
    return "asset"


def _generated(relative: str, text_head: str = "") -> bool:
    low = relative.casefold()
    return (
        any(
            part in {"generated", "gen", "dist", "build", "coverage", "vendor"}
            for part in Path(low).parts
        )
        or "generated file" in text_head.casefold()[:500]
        or "do not edit" in text_head.casefold()[:500]
    )


def _is_text(path: Path, sample: bytes) -> bool:
    if path.name.casefold() in TEXT_NAMES or path.suffix.casefold() in TEXT_SUFFIXES:
        return b"\x00" not in sample
    if b"\x00" in sample:
        return False
    if not sample:
        return True
    printable = sum(
        byte in b"\n\r\t\f\b" or 32 <= byte <= 126 or byte >= 128 for byte in sample
    )
    return printable / len(sample) >= 0.85


def _read_text(path: Path, max_text_bytes: int) -> tuple[str | None, dict[str, object]]:
    size = path.stat().st_size
    with path.open("rb") as stream:
        sample = stream.read(min(size, max_text_bytes, 8192))
        if not _is_text(path, sample):
            return None, {"binary": True, "text_truncated": False, "encoding": None}
        stream.seek(0)
        data = stream.read(max_text_bytes + 1)
    truncated = len(data) > max_text_bytes
    data = data[:max_text_bytes]
    encoding = "utf-8"
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        encoding = "utf-8-replacement"
        text = data.decode("utf-8", errors="replace")
    return text, {"binary": False, "text_truncated": truncated, "encoding": encoding}


def _attribute_name(node: AST) -> str:
    parts: list[str] = []
    current: AST | None = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    elif isinstance(current, ast.Call):
        parts.append(_attribute_name(current.func))
    return ".".join(reversed([part for part in parts if part]))


def _literal_string(node: AST | None) -> str | None:
    return (
        node.value
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        else None
    )


def _safe_url_domain(raw: str) -> str | None:
    try:
        parsed = urlparse(raw.rstrip(".,);]"))
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    host = parsed.hostname.casefold()
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme}://{host}{port}"


def _classify_call(callee: str) -> tuple[str | None, str | None, float]:
    low = callee.casefold()
    source = sink = None
    confidence = 0.65
    if low in {"open", "path.read_text", "path.read_bytes"} or low.endswith(
        (".read_text", ".read_bytes")
    ):
        source = "filesystem"
    if low.endswith((".write_text", ".write_bytes")):
        sink = "filesystem"
    if any(term in low for term in ("getenv", "environ", "config.get", "settings.")):
        source = "configuration"
    if any(
        term in low
        for term in ("requests.get", "httpx.get", "aiohttp", "axios.get", "fetch")
    ):
        source = "external_http"
    if any(
        term in low
        for term in (
            "requests.post",
            "requests.put",
            "httpx.post",
            "axios.post",
            "fetch",
        )
    ):
        sink = "external_http"
    if any(
        term in low
        for term in ("fetchone", "fetchall", "query", "select", "find_one", "findmany")
    ):
        source = "database"
    if any(
        term in low
        for term in (
            "execute",
            "executemany",
            "commit",
            "insert",
            "update",
            "delete",
            "save",
            "upsert",
        )
    ):
        sink = "database"
    if any(
        term in low
        for term in (
            "publish",
            "enqueue",
            "send_message",
            "produce",
            "delay",
            "apply_async",
        )
    ):
        sink = "queue_or_event_bus"
    if any(term in low for term in ("consume", "subscribe", "receive", "dequeue")):
        source = "queue_or_event_bus"
    if any(term in low for term in ("subprocess", "popen", "system", "exec")):
        sink = "process_boundary"
        confidence = 0.8
    return source, sink, confidence


class _PythonScanner(ast.NodeVisitor):
    def __init__(self, relative: str) -> None:
        self.relative = relative
        self.scope: list[str] = []
        self.symbols: list[dict[str, object]] = []
        self.imports: list[dict[str, object]] = []
        self.calls: list[dict[str, object]] = []
        self.routes: list[dict[str, object]] = []
        self.config_refs: list[dict[str, object]] = []
        self.data_flows: list[dict[str, object]] = []
        self.contracts: list[dict[str, object]] = []
        self.tests: list[dict[str, object]] = []

    def _qualname(self, name: str) -> str:
        return ".".join((*self.scope, name))

    def _decorators(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef
    ) -> list[str]:
        return [
            _attribute_name(item.func if isinstance(item, ast.Call) else item)
            for item in node.decorator_list
        ]

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        bases = [_attribute_name(base) for base in node.bases]
        decorators = self._decorators(node)
        symbol = {
            "name": node.name,
            "qualname": self._qualname(node.name),
            "kind": "class",
            "line_start": node.lineno,
            "line_end": getattr(node, "end_lineno", node.lineno),
            "bases": [value for value in bases if value],
            "decorators": [value for value in decorators if value],
        }
        self.symbols.append(symbol)
        if any(
            base.endswith(("BaseModel", "TypedDict", "Enum")) for base in bases
        ) or any(item.endswith("dataclass") for item in decorators):
            self.contracts.append(
                {
                    "id": f"python:{self.relative}:{symbol['qualname']}",
                    "kind": "python_model",
                    "name": node.name,
                    "path": self.relative,
                    "line": node.lineno,
                    "evidence": {"bases": bases, "decorators": decorators},
                }
            )
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        kind = (
            "async_function" if isinstance(node, ast.AsyncFunctionDef) else "function"
        )
        if self.scope:
            kind = (
                "async_method" if isinstance(node, ast.AsyncFunctionDef) else "method"
            )
        decorators = self._decorators(node)
        symbol = {
            "name": node.name,
            "qualname": self._qualname(node.name),
            "kind": kind,
            "line_start": node.lineno,
            "line_end": getattr(node, "end_lineno", node.lineno),
            "decorators": [value for value in decorators if value],
        }
        self.symbols.append(symbol)
        if node.name.startswith("test_"):
            self.tests.append(
                {
                    "name": symbol["qualname"],
                    "path": self.relative,
                    "line": node.lineno,
                    "kind": "test_function",
                }
            )
        for decorator in node.decorator_list:
            target = decorator.func if isinstance(decorator, ast.Call) else decorator
            name = _attribute_name(target)
            method = name.rsplit(".", 1)[-1].casefold()
            if method in ROUTE_METHODS or method == "api_route":
                route_path = (
                    _literal_string(decorator.args[0])
                    if isinstance(decorator, ast.Call) and decorator.args
                    else None
                )
                methods = [method.upper()] if method != "api_route" else []
                if isinstance(decorator, ast.Call):
                    for keyword in decorator.keywords:
                        if keyword.arg == "methods" and isinstance(
                            keyword.value, (ast.List, ast.Tuple)
                        ):
                            methods = [
                                str(value.value).upper()
                                for value in keyword.value.elts
                                if isinstance(value, ast.Constant)
                            ]
                self.routes.append(
                    {
                        "id": f"route:{self.relative}:{node.lineno}:{route_path or '?'}",
                        "path": route_path,
                        "methods": methods or ["UNKNOWN"],
                        "handler": symbol["qualname"],
                        "file": self.relative,
                        "line": node.lineno,
                        "framework_hint": name.rsplit(".", 1)[0] or "decorator",
                    }
                )
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.imports.append(
                {
                    "module": alias.name,
                    "name": None,
                    "alias": alias.asname,
                    "level": 0,
                    "line": node.lineno,
                }
            )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            self.imports.append(
                {
                    "module": node.module or "",
                    "name": alias.name,
                    "alias": alias.asname,
                    "level": node.level,
                    "line": node.lineno,
                }
            )

    def visit_Call(self, node: ast.Call) -> None:
        callee = _attribute_name(node.func)
        caller = ".".join(self.scope) or "<module>"
        self.calls.append({"callee": callee, "caller": caller, "line": node.lineno})
        source, sink, confidence = _classify_call(callee)
        if source or sink:
            self.data_flows.append(
                {
                    "file": self.relative,
                    "line": node.lineno,
                    "caller": caller,
                    "operation": callee,
                    "source": source,
                    "sink": sink,
                    "confidence": confidence,
                    "basis": "static_call_pattern",
                }
            )
        if callee in {"os.getenv", "os.environ.get"} and node.args:
            key = _literal_string(node.args[0])
            if key:
                self.config_refs.append(
                    {
                        "key": key,
                        "path": self.relative,
                        "line": node.lineno,
                        "access": callee,
                        "sensitive": bool(SENSITIVE_KEY.search(key)),
                    }
                )
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        target = _attribute_name(node.value)
        if target == "os.environ":
            key = _literal_string(node.slice)
            if key:
                self.config_refs.append(
                    {
                        "key": key,
                        "path": self.relative,
                        "line": node.lineno,
                        "access": "os.environ[]",
                        "sensitive": bool(SENSITIVE_KEY.search(key)),
                    }
                )
        self.generic_visit(node)


def _scan_python(text: str, relative: str) -> dict[str, object]:
    scanner = _PythonScanner(relative)
    try:
        tree = ast.parse(text, filename=relative)
    except SyntaxError as error:
        return {
            "parse_errors": [
                {
                    "code": "python_syntax_error",
                    "line": error.lineno,
                    "message": error.msg,
                }
            ]
        }
    scanner.visit(tree)
    return {
        "symbols": scanner.symbols,
        "imports": scanner.imports,
        "calls": scanner.calls,
        "routes": scanner.routes,
        "config_refs": scanner.config_refs,
        "data_flows": scanner.data_flows,
        "contracts": scanner.contracts,
        "tests": scanner.tests,
    }


def _line_number(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def _regex_records(
    text: str, pattern: re.Pattern[str], transform: Any
) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for match in pattern.finditer(text):
        record = transform(match)
        if record:
            record.setdefault("line", _line_number(text, match.start()))
            records.append(record)
    return records


JS_IMPORT_RE = re.compile(
    r"(?:import\s+(?:(?:[^;]+?)\s+from\s+)?|export\s+[^;]+?\s+from\s+|require\s*\()\s*['\"]([^'\"]+)['\"]"
)
JS_SYMBOL_RE = re.compile(
    r"(?m)^\s*(?:export\s+)?(?:default\s+)?(?:(async)\s+)?(function|class|interface|type|enum)\s+([A-Za-z_$][\w$]*)|^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>"
)
JS_ROUTE_RE = re.compile(
    r"\b(?:app|router|server)\.(get|post|put|patch|delete|options|head|use)\s*\(\s*['\"]([^'\"]+)['\"]",
    re.IGNORECASE,
)
JS_ENV_RE = re.compile(
    r"\bprocess\.env\.([A-Za-z_][A-Za-z0-9_]*)|\bprocess\.env\[['\"]([^'\"]+)['\"]\]"
)
JS_CALL_RE = re.compile(
    r"\b(fetch|axios\.(?:get|post|put|patch|delete)|[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)+)\s*\("
)


def _scan_js(text: str, relative: str, language: str) -> dict[str, object]:
    imports = [
        {"specifier": match.group(1), "line": _line_number(text, match.start())}
        for match in JS_IMPORT_RE.finditer(text)
    ]
    symbols: list[dict[str, object]] = []
    for match in JS_SYMBOL_RE.finditer(text):
        kind = match.group(2) or "arrow_function"
        name = match.group(3) or match.group(4)
        symbols.append(
            {
                "name": name,
                "qualname": name,
                "kind": f"{language}_{kind}",
                "line_start": _line_number(text, match.start()),
                "line_end": _line_number(text, match.end()),
            }
        )
    routes = [
        {
            "id": f"route:{relative}:{_line_number(text, m.start())}:{m.group(2)}",
            "path": m.group(2),
            "methods": [m.group(1).upper()],
            "handler": None,
            "file": relative,
            "line": _line_number(text, m.start()),
            "framework_hint": "express_like",
        }
        for m in JS_ROUTE_RE.finditer(text)
    ]
    config_refs = []
    for match in JS_ENV_RE.finditer(text):
        key = match.group(1) or match.group(2)
        config_refs.append(
            {
                "key": key,
                "path": relative,
                "line": _line_number(text, match.start()),
                "access": "process.env",
                "sensitive": bool(SENSITIVE_KEY.search(key)),
            }
        )
    calls = []
    data_flows = []
    for match in JS_CALL_RE.finditer(text):
        callee = match.group(1)
        line = _line_number(text, match.start())
        calls.append({"callee": callee, "caller": "<unknown>", "line": line})
        source, sink, confidence = _classify_call(callee)
        if source or sink:
            data_flows.append(
                {
                    "file": relative,
                    "line": line,
                    "caller": "<unknown>",
                    "operation": callee,
                    "source": source,
                    "sink": sink,
                    "confidence": confidence,
                    "basis": "static_call_pattern",
                }
            )
    contracts = []
    for symbol in symbols:
        if any(term in str(symbol["kind"]) for term in ("interface", "type", "enum")):
            contracts.append(
                {
                    "id": f"{language}:{relative}:{symbol['name']}",
                    "kind": f"{language}_type",
                    "name": symbol["name"],
                    "path": relative,
                    "line": symbol["line_start"],
                }
            )
    tests = [
        {
            "name": symbol["name"],
            "path": relative,
            "line": symbol["line_start"],
            "kind": "test_symbol",
        }
        for symbol in symbols
        if str(symbol["name"]).casefold().startswith(("test", "should"))
    ]
    return {
        "symbols": symbols,
        "imports": imports,
        "calls": calls,
        "routes": routes,
        "config_refs": config_refs,
        "data_flows": data_flows,
        "contracts": contracts,
        "tests": tests,
    }


GO_IMPORT_RE = re.compile(
    r"(?m)^\s*import\s+(?:\w+\s+)?\"([^\"]+)\"|^\s*\"([^\"]+)\"\s*$"
)
GO_SYMBOL_RE = re.compile(
    r"(?m)^\s*func\s+(?:\([^)]*\)\s*)?([A-Za-z_][A-Za-z0-9_]*)\s*\(|^\s*type\s+([A-Za-z_][A-Za-z0-9_]*)\s+(struct|interface)\b"
)
GO_ENV_RE = re.compile(r"\bos\.(?:Getenv|LookupEnv)\(\s*\"([^\"]+)\"")
GO_ROUTE_RE = re.compile(r"\b(?:http\.)?HandleFunc\(\s*\"([^\"]+)\"")

RUST_IMPORT_RE = re.compile(r"(?m)^\s*(?:use|mod)\s+([^;{]+)")
RUST_SYMBOL_RE = re.compile(
    r"(?m)^\s*(?:pub\s+)?(?:async\s+)?(fn|struct|enum|trait|type|const|static)\s+([A-Za-z_][A-Za-z0-9_]*)"
)
RUST_ENV_RE = re.compile(r"\b(?:std::)?env::var\(\s*\"([^\"]+)\"")

JVM_IMPORT_RE = re.compile(r"(?m)^\s*import\s+([A-Za-z0-9_.*]+)\s*;?")
JVM_SYMBOL_RE = re.compile(
    r"(?m)^\s*(?:(?:public|private|protected|internal|abstract|final|static|sealed|data|open|partial)\s+)*(class|interface|enum|record|object)\s+([A-Za-z_][A-Za-z0-9_]*)"
)
CS_USING_RE = re.compile(r"(?m)^\s*using\s+([A-Za-z0-9_.]+)\s*;")
SPRING_ROUTE_RE = re.compile(
    r"@(Get|Post|Put|Patch|Delete|Request)Mapping\s*\(\s*(?:value\s*=\s*)?\"([^\"]+)\""
)
CS_ROUTE_RE = re.compile(
    r"\[(HttpGet|HttpPost|HttpPut|HttpPatch|HttpDelete)(?:\(\s*\"([^\"]*)\"\s*\))?\]"
)

RUBY_SYMBOL_RE = re.compile(
    r"(?m)^\s*(class|module|def)\s+([A-Za-z_][A-Za-z0-9_:!?=]*)"
)
RUBY_REQUIRE_RE = re.compile(r"(?m)^\s*require(?:_relative)?\s+['\"]([^'\"]+)['\"]")
PHP_SYMBOL_RE = re.compile(
    r"(?m)^\s*(?:final\s+|abstract\s+)?(class|interface|trait|function)\s+([A-Za-z_][A-Za-z0-9_]*)"
)
PHP_USE_RE = re.compile(
    r"(?m)^\s*(?:use|require|include)(?:_once)?\s*(?:\(|)\s*['\"]?([^;'\")]+)"
)


def _scan_regex_language(text: str, relative: str, language: str) -> dict[str, object]:
    symbols: list[dict[str, object]] = []
    imports: list[dict[str, object]] = []
    routes: list[dict[str, object]] = []
    config_refs: list[dict[str, object]] = []
    contracts: list[dict[str, object]] = []
    if language == "go":
        for match in GO_IMPORT_RE.finditer(text):
            imports.append(
                {
                    "specifier": match.group(1) or match.group(2),
                    "line": _line_number(text, match.start()),
                }
            )
        for match in GO_SYMBOL_RE.finditer(text):
            name = match.group(1) or match.group(2)
            kind = "function" if match.group(1) else match.group(3)
            symbols.append(
                {
                    "name": name,
                    "qualname": name,
                    "kind": f"go_{kind}",
                    "line_start": _line_number(text, match.start()),
                    "line_end": _line_number(text, match.end()),
                }
            )
            if kind in {"struct", "interface"}:
                contracts.append(
                    {
                        "id": f"go:{relative}:{name}",
                        "kind": f"go_{kind}",
                        "name": name,
                        "path": relative,
                        "line": _line_number(text, match.start()),
                    }
                )
        for match in GO_ENV_RE.finditer(text):
            key = match.group(1)
            config_refs.append(
                {
                    "key": key,
                    "path": relative,
                    "line": _line_number(text, match.start()),
                    "access": "os.Getenv",
                    "sensitive": bool(SENSITIVE_KEY.search(key)),
                }
            )
        for match in GO_ROUTE_RE.finditer(text):
            routes.append(
                {
                    "id": f"route:{relative}:{_line_number(text, match.start())}:{match.group(1)}",
                    "path": match.group(1),
                    "methods": ["UNKNOWN"],
                    "handler": None,
                    "file": relative,
                    "line": _line_number(text, match.start()),
                    "framework_hint": "net/http",
                }
            )
    elif language == "rust":
        imports = [
            {"specifier": m.group(1).strip(), "line": _line_number(text, m.start())}
            for m in RUST_IMPORT_RE.finditer(text)
        ]
        for match in RUST_SYMBOL_RE.finditer(text):
            kind, name = match.group(1), match.group(2)
            symbols.append(
                {
                    "name": name,
                    "qualname": name,
                    "kind": f"rust_{kind}",
                    "line_start": _line_number(text, match.start()),
                    "line_end": _line_number(text, match.end()),
                }
            )
            if kind in {"struct", "enum", "trait", "type"}:
                contracts.append(
                    {
                        "id": f"rust:{relative}:{name}",
                        "kind": f"rust_{kind}",
                        "name": name,
                        "path": relative,
                        "line": _line_number(text, match.start()),
                    }
                )
        for match in RUST_ENV_RE.finditer(text):
            key = match.group(1)
            config_refs.append(
                {
                    "key": key,
                    "path": relative,
                    "line": _line_number(text, match.start()),
                    "access": "env::var",
                    "sensitive": bool(SENSITIVE_KEY.search(key)),
                }
            )
    elif language in {"java", "kotlin", "csharp"}:
        import_re = CS_USING_RE if language == "csharp" else JVM_IMPORT_RE
        imports = [
            {"specifier": m.group(1), "line": _line_number(text, m.start())}
            for m in import_re.finditer(text)
        ]
        for match in JVM_SYMBOL_RE.finditer(text):
            kind, name = match.group(1), match.group(2)
            symbols.append(
                {
                    "name": name,
                    "qualname": name,
                    "kind": f"{language}_{kind}",
                    "line_start": _line_number(text, match.start()),
                    "line_end": _line_number(text, match.end()),
                }
            )
            if kind in {"interface", "enum", "record"}:
                contracts.append(
                    {
                        "id": f"{language}:{relative}:{name}",
                        "kind": f"{language}_{kind}",
                        "name": name,
                        "path": relative,
                        "line": _line_number(text, match.start()),
                    }
                )
        route_re = CS_ROUTE_RE if language == "csharp" else SPRING_ROUTE_RE
        for match in route_re.finditer(text):
            method = (
                match.group(1).replace("Http", "").replace("Mapping", "").upper()
                or "UNKNOWN"
            )
            route = match.group(2) or ""
            routes.append(
                {
                    "id": f"route:{relative}:{_line_number(text, match.start())}:{route}",
                    "path": route,
                    "methods": [method],
                    "handler": None,
                    "file": relative,
                    "line": _line_number(text, match.start()),
                    "framework_hint": "annotation_route",
                }
            )
    elif language == "ruby":
        imports = [
            {"specifier": m.group(1), "line": _line_number(text, m.start())}
            for m in RUBY_REQUIRE_RE.finditer(text)
        ]
        for match in RUBY_SYMBOL_RE.finditer(text):
            symbols.append(
                {
                    "name": match.group(2),
                    "qualname": match.group(2),
                    "kind": f"ruby_{match.group(1)}",
                    "line_start": _line_number(text, match.start()),
                    "line_end": _line_number(text, match.end()),
                }
            )
    elif language == "php":
        imports = [
            {"specifier": m.group(1).strip(), "line": _line_number(text, m.start())}
            for m in PHP_USE_RE.finditer(text)
        ]
        for match in PHP_SYMBOL_RE.finditer(text):
            kind, name = match.group(1), match.group(2)
            symbols.append(
                {
                    "name": name,
                    "qualname": name,
                    "kind": f"php_{kind}",
                    "line_start": _line_number(text, match.start()),
                    "line_end": _line_number(text, match.end()),
                }
            )
            if kind in {"interface", "trait"}:
                contracts.append(
                    {
                        "id": f"php:{relative}:{name}",
                        "kind": f"php_{kind}",
                        "name": name,
                        "path": relative,
                        "line": _line_number(text, match.start()),
                    }
                )
    return {
        "symbols": symbols,
        "imports": imports,
        "routes": routes,
        "config_refs": config_refs,
        "contracts": contracts,
    }


def _flatten_keys(value: object, prefix: str = "", depth: int = 0) -> list[str]:
    if depth > 8:
        return []
    result: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            name = f"{prefix}.{key}" if prefix else str(key)
            result.append(name)
            result.extend(_flatten_keys(child, name, depth + 1))
    elif isinstance(value, list):
        for child in value[:20]:
            result.extend(_flatten_keys(child, prefix, depth + 1))
    return result


def _dependency_name(raw: str) -> str:
    return (
        re.split(r"[<>=!~\[\s;]", raw.strip(), 1)[0]
        .strip()
        .casefold()
        .replace("_", "-")
    )


def _scan_known_config(text: str, relative: str, language: str) -> dict[str, object]:
    name = Path(relative).name.casefold()
    config_keys: list[dict[str, object]] = []
    dependencies: list[dict[str, object]] = []
    entrypoints: list[dict[str, object]] = []
    services: list[dict[str, object]] = []
    contracts: list[dict[str, object]] = []
    ci: list[dict[str, object]] = []
    ownership: list[dict[str, object]] = []
    parse_errors: list[dict[str, object]] = []

    if name == "package.json":
        try:
            data = json.loads(text)
            for section, scope in (
                ("dependencies", "runtime"),
                ("devDependencies", "development"),
                ("peerDependencies", "peer"),
                ("optionalDependencies", "optional"),
            ):
                for package in sorted((data.get(section) or {}).keys()):
                    dependencies.append(
                        {
                            "name": package,
                            "scope": scope,
                            "source": relative,
                            "ecosystem": "npm",
                        }
                    )
            for script in sorted((data.get("scripts") or {}).keys()):
                entrypoints.append(
                    {"kind": "npm_script", "name": script, "source": relative}
                )
            for key in _flatten_keys(data):
                config_keys.append(
                    {
                        "key": key,
                        "path": relative,
                        "line": None,
                        "access": "json_key",
                        "sensitive": bool(SENSITIVE_KEY.search(key)),
                    }
                )
        except json.JSONDecodeError as error:
            parse_errors.append(
                {"code": "json_parse_error", "line": error.lineno, "message": error.msg}
            )
    elif name == "pyproject.toml":
        try:
            data = tomllib.loads(text)
            project = data.get("project", {})
            for raw in project.get("dependencies", ()):
                dependencies.append(
                    {
                        "name": _dependency_name(str(raw)),
                        "scope": "runtime",
                        "source": relative,
                        "ecosystem": "python",
                    }
                )
            for group, values in (
                project.get("optional-dependencies", {}) or {}
            ).items():
                for raw in values:
                    dependencies.append(
                        {
                            "name": _dependency_name(str(raw)),
                            "scope": f"optional:{group}",
                            "source": relative,
                            "ecosystem": "python",
                        }
                    )
            for script, target in (project.get("scripts", {}) or {}).items():
                entrypoints.append(
                    {
                        "kind": "python_console_script",
                        "name": script,
                        "target": str(target),
                        "source": relative,
                    }
                )
            for key in _flatten_keys(data):
                config_keys.append(
                    {
                        "key": key,
                        "path": relative,
                        "line": None,
                        "access": "toml_key",
                        "sensitive": bool(SENSITIVE_KEY.search(key)),
                    }
                )
        except tomllib.TOMLDecodeError as error:
            parse_errors.append(
                {"code": "toml_parse_error", "line": None, "message": str(error)}
            )
    elif name == "cargo.toml":
        try:
            data = tomllib.loads(text)
            for section, scope in (
                ("dependencies", "runtime"),
                ("dev-dependencies", "development"),
                ("build-dependencies", "build"),
            ):
                for package in sorted((data.get(section) or {}).keys()):
                    dependencies.append(
                        {
                            "name": package,
                            "scope": scope,
                            "source": relative,
                            "ecosystem": "cargo",
                        }
                    )
        except tomllib.TOMLDecodeError as error:
            parse_errors.append(
                {"code": "toml_parse_error", "line": None, "message": str(error)}
            )
    elif name == "go.mod":
        for match in re.finditer(r"(?m)^\s*([A-Za-z0-9_.~/-]+)\s+v[0-9]", text):
            dependencies.append(
                {
                    "name": match.group(1),
                    "scope": "runtime",
                    "source": relative,
                    "ecosystem": "go",
                }
            )
    elif name.startswith("requirements") and name.endswith(".txt"):
        for line_number, line in enumerate(text.splitlines(), 1):
            clean = line.split("#", 1)[0].strip()
            if clean and not clean.startswith(("-", "git+", "http:")):
                dependencies.append(
                    {
                        "name": _dependency_name(clean),
                        "scope": "runtime",
                        "source": relative,
                        "ecosystem": "python",
                        "line": line_number,
                    }
                )
    elif name in {
        "docker-compose.yml",
        "docker-compose.yaml",
        "compose.yml",
        "compose.yaml",
    }:
        services.extend(_parse_compose(text, relative))
    elif name == "dockerfile" or name.endswith(".dockerfile"):
        for line_number, line in enumerate(text.splitlines(), 1):
            match = re.match(
                r"\s*(FROM|ENTRYPOINT|CMD|EXPOSE|HEALTHCHECK)\s+(.+)",
                line,
                re.IGNORECASE,
            )
            if match:
                entrypoints.append(
                    {
                        "kind": f"docker_{match.group(1).casefold()}",
                        "name": match.group(2).strip()[:200],
                        "source": relative,
                        "line": line_number,
                    }
                )
    elif name in {"codeowners", "owners"} or relative.casefold().endswith(
        "/.github/codeowners"
    ):
        for line_number, line in enumerate(text.splitlines(), 1):
            clean = line.strip()
            if not clean or clean.startswith("#"):
                continue
            parts = clean.split()
            if len(parts) >= 2:
                ownership.append(
                    {
                        "pattern": parts[0],
                        "owners": parts[1:],
                        "source": relative,
                        "line": line_number,
                    }
                )
    elif relative.casefold().startswith((".github/workflows/", ".gitlab/")) or name in {
        "azure-pipelines.yml",
        "jenkinsfile",
        ".gitlab-ci.yml",
    }:
        jobs = []
        for line_number, line in enumerate(text.splitlines(), 1):
            match = re.match(r"\s{2,}([A-Za-z0-9_.-]+):\s*(?:#.*)?$", line)
            if match and match.group(1) not in {
                "steps",
                "env",
                "with",
                "permissions",
                "on",
            }:
                jobs.append({"name": match.group(1), "line": line_number})
        uses = sorted(set(re.findall(r"\buses:\s*([^\s#]+)", text)))
        ci.append({"source": relative, "jobs": jobs[:100], "external_actions": uses})
    elif language == "json":
        try:
            data = json.loads(text)
            for key in _flatten_keys(data):
                config_keys.append(
                    {
                        "key": key,
                        "path": relative,
                        "line": None,
                        "access": "json_key",
                        "sensitive": bool(SENSITIVE_KEY.search(key)),
                    }
                )
            if any(term in name for term in ("openapi", "swagger")):
                for route, methods in (data.get("paths") or {}).items():
                    for method in methods:
                        if method.casefold() in ROUTE_METHODS:
                            contracts.append(
                                {
                                    "id": f"openapi:{relative}:{method}:{route}",
                                    "kind": "openapi_operation",
                                    "name": f"{method.upper()} {route}",
                                    "path": relative,
                                    "line": None,
                                }
                            )
        except json.JSONDecodeError as error:
            parse_errors.append(
                {"code": "json_parse_error", "line": error.lineno, "message": error.msg}
            )
    elif name.startswith(".env") or language in {"toml", "yaml"}:
        for line_number, line in enumerate(text.splitlines(), 1):
            match = re.match(r"\s*([A-Za-z_][A-Za-z0-9_.-]*)\s*[:=]", line)
            if match:
                key = match.group(1)
                config_keys.append(
                    {
                        "key": key,
                        "path": relative,
                        "line": line_number,
                        "access": "config_declaration",
                        "sensitive": bool(SENSITIVE_KEY.search(key)),
                    }
                )
    if language == "protobuf":
        for match in re.finditer(
            r"(?m)^\s*(message|service|enum)\s+([A-Za-z_][A-Za-z0-9_]*)", text
        ):
            contracts.append(
                {
                    "id": f"proto:{relative}:{match.group(2)}",
                    "kind": f"proto_{match.group(1)}",
                    "name": match.group(2),
                    "path": relative,
                    "line": _line_number(text, match.start()),
                }
            )
    elif language == "graphql":
        for match in re.finditer(
            r"(?m)^\s*(type|input|interface|enum|union|scalar)\s+([A-Za-z_][A-Za-z0-9_]*)",
            text,
        ):
            contracts.append(
                {
                    "id": f"graphql:{relative}:{match.group(2)}",
                    "kind": f"graphql_{match.group(1)}",
                    "name": match.group(2),
                    "path": relative,
                    "line": _line_number(text, match.start()),
                }
            )
    elif language == "sql":
        for match in re.finditer(
            r"(?i)\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[\"`\[]?([A-Za-z_][A-Za-z0-9_.]*)",
            text,
        ):
            contracts.append(
                {
                    "id": f"sql:{relative}:{match.group(1)}",
                    "kind": "database_table",
                    "name": match.group(1),
                    "path": relative,
                    "line": _line_number(text, match.start()),
                }
            )
    return {
        "config_refs": config_keys,
        "dependencies": dependencies,
        "entrypoints": entrypoints,
        "services": services,
        "contracts": contracts,
        "ci": ci,
        "ownership": ownership,
        "parse_errors": parse_errors,
    }


def _parse_compose(text: str, relative: str) -> list[dict[str, object]]:
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(text) or {}
        services = []
        for name, spec in sorted((data.get("services") or {}).items()):
            spec = spec or {}
            environment = spec.get("environment") or {}
            if isinstance(environment, list):
                env_keys = sorted(str(item).split("=", 1)[0] for item in environment)
            else:
                env_keys = sorted(map(str, environment.keys()))
            depends = spec.get("depends_on") or []
            if isinstance(depends, Mapping):
                depends = list(depends)
            services.append(
                {
                    "id": f"service:{name}",
                    "name": str(name),
                    "source": relative,
                    "image": str(spec.get("image", "")) or None,
                    "build": str(spec.get("build", ""))
                    if not isinstance(spec.get("build"), Mapping)
                    else str(spec.get("build", {}).get("context", "")),
                    "depends_on": sorted(map(str, depends)),
                    "ports": [str(item) for item in spec.get("ports", ())],
                    "environment_keys": env_keys,
                    "command_declared": "command" in spec,
                }
            )
        return services
    except Exception:
        services: list[dict[str, object]] = []
        lines = text.splitlines()
        in_services = False
        current: dict[str, object] | None = None
        base_indent = 0
        for number, line in enumerate(lines, 1):
            if re.match(r"^services:\s*$", line):
                in_services = True
                base_indent = len(line) - len(line.lstrip())
                continue
            if not in_services:
                continue
            indent = len(line) - len(line.lstrip())
            match = re.match(r"^\s+([A-Za-z0-9_.-]+):\s*$", line)
            if (
                match
                and indent > base_indent
                and (current is None or indent <= int(current.get("indent", indent)))
            ):
                if current:
                    current.pop("indent", None)
                    services.append(current)
                current = {
                    "id": f"service:{match.group(1)}",
                    "name": match.group(1),
                    "source": relative,
                    "line": number,
                    "depends_on": [],
                    "ports": [],
                    "environment_keys": [],
                    "indent": indent,
                }
                continue
            if current:
                scalar = re.match(r"^\s+(image|build|command):\s*(.+)$", line)
                if scalar:
                    key = scalar.group(1)
                    value = scalar.group(2).strip().strip("'\"")
                    current["command_declared" if key == "command" else key] = (
                        True if key == "command" else value
                    )
        if current:
            current.pop("indent", None)
            services.append(current)
        return services


def _headings(text: str, language: str) -> list[str]:
    if language in {"markdown", "rst"}:
        values = [
            match.group(1).strip()
            for match in re.finditer(r"(?m)^#{1,6}\s+(.+)$", text)
        ]
        return values[:100]
    return []


def _scan_file(
    path: Path, root: Path, sha256: str, max_text_bytes: int
) -> dict[str, object]:
    relative = path.relative_to(root).as_posix()
    language = _language(path)
    text, text_meta = _read_text(path, max_text_bytes)
    fact: dict[str, object] = {
        "adapter_version": ADAPTER_VERSION,
        "path": relative,
        "sha256": sha256,
        "size_bytes": path.stat().st_size,
        "language": language,
        "role": _role(relative, language),
        "binary": text_meta["binary"],
        "text_truncated": text_meta["text_truncated"],
        "encoding": text_meta["encoding"],
        "generated": False,
        "line_count": 0,
        "symbols": [],
        "imports": [],
        "calls": [],
        "routes": [],
        "config_refs": [],
        "data_flows": [],
        "contracts": [],
        "tests": [],
        "dependencies": [],
        "entrypoints": [],
        "services": [],
        "ci": [],
        "ownership": [],
        "urls": [],
        "headings": [],
        "parse_errors": [],
    }
    if text is None:
        return fact
    fact["line_count"] = text.count("\n") + (1 if text else 0)
    fact["generated"] = _generated(relative, text[:500])
    fact["headings"] = _headings(text, language)
    domains = sorted(
        {domain for raw in URL_RE.findall(text) if (domain := _safe_url_domain(raw))}
    )
    fact["urls"] = domains[:200]
    scans: list[dict[str, object]] = []
    if language == "python":
        scans.append(_scan_python(text, relative))
    elif language in {"javascript", "typescript"}:
        scans.append(_scan_js(text, relative, language))
    elif language in {"go", "rust", "java", "kotlin", "csharp", "ruby", "php"}:
        scans.append(_scan_regex_language(text, relative, language))
    scans.append(_scan_known_config(text, relative, language))
    list_fields = {
        "symbols",
        "imports",
        "calls",
        "routes",
        "config_refs",
        "data_flows",
        "contracts",
        "tests",
        "dependencies",
        "entrypoints",
        "services",
        "ci",
        "ownership",
        "parse_errors",
    }
    for scan in scans:
        for key in list_fields:
            if scan.get(key):
                fact[key].extend(scan[key])  # type: ignore[union-attr]
    return fact


def _python_module(relative: str) -> str | None:
    path = Path(relative)
    if path.suffix.casefold() not in {".py", ".pyi"}:
        return None
    parts = list(path.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _resolve_relative_js(source: str, specifier: str, files: set[str]) -> str | None:
    if not specifier.startswith("."):
        return None
    base = (Path(source).parent / specifier).as_posix()
    candidates = [
        base,
        *[
            base + suffix
            for suffix in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".json")
        ],
        *[
            (Path(base) / f"index{suffix}").as_posix()
            for suffix in (".ts", ".tsx", ".js", ".jsx")
        ],
    ]
    normalized = {Path(item).as_posix(): item for item in files}
    for candidate in candidates:
        clean = Path(candidate).as_posix()
        if clean in normalized:
            return normalized[clean]
    return None


def _dependency_graph(facts: Sequence[Mapping[str, object]]) -> dict[str, object]:
    files = {str(fact["path"]) for fact in facts}
    python_modules: dict[str, str] = {}
    for path in files:
        module = _python_module(path)
        if module is not None:
            python_modules[module] = path
    nodes: dict[str, dict[str, object]] = {
        f"file:{path}": {"id": f"file:{path}", "kind": "file", "path": path}
        for path in files
    }
    edges: list[dict[str, object]] = []
    unresolved: list[dict[str, object]] = []
    external: set[tuple[str, str]] = set()
    for fact in facts:
        source = str(fact["path"])
        language = str(fact["language"])
        for item in fact.get("imports", ()):  # type: ignore[union-attr]
            target: str | None = None
            specifier = str(item.get("module") or item.get("specifier") or "")
            if language == "python":
                level = int(item.get("level") or 0)
                module = specifier
                if level:
                    current = _python_module(source) or ""
                    package = current.split(".")[:-1]
                    keep = max(0, len(package) - level + 1)
                    module = ".".join(
                        (*package[:keep], *([specifier] if specifier else []))
                    ).strip(".")
                candidates = (
                    [
                        module,
                        *[
                            ".".join(module.split(".")[:index])
                            for index in range(len(module.split(".")) - 1, 0, -1)
                        ],
                    ]
                    if module
                    else []
                )
                target = next(
                    (
                        python_modules[value]
                        for value in candidates
                        if value in python_modules
                    ),
                    None,
                )
            elif language in {"javascript", "typescript"}:
                target = _resolve_relative_js(source, specifier, files)
            if target:
                edges.append(
                    {
                        "from": f"file:{source}",
                        "to": f"file:{target}",
                        "kind": "imports",
                        "line": item.get("line"),
                        "specifier": specifier,
                        "resolved": True,
                    }
                )
            elif specifier:
                package = (
                    specifier.split("/", 1)[0]
                    if not specifier.startswith("@")
                    else "/".join(specifier.split("/")[:2])
                )
                external.add((language, package))
                node_id = f"external:{language}:{package}"
                nodes.setdefault(
                    node_id,
                    {
                        "id": node_id,
                        "kind": "external_package",
                        "name": package,
                        "ecosystem_hint": language,
                    },
                )
                edges.append(
                    {
                        "from": f"file:{source}",
                        "to": node_id,
                        "kind": "imports_external",
                        "line": item.get("line"),
                        "specifier": specifier,
                        "resolved": False,
                    }
                )
                if specifier.startswith(".") or (
                    language == "python"
                    and specifier.split(".", 1)[0]
                    not in {
                        "os",
                        "sys",
                        "json",
                        "pathlib",
                        "typing",
                        "collections",
                        "datetime",
                        "re",
                        "math",
                        "hashlib",
                        "argparse",
                        "subprocess",
                        "tempfile",
                        "shutil",
                        "itertools",
                        "functools",
                        "dataclasses",
                        "enum",
                        "logging",
                        "asyncio",
                        "unittest",
                    }
                ):
                    unresolved.append(
                        {
                            "source": source,
                            "specifier": specifier,
                            "line": item.get("line"),
                            "language": language,
                        }
                    )
        for dep in fact.get("dependencies", ()):  # type: ignore[union-attr]
            name = str(dep.get("name", ""))
            ecosystem = str(dep.get("ecosystem", "unknown"))
            if not name:
                continue
            node_id = f"external:{ecosystem}:{name}"
            nodes.setdefault(
                node_id,
                {
                    "id": node_id,
                    "kind": "external_package",
                    "name": name,
                    "ecosystem_hint": ecosystem,
                },
            )
            edges.append(
                {
                    "from": f"file:{source}",
                    "to": node_id,
                    "kind": "declares_dependency",
                    "scope": dep.get("scope"),
                    "resolved": True,
                }
            )
        for service in fact.get("services", ()):  # type: ignore[union-attr]
            node_id = str(service.get("id"))
            nodes[node_id] = {
                "id": node_id,
                "kind": "service",
                "name": service.get("name"),
                "source": source,
            }
            edges.append(
                {
                    "from": f"file:{source}",
                    "to": node_id,
                    "kind": "declares_service",
                    "resolved": True,
                }
            )
    for fact in facts:
        for service in fact.get("services", ()):  # type: ignore[union-attr]
            source_id = str(service.get("id"))
            for dependency in service.get("depends_on", ()):  # type: ignore[union-attr]
                target_id = f"service:{dependency}"
                if target_id in nodes:
                    edges.append(
                        {
                            "from": source_id,
                            "to": target_id,
                            "kind": "service_depends_on",
                            "resolved": True,
                        }
                    )
                else:
                    unresolved.append(
                        {
                            "source": source_id,
                            "specifier": dependency,
                            "language": "compose",
                            "line": service.get("line"),
                        }
                    )
    edges.sort(
        key=lambda item: (
            str(item["from"]),
            str(item["to"]),
            str(item["kind"]),
            int(item.get("line") or 0),
        )
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "nodes": sorted(nodes.values(), key=lambda item: str(item["id"])),
        "edges": edges,
        "unresolved": sorted(
            unresolved, key=lambda item: (str(item["source"]), str(item["specifier"]))
        ),
    }


def _call_graph(
    facts: Sequence[Mapping[str, object]],
    dependency_graph: Mapping[str, object] | None = None,
) -> dict[str, object]:
    nodes: dict[str, dict[str, object]] = {}
    by_file_name: dict[str, dict[str, str]] = defaultdict(dict)
    for fact in facts:
        path = str(fact["path"])
        for symbol in fact.get("symbols", ()):  # type: ignore[union-attr]
            node_id = f"symbol:{path}:{symbol.get('qualname')}"
            nodes[node_id] = {
                "id": node_id,
                "kind": symbol.get("kind"),
                "name": symbol.get("qualname"),
                "path": path,
                "line": symbol.get("line_start"),
            }
            by_file_name[path][str(symbol.get("name"))] = node_id
    edges: list[dict[str, object]] = []
    external_calls: Counter[str] = Counter()
    imported_targets: dict[tuple[str, str], str] = {}
    dependency_edges = list((dependency_graph or {}).get("edges", ()))
    for fact in facts:
        path = str(fact["path"])
        for imported in fact.get("imports", ()):  # type: ignore[union-attr]
            imported_name = str(imported.get("alias") or imported.get("name") or "")
            if not imported_name or imported_name == "*":
                continue
            specifier = str(imported.get("module") or imported.get("specifier") or "")
            target_file = None
            for edge in dependency_edges:
                if (
                    edge.get("from") == f"file:{path}"
                    and edge.get("kind") == "imports"
                    and (
                        edge.get("line") == imported.get("line")
                        or edge.get("specifier") == specifier
                    )
                ):
                    target_file = str(edge.get("to", "")).removeprefix("file:")
                    break
            target_symbol = by_file_name.get(target_file or "", {}).get(
                str(imported.get("name") or imported_name)
            )
            if target_symbol:
                imported_targets[(path, imported_name)] = target_symbol
    for fact in facts:
        path = str(fact["path"])
        for call in fact.get("calls", ()):  # type: ignore[union-attr]
            callee = str(call.get("callee", ""))
            leaf = callee.rsplit(".", 1)[-1]
            target = by_file_name[path].get(leaf) or imported_targets.get((path, leaf))
            caller_name = str(call.get("caller", "<module>"))
            caller = (
                f"symbol:{path}:{caller_name}"
                if f"symbol:{path}:{caller_name}" in nodes
                else f"file:{path}"
            )
            if target:
                edges.append(
                    {
                        "from": caller,
                        "to": target,
                        "kind": "calls",
                        "line": call.get("line"),
                        "resolved": True,
                    }
                )
            elif callee and ("." in callee or callee in {"open", "fetch"}):
                external_calls[callee] += 1
    edges.sort(
        key=lambda item: (
            str(item["from"]),
            str(item["to"]),
            int(item.get("line") or 0),
        )
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "nodes": sorted(nodes.values(), key=lambda item: str(item["id"])),
        "edges": edges,
        "external_call_summary": [
            {"callee": key, "count": value}
            for key, value in external_calls.most_common(200)
        ],
    }


def _runtime_topology(facts: Sequence[Mapping[str, object]]) -> dict[str, object]:
    services = [dict(service) for fact in facts for service in fact.get("services", ())]  # type: ignore[union-attr]
    entrypoints = [dict(item) for fact in facts for item in fact.get("entrypoints", ())]  # type: ignore[union-attr]
    pipelines = [dict(item) for fact in facts for item in fact.get("ci", ())]  # type: ignore[union-attr]
    runtime_markers: Counter[str] = Counter()
    for fact in facts:
        for dep in fact.get("dependencies", ()):  # type: ignore[union-attr]
            name = str(dep.get("name", "")).casefold()
            if any(
                term in name for term in ("celery", "rq", "bull", "sidekiq", "hangfire")
            ):
                runtime_markers["background_worker"] += 1
            if any(
                term in name
                for term in (
                    "fastapi",
                    "flask",
                    "django",
                    "express",
                    "aspnet",
                    "spring",
                )
            ):
                runtime_markers["web_service"] += 1
            if any(term in name for term in ("cron", "schedule", "apscheduler")):
                runtime_markers["scheduler"] += 1
    return {
        "schema_version": SCHEMA_VERSION,
        "services": sorted(services, key=lambda item: str(item.get("id"))),
        "entrypoints": sorted(
            entrypoints,
            key=lambda item: (str(item.get("source")), str(item.get("name"))),
        ),
        "ci_pipelines": sorted(pipelines, key=lambda item: str(item.get("source"))),
        "runtime_markers": dict(sorted(runtime_markers.items())),
        "limitations": [
            "Runtime topology is static and must be reconciled with deployed evidence for production claims."
        ],
    }


def _data_flow_map(
    facts: Sequence[Mapping[str, object]], routes: Sequence[Mapping[str, object]]
) -> dict[str, object]:
    flows = [dict(item) for fact in facts for item in fact.get("data_flows", ())]  # type: ignore[union-attr]
    for route in routes:
        flows.append(
            {
                "file": route.get("file"),
                "line": route.get("line"),
                "caller": route.get("handler"),
                "operation": "request_handler",
                "source": "external_request",
                "sink": "application_handler",
                "confidence": 0.9,
                "basis": "route_declaration",
            }
        )
    boundaries = []
    for flow in flows:
        if flow.get("source") in {
            "external_http",
            "external_request",
            "queue_or_event_bus",
            "configuration",
        } or flow.get("sink") in {
            "external_http",
            "queue_or_event_bus",
            "process_boundary",
        }:
            boundaries.append(
                {
                    "file": flow.get("file"),
                    "line": flow.get("line"),
                    "source": flow.get("source"),
                    "sink": flow.get("sink"),
                    "basis": flow.get("basis"),
                }
            )
    return {
        "schema_version": SCHEMA_VERSION,
        "flows": sorted(
            flows,
            key=lambda item: (
                str(item.get("file")),
                int(item.get("line") or 0),
                str(item.get("operation")),
            ),
        ),
        "trust_boundary_candidates": sorted(
            boundaries,
            key=lambda item: (str(item.get("file")), int(item.get("line") or 0)),
        ),
        "limitations": [
            "Static data-flow records are hypotheses; dynamic dispatch, reflection, generated SQL, and runtime routing remain unresolved without execution evidence."
        ],
    }


def _integration_map(facts: Sequence[Mapping[str, object]]) -> dict[str, object]:
    packages: dict[tuple[str, str], dict[str, object]] = {}
    endpoints: dict[str, dict[str, object]] = {}
    for fact in facts:
        path = str(fact["path"])
        for dep in fact.get("dependencies", ()):  # type: ignore[union-attr]
            key = (str(dep.get("ecosystem", "unknown")), str(dep.get("name", "")))
            packages.setdefault(
                key,
                {
                    "name": key[1],
                    "ecosystem": key[0],
                    "sources": [],
                    "scopes": set(),
                    "category": None,
                },
            )
            packages[key]["sources"].append(path)  # type: ignore[union-attr]
            packages[key]["scopes"].add(str(dep.get("scope", "unknown")))  # type: ignore[union-attr]
        for imp in fact.get("imports", ()):  # type: ignore[union-attr]
            specifier = str(imp.get("module") or imp.get("specifier") or "")
            normalized = specifier.casefold()
            for hint, category in INTEGRATION_HINTS.items():
                if (
                    normalized == hint
                    or normalized.startswith(hint + ".")
                    or normalized.startswith(hint + "/")
                ):
                    key = (str(fact.get("language", "unknown")), hint)
                    packages.setdefault(
                        key,
                        {
                            "name": hint,
                            "ecosystem": str(fact.get("language", "unknown")),
                            "sources": [],
                            "scopes": set(),
                            "category": category,
                        },
                    )
                    packages[key]["sources"].append(path)  # type: ignore[union-attr]
        for domain in fact.get("urls", ()):  # type: ignore[union-attr]
            endpoints.setdefault(str(domain), {"origin": domain, "sources": []})[
                "sources"
            ].append(path)  # type: ignore[index]
    records = []
    for item in packages.values():
        item["sources"] = sorted(set(item["sources"]))
        item["scopes"] = sorted(item["scopes"])
        if item.get("category") is None:
            normalized = str(item["name"]).casefold()
            item["category"] = next(
                (
                    category
                    for hint, category in INTEGRATION_HINTS.items()
                    if hint in normalized
                ),
                "external_package",
            )
        records.append(item)
    return {
        "schema_version": SCHEMA_VERSION,
        "packages": sorted(
            records, key=lambda item: (str(item["ecosystem"]), str(item["name"]))
        ),
        "network_origins": sorted(
            (
                {**item, "sources": sorted(set(item["sources"]))}
                for item in endpoints.values()
            ),
            key=lambda item: str(item["origin"]),
        ),
        "redaction_policy": "Only package names, origin-level URLs, configuration key names, and structural evidence are stored; values, credentials, query strings, and request bodies are excluded.",
    }


def _configuration_map(facts: Sequence[Mapping[str, object]]) -> dict[str, object]:
    keys: dict[str, dict[str, object]] = {}
    files = []
    for fact in facts:
        if fact.get("role") == "configuration":
            files.append(
                {
                    "path": fact["path"],
                    "language": fact["language"],
                    "sha256": fact["sha256"],
                }
            )
        for ref in fact.get("config_refs", ()):  # type: ignore[union-attr]
            key = str(ref.get("key", ""))
            if not key:
                continue
            record = keys.setdefault(
                key,
                {
                    "key": key,
                    "sensitive": bool(SENSITIVE_KEY.search(key)),
                    "references": [],
                },
            )
            record["sensitive"] = bool(record["sensitive"] or ref.get("sensitive"))
            record["references"].append(
                {
                    "path": ref.get("path"),
                    "line": ref.get("line"),
                    "access": ref.get("access"),
                }
            )
    return {
        "schema_version": SCHEMA_VERSION,
        "configuration_files": sorted(files, key=lambda item: str(item["path"])),
        "keys": sorted(
            (
                {
                    **item,
                    "references": sorted(
                        item["references"],
                        key=lambda value: (
                            str(value.get("path")),
                            int(value.get("line") or 0),
                        ),
                    ),
                }
                for item in keys.values()
            ),
            key=lambda item: str(item["key"]),
        ),
        "value_storage": "prohibited",
        "precedence": "unknown unless explicitly declared by an executable configuration resolver",
    }


def _ownership_map(facts: Sequence[Mapping[str, object]]) -> dict[str, object]:
    rules = [dict(item) for fact in facts for item in fact.get("ownership", ())]  # type: ignore[union-attr]
    assignments = []
    unowned = []
    for fact in facts:
        path = str(fact["path"])
        matched: list[str] = []
        for rule in rules:
            pattern = str(rule.get("pattern", ""))
            normalized = pattern.lstrip("/")
            if fnmatch.fnmatch(path, normalized) or fnmatch.fnmatch(
                "/" + path, pattern
            ):
                matched = [str(owner) for owner in rule.get("owners", ())]
        if matched:
            assignments.append({"path": path, "owners": matched, "basis": "codeowners"})
        elif fact.get("role") in {
            "source",
            "test",
            "contract",
            "configuration",
            "build_or_runtime",
        }:
            unowned.append(path)
    candidates = [
        str(fact["path"])
        for fact in facts
        if Path(str(fact["path"])).name.casefold()
        in {"agents.md", "architecture.md", "maintainers", "owners", "codeowners"}
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "rules": sorted(
            rules,
            key=lambda item: (str(item.get("source")), int(item.get("line") or 0)),
        ),
        "assignments": assignments,
        "unowned_material_files": sorted(unowned),
        "owner_document_candidates": sorted(candidates),
        "limitations": [
            "No owner is inferred from directory names or commit history without explicit evidence."
        ],
    }


def _contract_map(facts: Sequence[Mapping[str, object]]) -> dict[str, object]:
    contracts = [dict(item) for fact in facts for item in fact.get("contracts", ())]  # type: ignore[union-attr]
    seen: set[str] = set()
    unique = []
    for item in sorted(contracts, key=lambda value: str(value.get("id"))):
        identifier = str(item.get("id"))
        if identifier and identifier not in seen:
            seen.add(identifier)
            unique.append(item)
    return {
        "schema_version": SCHEMA_VERSION,
        "contracts": unique,
        "count": len(unique),
        "limitations": [
            "Schema compatibility and runtime conformance require language-specific validators or generated-client tests."
        ],
    }


def _test_coverage_map(
    facts: Sequence[Mapping[str, object]], dependency_graph: Mapping[str, object]
) -> dict[str, object]:
    test_files = {str(fact["path"]) for fact in facts if fact.get("role") == "test"}
    source_files = {
        str(fact["path"])
        for fact in facts
        if fact.get("role") == "source" and not fact.get("generated")
    }
    links: set[tuple[str, str, str]] = set()
    for edge in dependency_graph.get("edges", ()):
        source = str(edge.get("from", "")).removeprefix("file:")
        target = str(edge.get("to", "")).removeprefix("file:")
        if (
            source in test_files
            and target in source_files
            and edge.get("kind") == "imports"
        ):
            links.add((source, target, "test_import"))
    for test in test_files:
        stem = (
            Path(test)
            .stem.casefold()
            .removeprefix("test_")
            .removesuffix("_test")
            .removesuffix(".test")
            .removesuffix(".spec")
        )
        if len(stem) < 3:
            continue
        for source in source_files:
            if stem == Path(source).stem.casefold() or stem in source.casefold():
                links.add((test, source, "name_proximity"))
    linked_sources = {source for _, source, _ in links}
    linked_tests = {test for test, _, _ in links}
    return {
        "schema_version": SCHEMA_VERSION,
        "coverage_kind": "static_traceability_not_execution_coverage",
        "test_files": sorted(test_files),
        "source_files": sorted(source_files),
        "links": [
            {"test": test, "source": source, "basis": basis}
            for test, source, basis in sorted(links)
        ],
        "untested_source_candidates": sorted(source_files - linked_sources),
        "unmapped_test_files": sorted(test_files - linked_tests),
    }


def _architecture_graph(
    facts: Sequence[Mapping[str, object]],
    dependency_graph: Mapping[str, object],
    runtime: Mapping[str, object],
    contract_map: Mapping[str, object],
    integration_map: Mapping[str, object],
    routes: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    nodes: dict[str, dict[str, object]] = {
        "project": {"id": "project", "kind": "project", "name": "project"}
    }
    edges: list[dict[str, object]] = []
    for fact in facts:
        node_id = f"file:{fact['path']}"
        nodes[node_id] = {
            "id": node_id,
            "kind": "file",
            "path": fact["path"],
            "language": fact["language"],
            "role": fact["role"],
        }
        edges.append({"from": "project", "to": node_id, "kind": "contains"})
    for edge in dependency_graph.get("edges", ()):
        nodes.setdefault(
            str(edge["to"]),
            next(
                (
                    node
                    for node in dependency_graph.get("nodes", ())
                    if node.get("id") == edge["to"]
                ),
                {"id": edge["to"], "kind": "unknown"},
            ),
        )
        edges.append({"from": edge["from"], "to": edge["to"], "kind": edge["kind"]})
    for service in runtime.get("services", ()):
        node_id = str(service["id"])
        nodes[node_id] = {
            "id": node_id,
            "kind": "service",
            "name": service.get("name"),
            "image": service.get("image"),
        }
        edges.append({"from": "project", "to": node_id, "kind": "runs"})
    for route in routes:
        node_id = str(route["id"])
        nodes[node_id] = {
            "id": node_id,
            "kind": "route",
            "path": route.get("path"),
            "methods": route.get("methods"),
        }
        edges.append(
            {"from": f"file:{route['file']}", "to": node_id, "kind": "declares_route"}
        )
    for contract in contract_map.get("contracts", ()):
        node_id = f"contract:{contract['id']}"
        nodes[node_id] = {
            "id": node_id,
            "kind": "contract",
            "name": contract.get("name"),
            "contract_kind": contract.get("kind"),
        }
        edges.append(
            {
                "from": f"file:{contract['path']}",
                "to": node_id,
                "kind": "defines_contract",
            }
        )
    for package in integration_map.get("packages", ()):
        node_id = f"integration:{package['ecosystem']}:{package['name']}"
        nodes[node_id] = {
            "id": node_id,
            "kind": "integration",
            "name": package["name"],
            "category": package.get("category"),
        }
        for source in package.get("sources", ()):
            edges.append(
                {"from": f"file:{source}", "to": node_id, "kind": "uses_integration"}
            )
    return {
        "schema_version": SCHEMA_VERSION,
        "nodes": sorted(nodes.values(), key=lambda item: str(item["id"])),
        "edges": sorted(
            edges,
            key=lambda item: (str(item["from"]), str(item["to"]), str(item["kind"])),
        ),
    }


def _traceability_map(
    facts: Sequence[Mapping[str, object]],
    routes: Sequence[Mapping[str, object]],
    contract_map: Mapping[str, object],
    tests: Mapping[str, object],
    dependency_graph: Mapping[str, object],
) -> dict[str, object]:
    test_links: dict[str, list[str]] = defaultdict(list)
    for link in tests.get("links", ()):
        test_links[str(link["source"])].append(str(link["test"]))
    records = []
    for fact in facts:
        path = str(fact["path"])
        if fact.get("role") in {
            "source",
            "contract",
            "build_or_runtime",
            "configuration",
        }:
            records.append(
                {
                    "subject": f"file:{path}",
                    "implementation": path,
                    "tests": sorted(set(test_links.get(path, ()))),
                    "contracts": [item.get("id") for item in fact.get("contracts", ())],
                    "routes": [item.get("id") for item in fact.get("routes", ())],
                    "evidence": [{"kind": "content_hash", "sha256": fact["sha256"]}],
                }
            )
    return {
        "schema_version": SCHEMA_VERSION,
        "records": records,
        "unresolved_import_count": len(dependency_graph.get("unresolved", ())),
        "limitations": [
            "Requirement-to-code links require explicit requirement identifiers in source, issue, or specification artifacts."
        ],
    }


def _risk_gap_map(
    facts: Sequence[Mapping[str, object]],
    dependency_graph: Mapping[str, object],
    ownership: Mapping[str, object],
    tests: Mapping[str, object],
    configuration: Mapping[str, object],
) -> dict[str, object]:
    findings: list[dict[str, object]] = []
    parse_errors = [
        {"path": fact["path"], **error}
        for fact in facts
        for error in fact.get("parse_errors", ())
    ]
    if parse_errors:
        findings.append(
            {
                "id": "parse-errors",
                "severity": "medium",
                "summary": f"{len(parse_errors)} parser errors or unsupported structures",
                "evidence": parse_errors[:100],
            }
        )
    unresolved = list(dependency_graph.get("unresolved", ()))
    if unresolved:
        findings.append(
            {
                "id": "unresolved-imports",
                "severity": "medium",
                "summary": f"{len(unresolved)} imports or service dependencies could not be resolved statically",
                "evidence": unresolved[:100],
            }
        )
    truncated = [str(fact["path"]) for fact in facts if fact.get("text_truncated")]
    if truncated:
        findings.append(
            {
                "id": "truncated-text-scans",
                "severity": "low",
                "summary": f"{len(truncated)} files exceeded the per-file text scan ceiling",
                "evidence": truncated[:100],
            }
        )
    unowned = list(ownership.get("unowned_material_files", ()))
    if unowned:
        findings.append(
            {
                "id": "unowned-files",
                "severity": "medium",
                "summary": f"{len(unowned)} material files lack explicit ownership",
                "evidence": unowned[:100],
            }
        )
    untested = list(tests.get("untested_source_candidates", ()))
    if untested:
        findings.append(
            {
                "id": "untested-source-candidates",
                "severity": "medium",
                "summary": f"{len(untested)} source files have no static test link",
                "evidence": untested[:100],
            }
        )
    sensitive = [
        item["key"] for item in configuration.get("keys", ()) if item.get("sensitive")
    ]
    if sensitive:
        findings.append(
            {
                "id": "sensitive-config-keys",
                "severity": "informational",
                "summary": f"{len(sensitive)} sensitive-looking configuration keys are referenced; values were not captured",
                "evidence": sensitive[:100],
            }
        )
    generated = [str(fact["path"]) for fact in facts if fact.get("generated")]
    if generated:
        findings.append(
            {
                "id": "generated-surfaces",
                "severity": "informational",
                "summary": f"{len(generated)} generated or vendor-like files were mapped",
                "evidence": generated[:100],
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "finding_count": len(findings),
        "findings": findings,
        "unknowns": [
            "Dynamic runtime paths, reflection, plugin loading, external consumers, deployed configuration values, and production traffic are not proven by static mapping."
        ],
        "completion_rule": "A complete static map may still contain explicit unknowns; unknowns must not be silently converted into facts.",
    }


def _tokenize(*values: object) -> list[str]:
    tokens: list[str] = []
    for value in values:
        if value is None:
            continue
        if isinstance(value, (list, tuple, set)):
            tokens.extend(_tokenize(*value))
            continue
        text = str(value).casefold().replace("_", "-")
        tokens.extend(TOKEN_RE.findall(text))
        for token in list(tokens[-100:]):
            if "/" in token:
                tokens.extend(part for part in token.split("/") if len(part) > 1)
            if "-" in token:
                tokens.extend(part for part in token.split("-") if len(part) > 1)
            if "." in token:
                tokens.extend(part for part in token.split(".") if len(part) > 1)
    return [token for token in tokens if len(token) > 1]


def _doc_id(kind: str, *parts: object) -> str:
    payload = ":".join(str(part) for part in parts)
    return f"{kind}:{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:20]}"


def _retrieval_index(
    facts: Sequence[Mapping[str, object]],
    dependency_graph: Mapping[str, object],
    architecture: Mapping[str, object],
    runtime: Mapping[str, object],
    integration: Mapping[str, object],
    configuration: Mapping[str, object],
    contracts: Mapping[str, object],
    risks: Mapping[str, object],
    routes: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    docs: list[dict[str, object]] = []
    relation_map: dict[str, set[str]] = defaultdict(set)
    file_doc: dict[str, str] = {}
    for fact in facts:
        path = str(fact["path"])
        identifier = _doc_id("file", path)
        file_doc[path] = identifier
        symbol_names = [str(item.get("qualname")) for item in fact.get("symbols", ())][
            :100
        ]
        import_names = [
            str(item.get("module") or item.get("specifier") or "")
            for item in fact.get("imports", ())
        ][:100]
        docs.append(
            {
                "id": identifier,
                "kind": "file",
                "title": path,
                "path": path,
                "language": fact["language"],
                "role": fact["role"],
                "line_start": 1,
                "line_end": fact.get("line_count"),
                "summary": f"{fact['role']} {fact['language']} file; symbols: {', '.join(symbol_names[:12]) or 'none'}; imports: {', '.join(import_names[:12]) or 'none'}",
                "relations": [],
            }
        )
        for symbol in fact.get("symbols", ()):
            sid = _doc_id(
                "symbol", path, symbol.get("qualname"), symbol.get("line_start")
            )
            docs.append(
                {
                    "id": sid,
                    "kind": "symbol",
                    "title": str(symbol.get("qualname")),
                    "path": path,
                    "language": fact["language"],
                    "role": fact["role"],
                    "line_start": symbol.get("line_start"),
                    "line_end": symbol.get("line_end"),
                    "summary": f"{symbol.get('kind')} {symbol.get('qualname')} defined in {path}",
                    "relations": [identifier],
                }
            )
            relation_map[identifier].add(sid)
            relation_map[sid].add(identifier)
    for route in routes:
        rid = _doc_id("route", route.get("id"))
        path = str(route.get("file"))
        parent = file_doc.get(path)
        docs.append(
            {
                "id": rid,
                "kind": "route",
                "title": f"{'/'.join(route.get('methods', ()))} {route.get('path')}",
                "path": path,
                "language": None,
                "role": "api",
                "line_start": route.get("line"),
                "line_end": route.get("line"),
                "summary": f"API route handled by {route.get('handler') or 'unresolved handler'} in {path}",
                "relations": [parent] if parent else [],
            }
        )
        if parent:
            relation_map[parent].add(rid)
            relation_map[rid].add(parent)
    for service in runtime.get("services", ()):
        sid = _doc_id("service", service.get("id"))
        source = str(service.get("source", ""))
        parent = file_doc.get(source)
        docs.append(
            {
                "id": sid,
                "kind": "service",
                "title": str(service.get("name")),
                "path": source,
                "language": "compose",
                "role": "runtime",
                "line_start": service.get("line"),
                "line_end": service.get("line"),
                "summary": f"Runtime service image={service.get('image')} build={service.get('build')} depends_on={service.get('depends_on')}",
                "relations": [parent] if parent else [],
            }
        )
        if parent:
            relation_map[parent].add(sid)
            relation_map[sid].add(parent)
    for contract in contracts.get("contracts", ()):
        cid = _doc_id("contract", contract.get("id"))
        path = str(contract.get("path", ""))
        parent = file_doc.get(path)
        docs.append(
            {
                "id": cid,
                "kind": "contract",
                "title": str(contract.get("name")),
                "path": path,
                "language": None,
                "role": "contract",
                "line_start": contract.get("line"),
                "line_end": contract.get("line"),
                "summary": f"{contract.get('kind')} contract declared in {path}",
                "relations": [parent] if parent else [],
            }
        )
        if parent:
            relation_map[parent].add(cid)
            relation_map[cid].add(parent)
    for item in configuration.get("keys", ()):
        refs = item.get("references", ())
        first = refs[0] if refs else {}
        cid = _doc_id("config", item.get("key"))
        related = sorted(
            {
                file_doc.get(str(ref.get("path")))
                for ref in refs
                if file_doc.get(str(ref.get("path")))
            }
        )
        docs.append(
            {
                "id": cid,
                "kind": "configuration",
                "title": str(item.get("key")),
                "path": first.get("path"),
                "language": None,
                "role": "configuration",
                "line_start": first.get("line"),
                "line_end": first.get("line"),
                "summary": f"Configuration key referenced {len(refs)} time(s); sensitive={item.get('sensitive')}",
                "relations": related,
            }
        )
        for parent in related:
            relation_map[parent].add(cid)
            relation_map[cid].add(parent)
    for package in integration.get("packages", ()):
        iid = _doc_id("integration", package.get("ecosystem"), package.get("name"))
        related = sorted(
            {
                file_doc.get(str(path))
                for path in package.get("sources", ())
                if file_doc.get(str(path))
            }
        )
        docs.append(
            {
                "id": iid,
                "kind": "integration",
                "title": str(package.get("name")),
                "path": package.get("sources", [None])[0]
                if package.get("sources")
                else None,
                "language": package.get("ecosystem"),
                "role": "integration",
                "line_start": None,
                "line_end": None,
                "summary": f"{package.get('category')} integration used by {len(package.get('sources', ()))} file(s)",
                "relations": related,
            }
        )
        for parent in related:
            relation_map[parent].add(iid)
            relation_map[iid].add(parent)
    for finding in risks.get("findings", ()):
        rid = _doc_id("risk", finding.get("id"))
        docs.append(
            {
                "id": rid,
                "kind": "risk",
                "title": str(finding.get("id")),
                "path": None,
                "language": None,
                "role": "risk",
                "line_start": None,
                "line_end": None,
                "summary": str(finding.get("summary")),
                "relations": [],
            }
        )
    by_id = {str(doc["id"]): doc for doc in docs}
    for identifier, relations in relation_map.items():
        if identifier in by_id:
            by_id[identifier]["relations"] = sorted(
                set((*by_id[identifier].get("relations", ()), *relations))
            )
    docs = sorted(by_id.values(), key=lambda item: str(item["id"]))
    postings: dict[str, list[list[int]]] = defaultdict(list)
    lengths: list[int] = []
    for index, doc in enumerate(docs):
        terms = _tokenize(
            doc.get("title"),
            doc.get("path"),
            doc.get("language"),
            doc.get("role"),
            doc.get("summary"),
        )
        frequencies = Counter(terms)
        lengths.append(sum(frequencies.values()))
        for token, frequency in sorted(frequencies.items()):
            postings[token].append([index, frequency])
    count = len(docs)
    idf = {
        token: math.log(1 + (count - len(values) + 0.5) / (len(values) + 0.5))
        for token, values in postings.items()
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "algorithm": "bm25_metadata_plus_relation_expansion",
        "document_count": count,
        "average_document_length": (sum(lengths) / count if count else 0.0),
        "document_lengths": lengths,
        "documents": docs,
        "postings": dict(sorted(postings.items())),
        "idf": dict(sorted(idf.items())),
        "query_aliases": QUERY_ALIASES,
        "loading_rule": "metadata_first_then_targeted_source_hydration",
    }


def _summary_markdown(
    manifest: Mapping[str, object],
    risk_map: Mapping[str, object],
    runtime: Mapping[str, object],
) -> str:
    counts = manifest.get("counts", {})
    lines = [
        "# Project Intelligence Map",
        "",
        f"Map revision: `{manifest.get('map_revision')}`",
        f"Source inventory: `{manifest.get('source_inventory_sha256')}`",
        "",
        "## Coverage",
        "",
        f"- Files: {counts.get('files', 0)}",
        f"- Symbols: {counts.get('symbols', 0)}",
        f"- Dependency edges: {counts.get('dependency_edges', 0)}",
        f"- Routes: {counts.get('routes', 0)}",
        f"- Runtime services: {counts.get('services', 0)}",
        f"- Contracts: {counts.get('contracts', 0)}",
        f"- Configuration keys: {counts.get('configuration_keys', 0)}",
        f"- Retrieval documents: {counts.get('retrieval_documents', 0)}",
        "",
        "## Runtime markers",
        "",
    ]
    markers = runtime.get("runtime_markers", {})
    if markers:
        lines.extend(f"- {key}: {value}" for key, value in markers.items())
    else:
        lines.append("- No runtime category was proven from static manifests.")
    lines.extend(["", "## Risks and unknowns", ""])
    for finding in risk_map.get("findings", ()):
        lines.append(
            f"- **{finding.get('severity')} — {finding.get('id')}**: {finding.get('summary')}"
        )
    for unknown in risk_map.get("unknowns", ()):
        lines.append(f"- Unknown: {unknown}")
    lines.extend(
        [
            "",
            "## Retrieval",
            "",
            "Use `engineering-bootstrap project-map query --project <path> --query <goal>` to retrieve map records and a minimal source hydration plan.",
            "",
        ]
    )
    return "\n".join(lines)


def _inventory_digest(records: Sequence[Mapping[str, object]]) -> str:
    projection = [
        {
            "path": item["path"],
            "size_bytes": item["size_bytes"],
            "sha256": item["sha256"],
        }
        for item in records
    ]
    return _stable_hash(projection)


def _map_dir(path: Path) -> Path:
    resolved = path.resolve()
    if (resolved / "project-manifest.json").is_file():
        return resolved
    candidate = resolved / ".engineering-bootstrap" / "project-map"
    if candidate.is_dir():
        return candidate
    raise ValueError(f"project intelligence map not found under {resolved}")


def build_project_map(
    project: Path,
    *,
    output_dir: Path | None = None,
    max_files: int = 100_000,
    max_depth: int = 96,
    max_bytes: int = 2 * 1024 * 1024 * 1024,
    max_text_bytes: int = 2 * 1024 * 1024,
    incremental: bool = True,
    archive_previous: bool = True,
) -> dict[str, object]:
    """Build and atomically promote a complete static project intelligence map."""
    root = project.resolve()
    if not root.is_dir():
        raise ValueError("project must be a directory")
    if min(max_files, max_depth, max_bytes, max_text_bytes) < 1:
        raise ValueError("mapping limits must be positive")
    output = (output_dir or (root / ".engineering-bootstrap" / "project-map")).resolve()
    if (
        output == root
        or root in output.parents
        and ".engineering-bootstrap" not in output.parts
    ):
        raise ValueError("output directory must not replace the project root")
    control = output.parent
    control.mkdir(parents=True, exist_ok=True)
    lock = control / f".{output.name}.lock"
    run_id = uuid.uuid4().hex
    lock_record = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "project": root.as_posix(),
        "output": output.as_posix(),
        "created_utc": _now(),
        "pid": os.getpid(),
    }
    try:
        with lock.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(lock_record, stream, indent=2)
            stream.write("\n")
    except FileExistsError as error:
        raise RuntimeError(f"project map lock already exists: {lock}") from error
    stage_root = control / f".{output.name}.staging" / run_id
    try:
        exclusion_counts: Counter[str] = Counter()

        def exclude_source(relative: str) -> bool:
            category = _exclusion_category(relative)
            if category is not None:
                exclusion_counts[category] += 1
                return True
            return False

        walk = bounded_walk(
            root,
            limits=WalkLimits(
                max_files=max_files, max_depth=max_depth, max_bytes=max_bytes
            ),
            symlink_policy="reject",
            exclude=exclude_source,
        )
        previous: dict[str, dict[str, Any]] = {}
        previous_facts = output / "file-facts.jsonl"
        if incremental and previous_facts.is_file():
            previous = {
                str(item.get("path")): item for item in _load_jsonl(previous_facts)
            }
        inventory: list[dict[str, object]] = []
        facts: list[dict[str, object]] = []
        reused = rescanned = 0
        for entry in walk.files:
            digest = _sha_file(entry.path)
            inventory.append(
                {
                    "path": entry.relative,
                    "size_bytes": entry.size or 0,
                    "sha256": digest,
                    "language": _language(entry.path),
                    "role": _role(entry.relative, _language(entry.path)),
                }
            )
            prior = previous.get(entry.relative)
            if (
                prior
                and prior.get("sha256") == digest
                and prior.get("adapter_version") == ADAPTER_VERSION
            ):
                facts.append(prior)
                reused += 1
            else:
                facts.append(_scan_file(entry.path, root, digest, max_text_bytes))
                rescanned += 1
        inventory.sort(key=lambda item: str(item["path"]))
        facts.sort(key=lambda item: str(item["path"]))
        routes = [dict(item) for fact in facts for item in fact.get("routes", ())]
        symbols = [
            {"path": fact["path"], "language": fact["language"], **dict(item)}
            for fact in facts
            for item in fact.get("symbols", ())
        ]
        dependency = _dependency_graph(facts)
        call_graph = _call_graph(facts, dependency)
        runtime = _runtime_topology(facts)
        data_flow = _data_flow_map(facts, routes)
        integration = _integration_map(facts)
        configuration = _configuration_map(facts)
        ownership = _ownership_map(facts)
        contracts = _contract_map(facts)
        tests = _test_coverage_map(facts, dependency)
        architecture = _architecture_graph(
            facts, dependency, runtime, contracts, integration, routes
        )
        traceability = _traceability_map(facts, routes, contracts, tests, dependency)
        risks = _risk_gap_map(facts, dependency, ownership, tests, configuration)
        retrieval = _retrieval_index(
            facts,
            dependency,
            architecture,
            runtime,
            integration,
            configuration,
            contracts,
            risks,
            routes,
        )
        inventory_sha = _inventory_digest(inventory)
        counts = {
            "files": len(inventory),
            "symbols": len(symbols),
            "dependency_edges": len(dependency["edges"]),
            "call_edges": len(call_graph["edges"]),
            "routes": len(routes),
            "services": len(runtime["services"]),
            "data_flows": len(data_flow["flows"]),
            "integrations": len(integration["packages"]),
            "configuration_keys": len(configuration["keys"]),
            "contracts": len(contracts["contracts"]),
            "test_links": len(tests["links"]),
            "architecture_nodes": len(architecture["nodes"]),
            "architecture_edges": len(architecture["edges"]),
            "retrieval_documents": retrieval["document_count"],
            "risks": risks["finding_count"],
        }
        build_stats = {"reused_file_facts": reused, "rescanned_file_facts": rescanned}
        revision_payload = {
            "mapper_version": MAPPER_VERSION,
            "adapter_version": ADAPTER_VERSION,
            "source_inventory_sha256": inventory_sha,
            "counts": counts,
            "dependency_revision": _stable_hash(dependency),
            "architecture_revision": _stable_hash(architecture),
            "retrieval_revision": _stable_hash(
                {"documents": retrieval["documents"], "postings": retrieval["postings"]}
            ),
            "exclusion_policy": {
                "default_parts": sorted(DEFAULT_EXCLUDES),
                "sensitive_names": sorted(SENSITIVE_FILE_NAMES),
                "sensitive_suffixes": sorted(SENSITIVE_FILE_SUFFIXES),
            },
        }
        map_revision = _stable_hash(revision_payload)
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "mapper_version": MAPPER_VERSION,
            "adapter_version": ADAPTER_VERSION,
            "project_name": root.name,
            "project_root": root.as_posix(),
            "map_revision": map_revision,
            "source_inventory_sha256": inventory_sha,
            "counts": counts,
            "limits": {
                "max_files": max_files,
                "max_depth": max_depth,
                "max_bytes": max_bytes,
                "max_text_bytes": max_text_bytes,
            },
            "incremental": incremental,
            "build_stats": build_stats,
            "source_excludes": sorted(DEFAULT_EXCLUDES),
            "sensitive_source_excludes": {
                "names": sorted(SENSITIVE_FILE_NAMES),
                "suffixes": sorted(SENSITIVE_FILE_SUFFIXES),
                "directory_names": [".credentials", ".secrets"],
            },
            "exclusion_counts": dict(sorted(exclusion_counts.items())),
            "map_files": [
                name for name in REQUIRED_MAP_FILES if name != "map-receipt.json"
            ],
        }
        stage_root.mkdir(parents=True, exist_ok=False)
        _write_json(stage_root / "project-manifest.json", manifest)
        _write_jsonl(stage_root / "file-inventory.jsonl", inventory)
        _write_jsonl(stage_root / "file-facts.jsonl", facts)
        _write_jsonl(
            stage_root / "symbol-index.jsonl",
            sorted(
                symbols,
                key=lambda item: (
                    str(item["path"]),
                    int(item.get("line_start") or 0),
                    str(item.get("qualname")),
                ),
            ),
        )
        for name, value in (
            ("dependency-graph.json", dependency),
            ("call-graph.json", call_graph),
            ("architecture-graph.json", architecture),
            ("runtime-topology.json", runtime),
            ("data-flow-map.json", data_flow),
            ("integration-map.json", integration),
            ("configuration-map.json", configuration),
            ("ownership-map.json", ownership),
            ("contract-map.json", contracts),
            ("test-coverage-map.json", tests),
            ("traceability-map.json", traceability),
            ("risk-and-gap-map.json", risks),
            ("retrieval-index.json", retrieval),
        ):
            _write_json(stage_root / name, value)
        (stage_root / "map-summary.md").write_text(
            _summary_markdown(manifest, risks, runtime), encoding="utf-8", newline="\n"
        )
        hashes = {
            path.name: _sha_file(path)
            for path in sorted(stage_root.iterdir(), key=lambda item: item.name)
            if path.is_file()
        }
        receipt_payload = {
            "schema_version": SCHEMA_VERSION,
            "map_revision": map_revision,
            "source_inventory_sha256": inventory_sha,
            "file_sha256": hashes,
            "created_utc": _now(),
            "run_id": run_id,
            "promotion": "prepared",
            "exclusion_counts": dict(sorted(exclusion_counts.items())),
        }
        receipt_payload["receipt_payload_sha256"] = _stable_hash(receipt_payload)
        _write_json(stage_root / "map-receipt.json", receipt_payload)
        staged_validation = validate_project_map(stage_root, check_freshness=False)
        if not staged_validation["valid"]:
            raise RuntimeError(
                f"staged project map validation failed: {staged_validation['errors']}"
            )
        archived = None
        if output.exists():
            if not archive_previous:
                raise FileExistsError(
                    f"project map already exists and archive_previous is false: {output}"
                )
            old_manifest = (
                _load_json(output / "project-manifest.json")
                if (output / "project-manifest.json").is_file()
                else {}
            )
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            history = control / f"{output.name}-history"
            history.mkdir(parents=True, exist_ok=True)
            archived = (
                history
                / f"{stamp}-{str(old_manifest.get('map_revision', 'unknown'))[:16]}"
            )
            os.replace(output, archived)
        output.parent.mkdir(parents=True, exist_ok=True)
        os.replace(stage_root, output)
        final_receipt = _load_json(output / "map-receipt.json")
        final_receipt["promotion"] = "promoted"
        final_receipt["promoted_utc"] = _now()
        final_receipt["archived_previous"] = archived.as_posix() if archived else None
        final_receipt["receipt_sha256"] = _stable_hash(final_receipt)
        _write_json(output / "map-receipt.json", final_receipt)
        return {
            "valid": True,
            "project": root.as_posix(),
            "map_dir": output.as_posix(),
            "map_revision": map_revision,
            "source_inventory_sha256": inventory_sha,
            "counts": counts,
            "archived_previous": archived.as_posix() if archived else None,
            "incremental_reuse": {"reused": reused, "rescanned": rescanned},
            "receipt": (output / "map-receipt.json").as_posix(),
        }
    except Exception:
        failure = control / f"{output.name}-failed-runs" / run_id
        failure.parent.mkdir(parents=True, exist_ok=True)
        if stage_root.exists():
            os.replace(stage_root, failure)
        raise
    finally:
        if lock.exists():
            history = control / f"{output.name}-lock-history"
            history.mkdir(parents=True, exist_ok=True)
            destination = history / f"{run_id}.json"
            try:
                os.replace(lock, destination)
            except OSError:
                # Preserve the lock in place for recoverable operator review. A
                # failed custody move must never become permission to delete it.
                pass


def validate_project_map(
    project_or_map: Path, *, check_freshness: bool = False
) -> dict[str, object]:
    errors: list[str] = []
    warnings: list[str] = []
    try:
        map_dir = _map_dir(project_or_map)
    except ValueError as error:
        return {"valid": False, "errors": [str(error)], "warnings": []}
    for name in REQUIRED_MAP_FILES:
        if not (map_dir / name).is_file():
            errors.append(f"missing map file: {name}")
    if errors:
        return {
            "valid": False,
            "map_dir": map_dir.as_posix(),
            "errors": errors,
            "warnings": warnings,
        }
    try:
        manifest = _load_json(map_dir / "project-manifest.json")
        receipt = _load_json(map_dir / "map-receipt.json")
        inventory = _load_jsonl(map_dir / "file-inventory.jsonl")
        facts = _load_jsonl(map_dir / "file-facts.jsonl")
        symbols = _load_jsonl(map_dir / "symbol-index.jsonl")
        retrieval = _load_json(map_dir / "retrieval-index.json")
        configuration = _load_json(map_dir / "configuration-map.json")
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return {
            "valid": False,
            "map_dir": map_dir.as_posix(),
            "errors": [f"map parse failure: {error}"],
            "warnings": warnings,
        }
    for name, expected in receipt.get("file_sha256", {}).items():
        path = map_dir / name
        if not path.is_file() or _sha_file(path) != expected:
            errors.append(f"map file hash mismatch: {name}")
    inventory_sha = _inventory_digest(inventory)
    if inventory_sha != manifest.get("source_inventory_sha256"):
        errors.append("source inventory digest does not match manifest")
    if receipt.get("map_revision") != manifest.get("map_revision"):
        errors.append("receipt map revision does not match manifest")
    if len(inventory) != manifest.get("counts", {}).get("files"):
        errors.append("file count does not match manifest")
    if len(symbols) != manifest.get("counts", {}).get("symbols"):
        errors.append("symbol count does not match manifest")
    fact_paths = {str(item.get("path")) for item in facts}
    inventory_paths = {str(item.get("path")) for item in inventory}
    if fact_paths != inventory_paths:
        errors.append("file facts and inventory path sets differ")
    forbidden_inventory = sorted(path for path in inventory_paths if _excluded_source(path))
    if forbidden_inventory:
        errors.append(
            "sensitive/excluded source paths entered inventory: "
            + ", ".join(forbidden_inventory[:10])
        )
    documents = retrieval.get("documents", [])
    if len(documents) != retrieval.get("document_count"):
        errors.append("retrieval document count is inconsistent")
    identifiers = [str(item.get("id")) for item in documents]
    if len(identifiers) != len(set(identifiers)):
        errors.append("retrieval document identifiers are not unique")
    forbidden_documents = sorted(
        {
            str(item.get("path"))
            for item in documents
            if item.get("path") and _excluded_source(str(item.get("path")))
        }
    )
    if forbidden_documents:
        errors.append(
            "sensitive/excluded source paths entered retrieval: "
            + ", ".join(forbidden_documents[:10])
        )
    document_count = len(documents)
    for token, postings in retrieval.get("postings", {}).items():
        for posting in postings:
            if (
                not isinstance(posting, list)
                or len(posting) != 2
                or not isinstance(posting[0], int)
                or posting[0] < 0
                or posting[0] >= document_count
            ):
                errors.append(f"invalid retrieval posting for token {token}")
                break
    forbidden_fields = {
        "value",
        "secret",
        "password",
        "token",
        "credential",
        "connection_string",
    }
    for key in configuration.get("keys", ()):
        if forbidden_fields.intersection(key):
            errors.append(
                f"configuration map contains prohibited value field for {key.get('key')}"
            )
    if check_freshness:
        project_root = Path(str(manifest.get("project_root", "")))
        if not project_root.is_dir():
            warnings.append(
                "freshness check skipped because recorded project root is unavailable"
            )
        else:
            try:
                walk = bounded_walk(
                    project_root,
                    limits=WalkLimits(
                        max_files=int(manifest["limits"]["max_files"]),
                        max_depth=int(manifest["limits"]["max_depth"]),
                        max_bytes=int(manifest["limits"]["max_bytes"]),
                    ),
                    symlink_policy="reject",
                    exclude=_excluded_source,
                )
                current = [
                    {
                        "path": entry.relative,
                        "size_bytes": entry.size or 0,
                        "sha256": _sha_file(entry.path),
                    }
                    for entry in walk.files
                ]
                current.sort(key=lambda item: str(item["path"]))
                if _stable_hash(current) != manifest.get("source_inventory_sha256"):
                    errors.append(
                        "project map is stale relative to the current source tree"
                    )
            except (OSError, FilesystemWalkError, ValueError) as error:
                errors.append(f"freshness walk failed: {error}")
    return {
        "valid": not errors,
        "map_dir": map_dir.as_posix(),
        "map_revision": manifest.get("map_revision"),
        "source_inventory_sha256": manifest.get("source_inventory_sha256"),
        "errors": errors,
        "warnings": warnings,
        "counts": manifest.get("counts", {}),
    }


def project_map_status(project: Path) -> dict[str, object]:
    try:
        map_dir = _map_dir(project)
    except ValueError as error:
        return {
            "valid": False,
            "available": False,
            "stale": None,
            "errors": [str(error)],
        }
    validation = validate_project_map(map_dir, check_freshness=False)
    manifest = (
        _load_json(map_dir / "project-manifest.json") if validation["valid"] else {}
    )
    return {
        "valid": validation["valid"],
        "available": True,
        "map_dir": map_dir.as_posix(),
        "map_revision": manifest.get("map_revision"),
        "source_inventory_sha256": manifest.get("source_inventory_sha256"),
        "counts": manifest.get("counts", {}),
        "errors": validation.get("errors", []),
        "freshness": "not_checked",
    }


def diff_project_maps(left: Path, right: Path) -> dict[str, object]:
    left_dir = _map_dir(left)
    right_dir = _map_dir(right)
    left_manifest = _load_json(left_dir / "project-manifest.json")
    right_manifest = _load_json(right_dir / "project-manifest.json")
    left_inventory = {
        str(item["path"]): item
        for item in _load_jsonl(left_dir / "file-inventory.jsonl")
    }
    right_inventory = {
        str(item["path"]): item
        for item in _load_jsonl(right_dir / "file-inventory.jsonl")
    }
    left_symbols = {
        (str(item["path"]), str(item.get("qualname")), str(item.get("kind")))
        for item in _load_jsonl(left_dir / "symbol-index.jsonl")
    }
    right_symbols = {
        (str(item["path"]), str(item.get("qualname")), str(item.get("kind")))
        for item in _load_jsonl(right_dir / "symbol-index.jsonl")
    }
    added = sorted(set(right_inventory) - set(left_inventory))
    removed = sorted(set(left_inventory) - set(right_inventory))
    changed = sorted(
        path
        for path in set(left_inventory).intersection(right_inventory)
        if left_inventory[path]["sha256"] != right_inventory[path]["sha256"]
    )
    return {
        "valid": True,
        "left_revision": left_manifest.get("map_revision"),
        "right_revision": right_manifest.get("map_revision"),
        "files": {
            "added": added,
            "removed": removed,
            "changed": changed,
            "unchanged_count": len(set(left_inventory).intersection(right_inventory))
            - len(changed),
        },
        "symbols": {
            "added": [
                {"path": item[0], "qualname": item[1], "kind": item[2]}
                for item in sorted(right_symbols - left_symbols)
            ],
            "removed": [
                {"path": item[0], "qualname": item[1], "kind": item[2]}
                for item in sorted(left_symbols - right_symbols)
            ],
        },
        "map_changed": left_manifest.get("map_revision")
        != right_manifest.get("map_revision"),
    }
