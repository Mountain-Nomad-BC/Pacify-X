from pathlib import Path

from runtime.release_environment import validate_release_environment


ROOT = Path(__file__).parents[1]


def test_current_release_environment_matches_exact_lock() -> None:
    result = validate_release_environment(ROOT)
    assert result["valid"], result["errors"]
    assert result["required_count"] >= 5
