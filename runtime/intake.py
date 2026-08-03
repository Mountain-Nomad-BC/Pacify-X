"""Read-only, deterministic existing-project discovery."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path

from .bounded_walk import WalkLimits, bounded_walk


EXCLUDES = {
    ".git", ".hg", ".svn", ".venv", "venv", "node_modules", "build", "dist", "__pycache__",
    ".engineering-bootstrap", "quarantine", "evidence", "planning",
}
LANGUAGES = {".py": "python", ".ts": "typescript", ".tsx": "typescript", ".js": "javascript", ".jsx": "javascript", ".go": "go", ".rs": "rust", ".java": "java", ".cs": "dotnet", ".rb": "ruby", ".php": "php"}
FRAMEWORK_FILES = {"pyproject.toml": "python", "requirements.txt": "python", "package.json": "node", "go.mod": "go", "cargo.toml": "rust", "docker-compose.yml": "containers", "docker-compose.yaml": "containers"}


def inspect_existing_project(
    project: Path, *, max_files: int = 10000, max_depth: int = 64,
    max_bytes: int = 256 * 1024 * 1024,
) -> dict[str, object]:
    root = project.resolve()
    if not root.is_dir():
        raise ValueError("existing project must be a directory")
    if max_files < 1:
        raise ValueError("max_files must be positive")
    # One extra accepted entry makes the public truncation state unambiguous.
    walk = bounded_walk(
        root,
        limits=WalkLimits(max_files=max_files + 1, max_depth=max_depth, max_bytes=max_bytes),
        symlink_policy="reject",
        exclude=lambda relative: any(part.casefold() in EXCLUDES for part in Path(relative).parts),
    )
    entries = list(walk.files)
    truncated = len(entries) > max_files
    entries = entries[:max_files]
    paths = [entry.path for entry in entries]
    relatives = [path.relative_to(root).as_posix() for path in paths]
    names = {path.name.casefold() for path in paths}
    languages = Counter(LANGUAGES[path.suffix.casefold()] for path in paths if path.suffix.casefold() in LANGUAGES)
    frameworks = sorted({value for name, value in FRAMEWORK_FILES.items() if name in names})
    tests = [relative for relative in relatives if "test" in Path(relative).name.casefold()]
    security = [relative for relative in relatives if any(term in relative.casefold() for term in ("security", "auth", "policy", "threat"))]
    ci = [relative for relative in relatives if relative.startswith((".github/workflows/", ".gitlab-ci")) or Path(relative).name.casefold() in {"jenkinsfile", "azure-pipelines.yml"}]
    owners = [relative for relative in relatives if Path(relative).name.casefold() in {"agents.md", "codeowners", "architecture.md", "package.json", "pyproject.toml"}]
    inventory_records = [
        {"path": entry.relative, "size_bytes": entry.size, "sha256": hashlib.sha256(entry.path.read_bytes()).hexdigest(), "file_type": "regular"}
        for entry in entries
    ]
    digest = hashlib.sha256(
        json.dumps(inventory_records, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    gaps = []
    if not tests: gaps.append("test discovery produced no candidates")
    if not security: gaps.append("security-policy discovery produced no candidates")
    if not ci: gaps.append("CI discovery produced no candidates")
    return {
        "schema_version": "1.0", "mode": "read_only", "root_name": root.name,
        "file_count": len(paths), "truncated": truncated,
        "inventory_sha256": digest, "inventory_records": inventory_records,
        "languages": dict(sorted(languages.items())), "frameworks": frameworks,
        "tests": tests, "security_assets": security, "ci_assets": ci, "canonical_owner_candidates": owners,
        "gap_matrix": gaps, "proposed_integrations": ["project-scoped metadata registry", "bounded validation profile"],
        "minimal_patch_path": ["add .engineering-bootstrap metadata", "preserve existing owners", "install no tools"],
    }
