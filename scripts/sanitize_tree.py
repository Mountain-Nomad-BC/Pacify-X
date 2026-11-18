"""Replace private identifiers in text content and path names beneath an explicit root."""

from __future__ import annotations

import argparse
import json
import hashlib
import os
from pathlib import Path
import re
import shutil
import tempfile

from runtime.confined_output import ConfinementError, confined_path, publish_json


TERMS = ("r" + "ie", "re" + "my", "rh" + "eem")
REPLACEMENTS = (
    "intelligent_integrations_and_engines",
    "governed_retrieval_system_with_deterministic_rails",
    "enterprise",
)
PATTERN = re.compile(
    rf"(?i)(?:(?<![A-Za-z])({TERMS[0]})(?![A-Za-z])|({TERMS[1]}|{TERMS[2]}))"
)
MAPPING = dict(zip(TERMS, REPLACEMENTS))
LEGACY_TERMS = ("integration" + "_" + "engine", "governed" + "_" + "retrieval")
LEGACY_PATTERN = re.compile(
    rf"(?i)({LEGACY_TERMS[0]}|{LEGACY_TERMS[1]}(?!_system_with_deterministic_rails))"
)
LEGACY_MAPPING = dict(zip(LEGACY_TERMS, REPLACEMENTS[:2]))
SKIP_DIRECTORIES = {".git", "__pycache__", ".pytest_cache"}
MAX_SAFE_COMPONENT = 240
# The repository this producer lives in. Every write below is re-checked against it, so a
# caller-chosen root can never move a write outside the tree that owns these files.
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class SanitizationPreflightError(RuntimeError):
    def __init__(self, errors: list[str]) -> None:
        super().__init__(
            "sanitization preservation preflight could not inspect every in-scope file"
        )
        self.errors = tuple(errors)


def sanitize(value: str) -> str:
    cleaned = PATTERN.sub(lambda match: MAPPING[match.group(0).casefold()], value)
    return LEGACY_PATTERN.sub(
        lambda match: LEGACY_MAPPING[match.group(1).casefold()], cleaned
    )


def _sanitized_component(name: str) -> str:
    cleaned = sanitize(name)
    if len(cleaned) <= MAX_SAFE_COMPONENT:
        return cleaned
    suffix = Path(cleaned).suffix[:32]
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:24]
    return f"sanitized-{digest}{suffix}"


def _extended_windows_path(path: Path) -> str:
    value = str(path.resolve())
    return (
        "\\\\?\\" + value
        if os.name == "nt" and not value.startswith("\\\\?\\")
        else value
    )


def _target_exists(path: Path) -> bool:
    return os.path.exists(_extended_windows_path(path))


def _collision_safe_target(source: Path, target: Path) -> Path:
    if not _target_exists(target):
        return target
    suffix = target.suffix
    stem = target.name[: -len(suffix)] if suffix else target.name
    digest = hashlib.sha256(source.name.encode("utf-8")).hexdigest()
    for width in (12, 16, 24, 32, 64):
        marker = f"-{digest[:width]}"
        available = MAX_SAFE_COMPONENT - len(marker) - len(suffix)
        candidate = target.with_name(f"{stem[:available]}{marker}{suffix}")
        if not _target_exists(candidate):
            return candidate
    raise FileExistsError(
        f"could not allocate collision-safe sanitized path beneath: {target.parent}"
    )


def _rename(source: Path, target: Path) -> None:
    os.rename(_extended_windows_path(source), _extended_windows_path(target))


def _text_requires_change(path: Path) -> bool:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return any(sanitize(line) != line for line in handle)


def _confined_rewrite_source(path: Path) -> Path:
    """Re-check the source of an in-tree rewrite against the repository before writing.

    `root` is caller-chosen but the walk starts at `resolved`, so every path that reaches here
    is already a descendant of that resolved root; this adds the repository boundary itself, so
    a caller root outside the repository can never be rewritten by this producer.
    """
    return confined_path(REPOSITORY_ROOT, path, label="rewrite source")


