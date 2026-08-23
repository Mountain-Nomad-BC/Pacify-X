from pathlib import Path

from runtime.release_preflight import concurrency_stress


def test_release_concurrency_stress_is_bounded_and_seeded(tmp_path: Path) -> None:
    result = concurrency_stress(tmp_path, iterations=25, seed=12345)
    assert result["valid"] and result["iterations"] == 25 and result["seed"] == 12345
    assert result["operations"] == ["atomic-json-publication", "file-lock-mutual-exclusion"]
    assert not list(tmp_path.glob(".*.prepared"))
