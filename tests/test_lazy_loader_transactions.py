from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile

import pytest

from runtime.lazy_loader import LazySkillLoader, SkillDescriptor


def _loader(root: Path, *, max_active: int = 3, max_bytes: int = 100) -> LazySkillLoader:
    (root / "base.md").write_text("base", encoding="utf-8")
    (root / "large.md").write_text("x" * 200, encoding="utf-8")
    return LazySkillLoader(root, (
        SkillDescriptor("base", "base.md"),
        SkillDescriptor("broken", "missing.md", dependencies=("base",)),
        SkillDescriptor("large", "large.md", dependencies=("base",)),
    ), max_active=max_active, max_bytes=max_bytes)


def test_failed_hydration_leaves_no_active_state() -> None:
    with tempfile.TemporaryDirectory() as directory:
        loader = _loader(Path(directory))
        with pytest.raises(FileNotFoundError):
            loader.hydrate("broken")
        assert loader.active_ids == ()


def test_failed_hydration_does_not_consume_budget() -> None:
    with tempfile.TemporaryDirectory() as directory:
        loader = _loader(Path(directory))
        before = loader.footprint_bytes
        with pytest.raises(ValueError, match="byte budget"):
            loader.hydrate("large")
        assert loader.footprint_bytes == before == 0


def test_hydration_retry_is_idempotent() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory); loader = _loader(root)
        with pytest.raises(FileNotFoundError):
            loader.hydrate("broken")
        (root / "missing.md").write_text("fixed", encoding="utf-8")
        hydrated = loader.hydrate("broken")
        assert hydrated.capability_id == "broken"
        assert loader.active_ids == ("base", "broken")


def test_concurrent_hydration_deduplicates_capability() -> None:
    with tempfile.TemporaryDirectory() as directory:
        loader = _loader(Path(directory))
        with ThreadPoolExecutor(max_workers=8) as pool:
            values = tuple(pool.map(lambda _: loader.hydrate("base"), range(24)))
        assert all(value is values[0] for value in values)
        assert loader.active_ids == ("base",)


def test_hydration_commit_occurs_after_all_validation() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory); loader = _loader(root, max_active=1)
        (root / "missing.md").write_text("fixed", encoding="utf-8")
        with pytest.raises(ValueError, match="active skill budget"):
            loader.hydrate("broken")
        assert loader.active_ids == ()
