"""Repository-wide exclusion for tests and projection identity mutation."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

from .file_lock import FileLock


OWNER_ENV = "PX_TEST_ORCHESTRATION_OWNER"
SUPERVISED_CHILD_ENV = "PX_TEST_ORCHESTRATION_SUPERVISED_CHILD"
LOCK_RELATIVE_PATH = Path(
    ".engineering-bootstrap/test-evidence/.test-orchestration.lock"
)


def claim_orchestration_lock(
    root: Path,
    *,
    owner_kind: str,
    allow_inherited_owner: bool = False,
) -> tuple[FileLock | None, str | None]:
    """Claim the physical repository lock or reuse a true child lease.

    Only the supervised stale-group child may reuse its profile parent's
    token. Projection writers always claim the physical lock, even when an
    owner token is present, so a test process cannot mutate group identity
    while its parent profile is collecting receipts.
    """

    resolved = root.resolve()
    previous = os.environ.get(OWNER_ENV)
    if allow_inherited_owner and previous:
        return None, previous
    lock = FileLock(resolved / LOCK_RELATIVE_PATH, timeout_seconds=0.25)
    lock.__enter__()
    os.environ[OWNER_ENV] = (
        f"{owner_kind}:{os.getpid()}:{uuid4().hex}"
    )
    return lock, previous


def release_orchestration_lock(
    lock: FileLock | None, previous_owner: str | None
) -> None:
    """Release a physical lease and restore the caller's prior token."""

    if lock is None:
        return
    if previous_owner is None:
        os.environ.pop(OWNER_ENV, None)
    else:
        os.environ[OWNER_ENV] = previous_owner
    lock.__exit__(None, None, None)
