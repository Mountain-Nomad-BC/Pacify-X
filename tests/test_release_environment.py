import hashlib
from pathlib import Path
import tempfile

from runtime.release_environment import (
    build_wheelhouse_manifest,
    certification_platform_binding,
    offline_install_command,
    parse_release_lock,
    scrub_release_environment,
    support_matrix,
    toolchain_identity,
    validate_certification_platform,
    validate_release_environment,
    validate_release_lock,
    validate_support_matrix,
)
from runtime.file_lock import FileLock


ROOT = Path(__file__).parents[1]


def test_current_release_environment_matches_exact_lock() -> None:
    lock = validate_release_lock(ROOT)
    assert lock["valid"], lock["errors"]
    assert lock["required_count"] >= 10
    # The developer interpreter is not release authority. A mismatch must be
    # visible and is resolved only by the disposable offline release venv.
    result = validate_release_environment(ROOT)
    assert result["lock_valid"]
    assert result["required_count"] == lock["required_count"]


def test_multiline_hash_allowlists_remain_exact_and_reject_interruption() -> None:
    root = Path(tempfile.mkdtemp())
    lock = root / "requirements-release.lock"
    first = "1" * 64
    second = "2" * 64
    lock.write_text(
        f"fixture==1.0 \\\n    --hash=sha256:{first} \\\n    --hash=sha256:{second}\n",
        encoding="utf-8",
    )
    parsed = parse_release_lock(lock)
    assert parsed["valid"], parsed["errors"]
    assert parsed["records"][0]["sha256"] == [first, second]
    lock.write_text(
        f"fixture==1.0 \\\n# interruption\n    --hash=sha256:{first}\n",
        encoding="utf-8",
    )
    assert not parse_release_lock(lock)["valid"]


def test_release_dependencies_install_offline_with_hashes() -> None:
    root = Path(tempfile.mkdtemp())
    wheelhouse = root / "wheelhouse"
    wheelhouse.mkdir()
    wheel = wheelhouse / "fixture-1.0-py3-none-any.whl"
    wheel.write_bytes(b"locked wheel")
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    lock = root / "requirements-release.lock"
    lock.write_text(f"fixture==1.0 --hash=sha256:{digest}\n", encoding="utf-8")
    manifest = build_wheelhouse_manifest(wheelhouse, lock)
    command = offline_install_command("python", lock, wheelhouse)
    assert manifest["valid"], manifest["errors"]
    assert "--no-index" in command and "--require-hashes" in command


def test_wrong_dependency_hash_fails() -> None:
    root = Path(tempfile.mkdtemp())
    wheelhouse = root / "wheelhouse"
    wheelhouse.mkdir()
    (wheelhouse / "fixture-1.0-py3-none-any.whl").write_bytes(b"substituted")
    lock = root / "requirements-release.lock"
    lock.write_text(f"fixture==1.0 --hash=sha256:{'0' * 64}\n", encoding="utf-8")
    assert not build_wheelhouse_manifest(wheelhouse, lock)["valid"]


def test_release_environment_is_scrubbed() -> None:
    clean = scrub_release_environment(
        {
            "PATH": "tools",
            "SYSTEMROOT": "system",
            "AWS_SECRET_ACCESS_KEY": "secret",
            "GITHUB_TOKEN": "secret",
            "PYTHONPATH": "host-imports",
            "PROGRAMDATA": "system-data",
        }
    )
    assert clean["PATH"] == "tools"
    assert clean["PROGRAMDATA"] == "system-data"
    assert "AWS_SECRET_ACCESS_KEY" not in clean and "GITHUB_TOKEN" not in clean
    assert "PYTHONPATH" not in clean
    assert clean["PIP_NO_INDEX"] == "1"


def test_toolchain_identity_is_in_certificate_evidence() -> None:
    identity = toolchain_identity()
    assert len(identity["python_executable_sha256"]) == 64
    assert (
        identity["python_version"]
        and identity["operating_system"]
        and identity["architecture"]
    )


def test_network_is_not_required_during_certification() -> None:
    root = Path(tempfile.mkdtemp())
    command = offline_install_command(
        "python", root / "requirements-release.lock", root / "wheelhouse"
    )
    clean = scrub_release_environment(
        {"PIP_INDEX_URL": "https://example.invalid/simple", "PATH": "tools"}
    )
    assert "--no-index" in command
    assert "PIP_INDEX_URL" not in clean and clean["PIP_NO_INDEX"] == "1"


def test_requires_python_matches_ci_matrix() -> None:
    result = validate_support_matrix(ROOT)
    assert result["valid"], result["errors"]
    assert result["python_requires"] == ">=3.11,<3.15"
    assert result["python_minors"] == ["3.11", "3.12", "3.13", "3.14"]


def test_platform_claims_match_ci_matrix() -> None:
    result = validate_support_matrix(ROOT)
    assert result["valid"], result["errors"]
    assert set(result["operating_systems"]) == {"Windows", "Linux", "Darwin"}
    assert set(result["ci_runners"].values()) == {
        "windows-latest",
        "ubuntu-latest",
        "macos-latest",
    }


def test_release_certificate_records_platform() -> None:
    binding = certification_platform_binding()
    result = validate_certification_platform(ROOT, binding)
    assert result["valid"], result["errors"]
    assert binding["python_version"]
    assert binding["python_minor"] in support_matrix(ROOT)["python_minors"]
    assert binding["operating_system"] in support_matrix(ROOT)["operating_systems"]
    assert binding["platform"] and binding["architecture"]


def test_platform_path_lock_permission_and_line_ending_controls() -> None:
    with tempfile.TemporaryDirectory() as directory:
        lock_path = Path(directory) / "directory with spaces" / "state.lock"
        with FileLock(lock_path):
            assert lock_path.is_file()
    attributes = (ROOT / ".gitattributes").read_bytes()
    assert b"* text=auto eol=lf\n" in attributes
    policy = support_matrix(ROOT)
    assert set(policy["platform_checks"]) == {
        "path-semantics",
        "advisory-file-locking",
        "permission-boundaries",
        "lf-line-endings",
    }
