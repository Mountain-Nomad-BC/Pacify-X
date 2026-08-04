import os
from pathlib import Path
import stat
import tempfile

from runtime.file_lock import FileLock
from runtime.platform_support import python_minor_supported, runtime_python_status
from runtime.release_environment import support_matrix, validate_support_matrix


ROOT = Path(__file__).parents[1]


def test_platform_support_policy_matches_declared_ci_matrix() -> None:
    result = validate_support_matrix(ROOT)
    assert result["valid"], result["errors"]
    assert result["python_requires"] == ">=3.11,<3.15"
    assert result["python_minors"] == ["3.11", "3.12", "3.13", "3.14"]
    assert set(result["operating_systems"]) == {"Windows", "Linux", "Darwin"}
    assert set(result["ci_runners"].values()) == {
        "windows-latest",
        "ubuntu-latest",
        "macos-latest",
    }


def test_runtime_python_support_enforces_both_bounds() -> None:
    policy = support_matrix(ROOT)
    assert not python_minor_supported((3, 10), policy)
    for minor in (11, 12, 13, 14):
        assert python_minor_supported((3, minor), policy)
        assert runtime_python_status(ROOT, (3, minor, 0))["supported"]
    assert not python_minor_supported((3, 15), policy)
    assert runtime_python_status(ROOT, (3, 15, 0))["reason"] == "python_version_outside_supported_range"


def test_path_semantics_accept_spaces_and_non_ascii_names() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "space path" / "café-工程.txt"
        path.parent.mkdir()
        path.write_text("portable\n", encoding="utf-8", newline="\n")
        assert path.read_text(encoding="utf-8") == "portable\n"
        assert path.resolve().is_file()


def test_advisory_file_lock_works_on_supported_host() -> None:
    with tempfile.TemporaryDirectory() as directory:
        lock_path = Path(directory) / "nested lock" / "state.lock"
        with FileLock(lock_path):
            assert lock_path.is_file()


def test_permission_boundary_preserves_read_only_files() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "read-only.txt"
        path.write_text("immutable input\n", encoding="utf-8")
        original_mode = stat.S_IMODE(path.stat().st_mode)
        try:
            path.chmod(stat.S_IREAD)
            assert stat.S_IMODE(path.stat().st_mode) & stat.S_IWRITE == 0
            assert path.read_text(encoding="utf-8") == "immutable input\n"
        finally:
            path.chmod(original_mode | stat.S_IWRITE)


def test_repository_enforces_lf_line_endings() -> None:
    attributes = (ROOT / ".gitattributes").read_bytes()
    assert b"* text=auto eol=lf\n" in attributes
    assert b"\r\n" not in attributes
    assert "lf-line-endings" in support_matrix(ROOT)["platform_checks"]


def test_host_os_is_in_release_support_policy() -> None:
    expected = {"nt": "Windows", "posix": {"Linux", "Darwin"}}
    allowed = set(support_matrix(ROOT)["operating_systems"])
    if os.name == "nt":
        assert expected["nt"] in allowed
    else:
        assert allowed.intersection(expected["posix"])
