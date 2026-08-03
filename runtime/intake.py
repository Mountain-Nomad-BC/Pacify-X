"""Read-only, deterministic existing-project discovery."""
from __future__ import annotations

from collections import Counter
import hashlib
from pathlib import Path


EXCLUDES = {
    ".git", ".hg", ".svn", ".venv", "venv", "node_modules", "build", "dist", "__pycache__",
    ".engineering-bootstrap", "quarantine", "evidence", "planning",
}
LANGUAGES = {".py": "python", ".ts": "typescript", ".tsx": "typescript", ".js": "javascript", ".jsx": "javascript", ".go": "go", ".rs": "rust", ".java": "java", ".cs": "dotnet", ".rb": "ruby", ".php": "php"}
FRAMEWORK_FILES = {"pyproject.toml": "python", "requirements.txt": "python", "package.json": "node", "go.mod": "go", "cargo.toml": "rust", "docker-compose.yml": "containers", "docker-compose.yaml": "containers"}


def inspect_existing_project(project: Path, *, max_files: int = 10000) -> dict[str, object]:
    root = project.resolve()
    if not root.is_dir():
        raise ValueError("existing project must be a directory")
    if max_files < 1:
        raise ValueError("max_files must be positive")
    paths: list[Path] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix().casefold()):
        if any(part.casefold() in EXCLUDES for part in path.relative_to(root).parts):
            continue
        if path.is_file():
            paths.append(path)
            if len(paths) >= max_files:
                break
    relatives = [path.relative_to(root).as_posix() for path in paths]
    names = {path.name.casefold() for path in paths}
    languages = Counter(LANGUAGES[path.suffix.casefold()] for path in paths if path.suffix.casefold() in LANGUAGES)
    frameworks = sorted({value for name, value in FRAMEWORK_FILES.items() if name in names})
    tests = [relative for relative in relatives if "test" in Path(relative).name.casefold()]
    security = [relative for relative in relatives if any(term in relative.casefold() for term in ("security", "auth", "policy", "threat"))]
    ci = [relative for relative in relatives if relative.startswith((".github/workflows/", ".gitlab-ci")) or Path(relative).name.casefold() in {"jenkinsfile", "azure-pipelines.yml"}]
    owners = [relative for relative in relatives if Path(relative).name.casefold() in {"agents.md", "codeowners", "architecture.md", "package.json", "pyproject.toml"}]
    digest = hashlib.sha256("\n".join(relatives).encode()).hexdigest()
    gaps = []
    if not tests: gaps.append("test discovery produced no candidates")
    if not security: gaps.append("security-policy discovery produced no candidates")
    if not ci: gaps.append("CI discovery produced no candidates")
    return {
        "schema_version": "1.0", "mode": "read_only", "root_name": root.name,
        "file_count": len(paths), "truncated": len(paths) == max_files,
        "inventory_sha256": digest, "languages": dict(sorted(languages.items())), "frameworks": frameworks,
        "tests": tests, "security_assets": security, "ci_assets": ci, "canonical_owner_candidates": owners,
        "gap_matrix": gaps, "proposed_integrations": ["project-scoped metadata registry", "bounded validation profile"],
        "minimal_patch_path": ["add .engineering-bootstrap metadata", "preserve existing owners", "install no tools"],
    }