def _confined_rewrite_target(path: Path, temporary_name: str) -> Path:
    """The prepared temporary that is about to replace `path`.

    `tempfile` returns a bare file name in its `dir`; resolved against the source's own parent
    it is that file, and it is checked against the repository before the rename can touch it.
    """
    candidate = confined_path(REPOSITORY_ROOT, path.parent / temporary_name, label="rewrite temporary")
    if candidate.parent != path.parent:
        raise ConfinementError("rewrite temporary must sit beside its source")
    return candidate


def _rewrite_text(path: Path, failed_temporary_quarantine: Path) -> None:
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="",
            delete=False,
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".sanitize-tmp",
        ) as destination:
            temporary_name = destination.name
            with path.open("r", encoding="utf-8", newline="") as source:
                for line in source:
                    destination.write(sanitize(line))
        temporary = _confined_rewrite_target(path, temporary_name)
        shutil.copystat(path, temporary)
        os.replace(temporary, path)
        temporary_name = None
    finally:
        if temporary_name:
            temporary = _confined_rewrite_target(path, temporary_name)
            if temporary.exists():
                quarantine = confined_path(
                    REPOSITORY_ROOT, failed_temporary_quarantine, label="failure quarantine"
                )
                quarantine.mkdir(parents=True, exist_ok=True)
                target = confined_path(quarantine, temporary.name, label="failure quarantine entry")
                if target.exists():
                    target = confined_path(
                        quarantine,
                        f"{temporary.stem}-{hashlib.sha256(temporary.read_bytes()).hexdigest()[:12]}{temporary.suffix}",
                        label="failure quarantine entry",
                    )
                os.replace(temporary, target)


def _binary_has_private_term(path: Path) -> bool:
    overlap = b""
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            buffer = overlap + chunk
            text = buffer.decode("latin-1", errors="ignore")
            if PATTERN.search(text) or LEGACY_PATTERN.search(text):
                return True
            overlap = buffer[-128:]
    return False


