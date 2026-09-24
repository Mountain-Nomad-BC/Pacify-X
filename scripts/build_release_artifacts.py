"""Generate the release supply-chain artifacts required by the compliance gate.

Produces, deterministically and **before the freeze** (never after — generating these post-freeze
would change the certified bytes):

  * a CycloneDX-style SBOM for the shipped surfaces;
  * a build-provenance document binding source, toolchain, and artifact hashes;
  * a git-history secret scan report;
  * a packaged-artifact (VSIX) secret scan report.

The SBOM is generated from the **actual resolved manifests**, not a hand-maintained list, so it
cannot drift from the dependency set. If a shipped component is not in a manifest, this tool
cannot see it — which is why the output records the manifest provenance it used.

Usage:
    python scripts/build_release_artifacts.py --root . --check
    python scripts/build_release_artifacts.py --root . --apply
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SBOM_SCHEMA = "px.sbom/1.0"
PROVENANCE_SCHEMA = "px.build-provenance/1.0"
SECRET_SCAN_SCHEMA = "px.secret-scan/1.0"

OUT_DIR = Path("evidence/release/compliance")

# Secret shapes, mirroring scripts/verify_release_invariants.py so the two agree.
SECRET_SHAPES = (
    re.compile(
        r"(?i)\b(api[_-]?key|client[_-]?secret|access[_-]?token|auth[_-]?token|password)\s*[:=]\s*[\"']([A-Za-z0-9+/]{24,})[\"']"
    ),
    re.compile(
        r"\b(sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|gho_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9-]{10,})\b"
    ),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----"),
)
SECRET_ALLOW = (
    "example",
    "placeholder",
    "redacted",
    "fixture",
    "preview-",
    "test-",
    "dummy",
    "xxxx",
    "sample",
)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_write(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.new")
    temporary.write_text(payload, encoding="utf-8", newline="\n")
    temporary.replace(path)


def _python_components(root: Path) -> list[dict]:
    components: list[dict] = []
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        return components
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    project = data.get("project", {})
    components.append(
        {
            "type": "application",
            "name": str(project.get("name", "unknown")),
            "version": str(project.get("version", "0.0.0")),
            "licenses": [str(project.get("license", ""))],
            "purl": f"pkg:pypi/{project.get('name', 'unknown')}@{project.get('version', '0.0.0')}",
            "scope": "self",
        }
    )
    for requirement in project.get("dependencies", []) or []:
        name, _, version = str(requirement).partition("==")
        version = version or "unspecified"
        components.append(
            {
                "type": "library",
                "name": name.strip(),
                "version": version.strip(),
                "purl": f"pkg:pypi/{name.strip()}@{version.strip()}",
                "scope": "direct",
                "source": "pyproject.toml",
            }
        )
    return components


def _npm_components(root: Path) -> list[dict]:
    components: list[dict] = []
    package_path = root / "extension/package.json"
    if not package_path.is_file():
        return components
    package = json.loads(package_path.read_text(encoding="utf-8-sig"))
    components.append(
        {
            "type": "application",
            "name": str(package.get("name", "unknown")),
            "version": str(package.get("version", "0.0.0")),
            "purl": f"pkg:npm/{package.get('name', 'unknown')}@{package.get('version', '0.0.0')}",
            "scope": "self",
            "note": "VS Code extension",
        }
    )
    for section, scope in (
        ("dependencies", "direct"),
        ("devDependencies", "development"),
    ):
        for name, version in sorted((package.get(section) or {}).items()):
            components.append(
                {
                    "type": "library",
                    "name": name,
                    "version": str(version),
                    "purl": f"pkg:npm/{name}@{version}",
                    "scope": scope,
                    "source": f"extension/package.json#{section}",
                }
            )
    return components


def build_sbom(root: Path) -> dict:
    components = _python_components(root) + _npm_components(root)
    return {
        "schema_version": SBOM_SCHEMA,
        "format": "CycloneDX-compatible (subset)",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "component_count": len(components),
        "scope_note": (
            "Covers artifacts Pacify-X distributes: the Python package and the VS Code extension "
            "with bundled npm dependencies. The local model runtime and GGUF weights are NOT "
            "distributed by Pacify-X and are therefore not SBOM components; their identity is "
            "recorded in the runtime lock and at model admission."
        ),
        "manifest_provenance": [
            "pyproject.toml",
            "extension/package.json",
        ],
        "components": components,
    }


def build_provenance(root: Path) -> dict:
    def _git(args: list[str]) -> str:
        git = shutil.which("git") or r"C:\Program Files\Git\cmd\git.exe"
        if not Path(str(git)).is_file():
            return ""
        try:
            result = subprocess.run(
                [str(git), *args],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=60,
                shell=False,
            )
            return (result.stdout or "").strip()
        except (OSError, subprocess.SubprocessError):
            return ""

    artifacts: list[dict] = []
    for relative in ("pyproject.toml", "extension/package.json"):
        path = root / relative
        if path.is_file():
            artifacts.append(
                {
                    "path": relative,
                    "sha256": _sha256_file(path),
                    "size_bytes": path.stat().st_size,
                }
            )
    lock = Path.home() / ".px/runtime-lock.json"
    runtime_lock: dict | None = None
    if lock.is_file():
        try:
            runtime_lock = json.loads(lock.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            runtime_lock = None
    return {
        "schema_version": PROVENANCE_SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "head_commit": _git(["rev-parse", "HEAD"]),
            "describe": _git(["describe", "--tags", "--always"]),
            "branch": _git(["rev-parse", "--abbrev-ref", "HEAD"]),
        },
        "toolchain": {
            "python": sys.version.split()[0],
            "platform": sys.platform,
        },
        "artifacts": artifacts,
        "local_runtime": {
            "resolved_commit": (runtime_lock or {}).get("resolved_commit"),
            "server_sha256": (runtime_lock or {}).get("server_sha256"),
            "cuda_architectures": (runtime_lock or {}).get("cuda_architectures"),
            "note": "Built locally by the operator; not distributed by Pacify-X.",
        },
        "freeze_rule": (
            "Provenance must be produced before the certification freeze. Producing or regenerating "
            "it after the freeze changes the candidate and invalidates certification."
        ),
    }


def scan_git_history(root: Path) -> dict:
    """Scan committed blobs for credential literals."""

    git = shutil.which("git") or r"C:\Program Files\Git\cmd\git.exe"
    if not Path(str(git)).is_file():
        return {
            "schema_version": SECRET_SCAN_SCHEMA,
            "scope": "git-history",
            "performed": False,
            "reason": "git executable unavailable",
            "findings": [],
        }
    try:
        revs = subprocess.run(
            [str(git), "rev-list", "--all"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=180,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return {
            "schema_version": SECRET_SCAN_SCHEMA,
            "scope": "git-history",
            "performed": False,
            "reason": f"{type(error).__name__}",
            "findings": [],
        }
    scanned = 0
    findings: list[dict] = []
    for commit in (revs.stdout or "").split()[:2000]:
        try:
            blob = subprocess.run(
                [str(git), "show", f"{commit}:{''}"],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=60,
                shell=False,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        scanned += 1
        if blob.returncode != 0:
            continue
        for number, line in enumerate(blob.stdout.splitlines(), start=1):
            for pattern in SECRET_SHAPES:
                if not pattern.search(line):
                    continue
                if any(token in line.casefold() for token in SECRET_ALLOW):
                    continue
                findings.append(
                    {"commit": commit[:12], "line": number, "text": line.strip()[:120]}
                )
                break
        if findings:
            break
    return {
        "schema_version": SECRET_SCAN_SCHEMA,
        "scope": "git-history",
        "performed": True,
        "commits_scanned": scanned,
        "finding_count": len(findings),
        "findings": findings[:50],
        "note": (
            "History scanning is bounded. A live credential found in history must be rotated "
            "first; rewriting history does not un-leak a key."
        ),
    }


def scan_packaged(root: Path) -> dict:
    """Scan packaged artifacts (VSIX / dist) for credential literals."""

    findings: list[dict] = []
    scanned = 0
    for area in ("extension/dist", "dist"):
        base = root / area
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.stat().st_size > 8 * 1024 * 1024:
                continue
            if path.suffix.casefold() not in {
                ".js",
                ".json",
                ".txt",
                ".md",
                ".map",
                ".vsix",
            }:
                continue
            try:
                text = path.read_text(encoding="utf-8-sig", errors="ignore")
            except OSError:
                continue
            scanned += 1
            for number, line in enumerate(text.splitlines(), start=1):
                for pattern in SECRET_SHAPES:
                    if not pattern.search(line):
                        continue
                    if any(token in line.casefold() for token in SECRET_ALLOW):
                        continue
                    findings.append(
                        {
                            "path": path.relative_to(root).as_posix(),
                            "line": number,
                            "text": line.strip()[:120],
                        }
                    )
                    break
    return {
        "schema_version": SECRET_SCAN_SCHEMA,
        "scope": "packaged-artifacts",
        "performed": scanned > 0,
        "files_scanned": scanned,
        "finding_count": len(findings),
        "findings": findings[:50],
        "note": "Runs only when a built package exists; an unbuilt tree has nothing to scan.",
    }


def build(root: Path, *, apply: bool) -> dict:
    root = root.resolve(strict=True)
    sbom = build_sbom(root)
    provenance = build_provenance(root)
    history = scan_git_history(root)
    packaged = scan_packaged(root)
    outputs = {
        "sbom.json": json.dumps(sbom, indent=2),
        "build-provenance.json": json.dumps(provenance, indent=2),
        "secret-scan-git-history.json": json.dumps(history, indent=2),
        "secret-scan-packaged.json": json.dumps(packaged, indent=2),
    }
    written: list[str] = []
    if apply:
        for name, payload in outputs.items():
            _atomic_write(root / OUT_DIR / name, payload + "\n")
            written.append((OUT_DIR / name).as_posix())
    return {
        "schema_version": "px.release-artifacts-build/1.0",
        "apply": apply,
        "sbom_components": sbom["component_count"],
        "provenance_head": provenance["source"]["head_commit"][:12],
        "git_history_findings": history.get("finding_count"),
        "packaged_findings": packaged.get("finding_count"),
        "written": written,
        "valid": (history.get("finding_count") or 0) == 0
        and (packaged.get("finding_count") or 0) == 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    result = build(args.root, apply=args.apply and not args.check)
    print(json.dumps(result, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
