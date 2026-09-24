"""Explicit, revision-bound multi-file application for LSP WorkspaceEdit plans."""
from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import tempfile
from typing import Mapping

from .file_lock import FileLock
from .semantic_code_document import read_document_snapshot, snapshot_bytes
from .semantic_code_limits import SemanticCodeLimits
from .semantic_code_paths import canonical_project_root, resolve_project_path
from .semantic_code_receipts import semantic_receipt
from .semantic_code_registry import SemanticBackendRegistry
from .semantic_lsp_types import PositionEncoding, WorkspaceEditPlan
from .semantic_lsp_workspace import render_workspace_edit


@dataclass(frozen=True, slots=True)
class WorkspaceEditApplicationResult:
    written: bool
    before_sha256: Mapping[str, str]
    after_sha256: Mapping[str, str]
    diagnostics: Mapping[str, tuple[dict[str, object], ...]]
    receipt: Mapping[str, object]
    text: Mapping[str, str] | None = None


def _lock_path(root: Path, relative_path: str) -> Path:
    key = hashlib.sha256(relative_path.encode("utf-8")).hexdigest()[:24]
    return root / ".px" / "semantic-code" / "locks" / f"{key}.lock"


def _fsync_directory(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _stage(target: Path, raw: bytes, mode: int, *, suffix: str) -> Path:
    fd, name = tempfile.mkstemp(prefix=f".{target.name}.{suffix}-", dir=target.parent)
    path = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(path, mode)
        return path
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        path.unlink(missing_ok=True)
        raise


def apply_workspace_edit_plan(
    root: Path,
    plan: WorkspaceEditPlan,
    *,
    encoding: PositionEncoding,
    write: bool = False,
    registry: SemanticBackendRegistry | None = None,
    limits: SemanticCodeLimits = SemanticCodeLimits(),
    lock_timeout_seconds: float = 5.0,
) -> WorkspaceEditApplicationResult:
    root = canonical_project_root(root)
    registry = registry or SemanticBackendRegistry()
    relatives = tuple(sorted(plan.expected_sha256))
    if not relatives:
        raise ValueError("workspace edit plan has no project files")

    def prepare() -> tuple[dict[str, bytes], dict[str, bytes], dict[str, int], dict[str, tuple[dict[str, object], ...]]]:
        rendered = render_workspace_edit(root, plan, encoding=encoding, limits=limits)
        originals: dict[str, bytes] = {}
        candidates: dict[str, bytes] = {}
        modes: dict[str, int] = {}
        diagnostics: dict[str, tuple[dict[str, object], ...]] = {}
        for relative in relatives:
            target = resolve_project_path(root, relative, require_file=True)
            snapshot = read_document_snapshot(root, relative, max_bytes=limits.max_file_bytes)
            if snapshot.raw_sha256 != plan.expected_sha256[relative]:
                raise ValueError(f"workspace edit source revision is stale: {relative}")
            # Preserve the exact bytes whose SHA was just validated; do not
            # introduce a second unlocked read window between validation and staging.
            originals[relative] = snapshot.text.encode("utf-8")
            modes[relative] = target.stat().st_mode
            raw = rendered[relative].encode("utf-8")
            candidate = snapshot_bytes(relative, raw, max_bytes=limits.max_file_bytes)
            candidates[relative] = raw
            backend = registry.for_path(relative)
            if backend is None:
                diagnostics[relative] = ()
                continue
            analysis = backend.analyze(candidate)
            file_diagnostics = tuple(item.as_dict() for item in analysis.diagnostics)
            diagnostics[relative] = file_diagnostics
            if any(int(item.severity) == 1 for item in analysis.diagnostics):
                raise ValueError(f"workspace edit candidate introduces parse diagnostics: {relative}")
        return originals, candidates, modes, diagnostics

    if not write:
        originals, candidates, _modes, diagnostics = prepare()
        before = {relative: hashlib.sha256(originals[relative]).hexdigest() for relative in relatives}
        after = {relative: hashlib.sha256(candidates[relative]).hexdigest() for relative in relatives}
        rendered = {relative: candidates[relative].decode("utf-8") for relative in relatives}
        receipt = semantic_receipt(
            operation="preview_lsp_workspace_edit",
            project_revision=None,
            source_revision=None,
            result={"operation": plan.operation, "before": before, "after": after},
        )
        return WorkspaceEditApplicationResult(False, before, after, diagnostics, receipt, rendered)

    with ExitStack() as stack:
        for relative in relatives:
            stack.enter_context(FileLock(_lock_path(root, relative), timeout_seconds=lock_timeout_seconds))
        originals, candidates, modes, diagnostics = prepare()
        before = {relative: hashlib.sha256(originals[relative]).hexdigest() for relative in relatives}
        after = {relative: hashlib.sha256(candidates[relative]).hexdigest() for relative in relatives}
        staged: dict[str, Path] = {}
        committed: list[str] = []
        try:
            for relative in relatives:
                target = resolve_project_path(root, relative, require_file=True)
                staged[relative] = _stage(target, candidates[relative], modes[relative], suffix="lsp-stage")
            for relative in relatives:
                target = resolve_project_path(root, relative, require_file=True)
                current = target.read_bytes()
                if hashlib.sha256(current).hexdigest() != before[relative]:
                    raise ValueError(f"workspace edit target changed during commit: {relative}")
                os.replace(staged[relative], target)
                committed.append(relative)
                _fsync_directory(target.parent)
        except BaseException as original_error:
            rollback_errors: list[str] = []
            for relative in reversed(committed):
                target = resolve_project_path(root, relative, require_file=True)
                try:
                    current = target.read_bytes()
                    if hashlib.sha256(current).hexdigest() != after[relative]:
                        rollback_errors.append(f"{relative}: target changed after PX commit")
                        continue
                    restore = _stage(target, originals[relative], modes[relative], suffix="lsp-rollback")
                    os.replace(restore, target)
                    _fsync_directory(target.parent)
                except BaseException as rollback_error:
                    rollback_errors.append(f"{relative}: {rollback_error}")
            if rollback_errors:
                raise RuntimeError(
                    "workspace edit commit failed and rollback was incomplete: " + "; ".join(rollback_errors)
                ) from original_error
            raise
        finally:
            for path in staged.values():
                path.unlink(missing_ok=True)

        receipt = semantic_receipt(
            operation="apply_lsp_workspace_edit",
            project_revision=None,
            source_revision=None,
            result={"operation": plan.operation, "before": before, "after": after},
        )
        return WorkspaceEditApplicationResult(True, before, after, diagnostics, receipt, None)