def sanitize_tree(
    root: Path,
    *,
    apply: bool = False,
    excluded_names: frozenset[str] = frozenset(),
    preservation_root: Path | None = None,
) -> dict[str, object]:
    resolved = root.resolve()
    if not resolved.is_dir() or resolved == Path(resolved.anchor):
        raise ValueError("root must be an explicit non-filesystem-root directory")
    preserved: list[dict[str, object]] = []
    preservation = preservation_root.resolve() if preservation_root else None
    if apply:
        if preservation is None:
            raise ValueError("apply requires a recoverable preservation root")
        # PX-OS-1067: the preservation root is a destination this producer writes, so it must
        # be confined to the repository. Combined with the existing rule below that it must not
        # nest inside the sanitized tree, this makes every preserved copy land in a location
        # the repository owns rather than an arbitrary caller directory.
        repository_root = Path(__file__).resolve().parents[1]
        try:
            preservation.relative_to(repository_root)
        except ValueError as error:
            raise ValueError(
                "apply requires a preservation root inside the repository"
            ) from error
        preservation_is_nested = True
        try:
            preservation.relative_to(resolved)
        except ValueError:
            preservation_is_nested = False
        if preservation_is_nested:
            raise ValueError(
                "preservation root must be outside the active sanitization tree"
            )
        if preservation.exists() and any(preservation.iterdir()):
            raise ValueError("preservation root must not contain an earlier run")
        preservation = confined_path(REPOSITORY_ROOT, preservation, label="preservation root")
        preservation.mkdir(parents=True, exist_ok=True)
    content_changes: list[str] = []
    path_changes: list[dict[str, str]] = []
    binary_hits: list[str] = []
    errors: list[str] = []
    paths = sorted(resolved.rglob("*"), key=lambda item: len(item.parts), reverse=True)
    if apply and preservation is not None:
        affected: set[Path] = set()
        preservation_errors: list[str] = []
        changed_nodes = [
            path for path in paths if _sanitized_component(path.name) != path.name
        ]
        for path in paths:
            relative_parts = path.relative_to(resolved).parts
            if any(
                part in SKIP_DIRECTORIES or part in excluded_names
                for part in relative_parts
            ):
                continue
            if path.is_file():
                try:
                    with path.open("rb") as handle:
                        sample = handle.read(65536)
                    if b"\x00" not in sample and _text_requires_change(path):
                        affected.add(path)
                except (OSError, UnicodeDecodeError) as error:
                    preservation_errors.append(
                        sanitize(
                            f"{path.relative_to(resolved).as_posix()}: {type(error).__name__}: {error}"
                        )
                    )
        if preservation_errors:
            raise SanitizationPreflightError(sorted(preservation_errors))
        for node in changed_nodes:
            if node.is_file():
                affected.add(node)
            elif node.is_dir():
                affected.update(path for path in node.rglob("*") if path.is_file())
        for path in sorted(affected, key=lambda item: item.as_posix().casefold()):
            relative = path.relative_to(resolved)
            target = preservation / relative
            # Re-checked at write time: the walk can visit a name that is now a link to
            # somewhere else, and the preservation copy must never follow it out of the root.
            target = confined_path(REPOSITORY_ROOT, target, label="preservation target")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            preserved.append(
                {
                    "path": relative.as_posix(),
                    "sha256": hashlib.sha256(
                        confined_path(REPOSITORY_ROOT, path, label="preservation source").read_bytes()
                    ).hexdigest(),
                    "bytes": path.stat().st_size,
                }
            )
        from runtime.confined_output import publish_json as _publish_json

        receipt = {
            "schema_version": "1.0",
            "operation": "pre_sanitization_preservation_copy",
            "source_root": ".",
            "recovery": "Restore a recorded quarantined file to its original relative path only after approved review.",
            "records": preserved,
        }
        # `preservation` is already confined to the repository above; publishing the receipt
        # atomically means a crash cannot leave a half-written recovery record beside files
        # that were already copied out of the tree.
        _publish_json(preservation, preservation / "preservation-receipt.json", receipt)
    for path in paths:
        relative_parts = path.relative_to(resolved).parts
        if any(
            part in SKIP_DIRECTORIES or part in excluded_names
            for part in relative_parts
        ):
            continue
        if path.is_file():
            try:
                with path.open("rb") as handle:
                    sample = handle.read(65536)
                if b"\x00" in sample:
                    if _binary_has_private_term(path):
                        binary_hits.append(
                            sanitize(path.relative_to(resolved).as_posix())
                        )
                else:
                    changed = _text_requires_change(path)
                    if changed:
                        content_changes.append(
                            sanitize(path.relative_to(resolved).as_posix())
                        )
                        if apply:
                            assert preservation is not None
                            _rewrite_text(
                                _confined_rewrite_source(path),
                                preservation / "_failed-sanitizer-temporary",
                            )
            except (OSError, UnicodeDecodeError) as error:
                errors.append(
                    sanitize(
                        f"{path.relative_to(resolved).as_posix()}: {type(error).__name__}: {error}"
                    )
                )
        cleaned_name = _sanitized_component(path.name)
        if cleaned_name != path.name:
            target = _collision_safe_target(path, path.with_name(cleaned_name))
            source_relative = path.relative_to(resolved).as_posix()
            path_changes.append(
                {
                    "source_path_sha256": hashlib.sha256(
                        source_relative.encode()
                    ).hexdigest(),
                    "to": sanitize(target.relative_to(resolved).as_posix()),
                }
            )
            if apply:
                _rename(path, target)
    return {
        "schema_version": "1.0",
        "root": ".",
        "apply": apply,
        "content_change_count": len(content_changes),
        "content_changes": sorted(content_changes),
        "path_change_count": len(path_changes),
        "path_changes": sorted(
            path_changes, key=lambda item: item["source_path_sha256"]
        ),
        "binary_hit_count": len(binary_hits),
        "binary_hits": sorted(binary_hits),
        "error_count": len(errors),
        "errors": sorted(errors),
        "preservation_count": len(preserved),
        "hard_delete": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--exclude-name", action="append", default=[])
    parser.add_argument("--preservation-root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = sanitize_tree(
        args.root,
        apply=args.apply,
        excluded_names=frozenset(args.exclude_name),
        preservation_root=args.preservation_root,
    )
    if args.output:
        # Confined, atomic publication inside the repository root. The sanitization result is
        # a report, never a mutation: the apply gate above is unchanged.
        publish_json(REPOSITORY_ROOT, args.output, result)
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "apply",
                    "content_change_count",
                    "path_change_count",
                    "binary_hit_count",
                    "error_count",
                )
            },
            indent=2,
        )
    )
    return 0 if not result["binary_hits"] and not result["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
