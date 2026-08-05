from pathlib import Path

from runtime.test_profiles import resolve_test_profile


ROOT = Path(__file__).resolve().parents[1]


def test_full_and_release_include_every_discovered_test_file():
    full = resolve_test_profile(ROOT, "full")
    release = resolve_test_profile(ROOT, "release")
    assert full["member_count"] == full["discovered_test_files"]
    assert release["members"] == full["members"]
    assert release["gates"]


def test_fast_keeps_ordinary_contract_checks_and_excludes_expensive_artifact_gates():
    fast = resolve_test_profile(ROOT, "fast")
    assert "tests/test_declared_suite_support.py" in fast["members"]
    assert "tests/test_exact_tool_certification.py" not in fast["members"]
    assert "tests/test_installed_wheel_e2e.py" not in fast["members"]
    assert (
        fast["timeout_seconds"] < resolve_test_profile(ROOT, "full")["timeout_seconds"]
    )
