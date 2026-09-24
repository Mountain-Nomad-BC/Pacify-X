"""Fail-closed application of a single-file semantic edit plan.

Writes are explicit.  A plan is revision-bound, revalidated under a PX FileLock,
syntax-checked through the registered backend, written to a same-directory temp
file, fsynced, and atomically replaced.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import tempfile

from .file_lock import FileLock
from .semantic_code_document import read_document_snapshot, snapshot_bytes
from .semantic_code_edits import SemanticEditPlan, render_edit_plan
from .semantic_code_limits import SemanticCodeLimits
from .semantic_code_paths import canonical_project_root, resolve_project_path
from .semantic_code_receipts import semantic_receipt
from .semantic_code_registry import SemanticBackendRegistry


@dataclass(frozen=True, slots=True)
class EditApplicationResult:
    written: bool
    relative_path: str
    before_sha256: str
    after_sha256: str
    plan_sha256: str
    diagnostics: tuple[dict[str, object], ...]
    receipt: dict[str, object]
    text: str | None = None


def _lock_path(root: Path, relative_path: str) -> Path:
    key = hashlib.sha256(relative_path.encode("utf-8")).hexdigest()[:24]
    return root / ".px" / "semantic-code" / "locks" / f"{key}.lock"


def apply_semantic_edit_plan(
    root: Path,
    plan: SemanticEditPlan,
    *,
    write: bool = False,
    registry: SemanticBackendRegistry | None = None,
    limits: SemanticCodeLimits = SemanticCodeLimits(),
    lock_timeout_seconds: float = 5.0,
) -> EditApplicationResult:
    root = canonical_project_root(root)
    registry = registry or SemanticBackendRegistry()
    target = resolve_project_path(root, plan.relative_path, require_file=True)

    def prepare() -> tuple[object, str, bytes, tuple[dict[str, object], ...], dict[str, object]]:
        snapshot = read_document_snapshot(root, plan.relative_path, max_bytes=limits.max_file_bytes)
        if snapshot.raw_sha256 != plan.expected_sha256:
            raise ValueError("semantic edit plan source revision is stale")
        candidate_text = render_edit_plan(snapshot, plan)
        raw = candidate_text.encode("utf-8")
        if len(raw) > limits.max_file_bytes:
            raise ValueError("semantic edit candidate exceeds file byte budget")
        candidate = snapshot_bytes(plan.relative_path, raw, max_bytes=limits.max_file_bytes)
        backend = registry.for_path(plan.relative_path)
        if backend is None:
            raise ValueError(f"no semantic backend for {plan.relative_path}")
        analysis = backend.analyze(candidate)
        diagnostics = tuple(item.as_dict() for item in analysis.diagnostics)
        if any(int(item.severity) == 1 for item in analysis.diagnostics):
            raise ValueError("semantic edit candidate introduces parse diagnostics")
        receipt = semantic_receipt(
            operation="apply_semantic_edit" if write else "preview_semantic_edit",
            project_revision=None,
            source_revision=snapshot.raw_sha256,
            result={
                "relative_path": plan.relative_path,
                "plan_sha256": plan.plan_sha256,
                "after_sha256": candidate.raw_sha256,
                "diagnostics": diagnostics,
            },
        )
        return snapshot, candidate_text, raw, diagnostics, receipt

    # Preview is deliberately side-effect free: no lock file, temp file, or cache write.
    if not write:
        snapshot, candidate_text, raw, diagnostics, receipt = prepare()
        return EditApplicationResult(
            written=False,
            relative_path=plan.relative_path,
            before_sha256=snapshot.raw_sha256,
            after_sha256=hashlib.sha256(raw).hexdigest(),
            plan_sha256=plan.plan_sha256,
            diagnostics=diagnostics,
            receipt=receipt,
            text=candidate_text,
        )

    with FileLock(_lock_path(root, plan.relative_path), timeout_seconds=lock_timeout_seconds):
        snapshot, _candidate_text, raw, diagnostics, receipt = prepare()
        current = read_document_snapshot(root, plan.relative_path, max_bytes=limits.max_file_bytes)
        if current.raw_sha256 != snapshot.raw_sha256:
            raise ValueError("semantic edit target changed before commit")
        mode = target.stat().st_mode
        fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.semantic-", dir=target.parent)
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temp_path, mode)
            latest = read_document_snapshot(root, plan.relative_path, max_bytes=limits.max_file_bytes)
            if latest.raw_sha256 != snapshot.raw_sha256:
                raise ValueError("semantic edit target changed during commit")
            os.replace(temp_path, target)
            try:
                directory_fd = os.open(target.parent, os.O_RDONLY)
            except OSError:
                directory_fd = None
            if directory_fd is not None:
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        finally:
            if temp_path.exists():
                temp_path.unlink()
        return EditApplicationResult(
            written=True,
            relative_path=plan.relative_path,
            before_sha256=snapshot.raw_sha256,
            after_sha256=hashlib.sha256(raw).hexdigest(),
            plan_sha256=plan.plan_sha256,
            diagnostics=diagnostics,
            receipt=receipt,
            text=None,
        )
