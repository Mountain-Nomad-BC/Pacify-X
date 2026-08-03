from __future__ import annotations

import hashlib
import io
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile

import pytest

from runtime.release_distribution import (
    bind_artifact_set,
    build_release_artifacts_once,
    file_record,
    generate_artifact_manifest,
    install_exact_wheel,
    inspect_sdist,
    inspect_wheel,
    verify_built_artifact,
    verify_declared_projection_duplicates,
    verify_artifact_records,
)


ROOT = Path(__file__).parents[1]


@pytest.fixture(scope="module")
def built_distribution(tmp_path_factory):
    temporary = tmp_path_factory.mktemp("artifact-manifest")
    source = temporary / "source"
    shutil.copytree(
        ROOT,
        source,
        ignore=shutil.ignore_patterns(
            ".git", "__pycache__", ".pytest_cache", ".ruff_cache",
            "*.pyc", "*.pyo", "*.egg-info", "build", "dist",
        ),
    )
    output = temporary / "dist"
    output.mkdir()
    process = subprocess.run(
        [sys.executable, "-m", "build", "--no-isolation", "--wheel", "--sdist", "--outdir", str(output)],
        cwd=source,
        text=True,
        capture_output=True,
        timeout=300,
    )
    assert process.returncode == 0, process.stdout + process.stderr
    manifest = generate_artifact_manifest(source)
    return source, next(output.glob("*.whl")), next(output.glob("*.tar.gz")), manifest


def _modified_wheel(source: Path, destination: Path, *, omit: str | None = None, extra: str | None = None) -> Path:
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(destination, "w") as changed:
        for item in original.infolist():
            if item.filename != omit:
                changed.writestr(item, original.read(item))
        if extra is not None:
            changed.writestr(extra, b"undeclared\n")
    return destination


def _artifact_set(root: Path, version: str = "1.2.3") -> list[dict]:
    wheel = root / f"engineering_loop_bootstrap-{version}-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("engineering_bootstrap/__init__.py", "")
        archive.writestr(f"engineering_loop_bootstrap-{version}.dist-info/METADATA", f"Metadata-Version: 2.4\nVersion: {version}\n")
    sdist = root / f"engineering_loop_bootstrap-{version}.tar.gz"
    with tarfile.open(sdist, "w:gz") as archive:
        data = f"Metadata-Version: 2.4\nVersion: {version}\n".encode()
        info = tarfile.TarInfo(f"engineering_loop_bootstrap-{version}/PKG-INFO")
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))
    return [file_record(wheel, "wheel"), file_record(sdist, "sdist")]


def test_release_build_occurs_once() -> None:
    root = Path(tempfile.mkdtemp())
    output = root / "artifacts"
    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        _artifact_set(output)
        return subprocess.CompletedProcess(command, 0, "", "")

    result = build_release_artifacts_once(root, output, python_executable="python", environment={}, runner=runner)
    assert result["valid"], result["errors"]
    assert result["build_invocations"] == len(calls) == 1


def test_release_build_intermediates_move_to_recoverable_custody() -> None:
    root = Path(tempfile.mkdtemp())
    output = root.parent / f"{root.name}-artifacts"
    custody = root.parent / f"{root.name}-build-custody"

    def runner(command, **kwargs):
        _artifact_set(output)
        generated = root / "build/lib"
        generated.mkdir(parents=True)
        (generated / "copied.py").write_text("generated = True\n", encoding="utf-8")
        metadata = root / "engineering_loop_bootstrap.egg-info"
        metadata.mkdir()
        (metadata / "PKG-INFO").write_text("Version: 1.2.3\n", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    result = build_release_artifacts_once(
        root, output, python_executable="python", environment={},
        intermediate_quarantine=custody, runner=runner,
    )
    assert result["valid"], result["errors"]
    assert result["intermediate_custody"]["hard_delete"] is False
    assert result["intermediate_custody"]["file_count"] == 2
    assert not (root / "build").exists()
    assert not (root / "engineering_loop_bootstrap.egg-info").exists()
    assert (custody / "build/lib/copied.py").is_file()
    assert (custody / "engineering_loop_bootstrap.egg-info/PKG-INFO").is_file()
    assert (custody / "receipt.json").is_file()


def test_certification_installs_exact_built_wheel(monkeypatch) -> None:
    root = Path(tempfile.mkdtemp())
    wheel = root / "fixture.whl"
    wheel.write_bytes(b"exact-wheel-bytes")
    expected = hashlib.sha256(wheel.read_bytes()).hexdigest()
    monkeypatch.setattr("runtime.release_distribution.venv.EnvBuilder.create", lambda self, target: Path(target).mkdir(parents=True))
    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    result = install_exact_wheel(wheel, expected, root / "venv", runner=runner)
    assert result["valid"]
    assert result["installed_wheel_sha256"] == expected
    assert str(wheel.resolve()) in calls[0]


def test_artifact_byte_change_revokes_certificate() -> None:
    root = Path(tempfile.mkdtemp())
    records = _artifact_set(root)
    (root / records[0]["filename"]).write_bytes(b"changed")
    assert not verify_artifact_records(root, records)["valid"]


def test_published_artifact_hash_matches_certificate() -> None:
    root = Path(tempfile.mkdtemp())
    records = _artifact_set(root)
    assert verify_artifact_records(root, records)["valid"]


def test_sdist_and_wheel_are_bound_to_same_source_snapshot() -> None:
    root = Path(tempfile.mkdtemp())
    records = _artifact_set(root)
    result = bind_artifact_set(root, records, source_product_digest="a" * 64, version="1.2.3")
    assert result["valid"], result["errors"]
    assert result["source_product_digest"] == "a" * 64


def test_wheel_metadata_version_matches_tag() -> None:
    root = Path(tempfile.mkdtemp())
    records = _artifact_set(root)
    result = bind_artifact_set(root, records, source_product_digest="a" * 64, version="1.2.4")
    assert not result["valid"]
    assert any("wheel metadata version" in error for error in result["errors"])


def test_sdist_metadata_version_matches_tag() -> None:
    root = Path(tempfile.mkdtemp())
    records = _artifact_set(root)
    result = bind_artifact_set(root, records, source_product_digest="a" * 64, version="1.2.4")
    assert not result["valid"]
    assert any("sdist metadata version" in error for error in result["errors"])


def test_wheel_matches_generated_artifact_manifest(built_distribution) -> None:
    _, wheel, _, manifest = built_distribution
    result = verify_built_artifact(wheel, manifest, package_target="wheel")
    assert result["valid"], result["errors"]


def test_sdist_matches_generated_artifact_manifest(built_distribution) -> None:
    _, _, sdist, manifest = built_distribution
    result = verify_built_artifact(sdist, manifest, package_target="sdist")
    assert result["valid"], result["errors"]


def test_required_resource_omission_fails_build(built_distribution, tmp_path) -> None:
    _, wheel, _, manifest = built_distribution
    required = next(
        record["installed_path"]
        for record in manifest["records"]
        if record["package_target"] == "wheel"
        and record["artifact_type"] == "skill-resource"
        and record["installed_path"].endswith("/SKILL.md")
    )
    changed = _modified_wheel(wheel, tmp_path / wheel.name, omit=required)
    result = verify_built_artifact(changed, manifest, package_target="wheel")
    assert not result["valid"]
    assert any("required wheel resource is missing" in error for error in result["errors"])


def test_undeclared_package_file_fails_build(built_distribution, tmp_path) -> None:
    _, wheel, _, manifest = built_distribution
    changed = _modified_wheel(wheel, tmp_path / wheel.name, extra="engineering_bootstrap/undeclared.py")
    result = verify_built_artifact(changed, manifest, package_target="wheel")
    assert not result["valid"]
    assert "undeclared wheel file: engineering_bootstrap/undeclared.py" in result["errors"]


def test_declared_projection_duplicates_match_expected_hashes(built_distribution) -> None:
    _, wheel, sdist, manifest = built_distribution
    wheel_entries = {item["path"]: item for item in inspect_wheel(wheel)["entries"]}
    sdist_entries = {item["path"]: item for item in inspect_sdist(sdist)["entries"]}
    result = verify_declared_projection_duplicates(manifest, wheel_entries, sdist_entries)
    assert result["valid"], result["errors"]
    assert result["duplicate_source_count"] > 0


def test_runtime_wheel_contains_only_declared_distribution_classes(built_distribution) -> None:
    _, wheel, _, manifest = built_distribution
    result = verify_built_artifact(wheel, manifest, package_target="wheel")
    assert result["valid"], result["errors"]
    assert "release-testkit" not in result["distribution_classes"]
    assert "release-build-control" not in result["distribution_classes"]


def test_mirrored_runtime_source_matches_importable_package(built_distribution) -> None:
    _, wheel, _, _ = built_distribution
    names = {item["path"] for item in inspect_wheel(wheel)["entries"]}
    forbidden = (
        ".data/data/share/engineering-bootstrap/runtime/",
        ".data/data/share/engineering-bootstrap/builders/",
    )
    assert not any(any(marker in name for marker in forbidden) for name in names)


def test_runtime_install_does_not_require_release_testkit(built_distribution) -> None:
    _, wheel, _, _ = built_distribution
    inspected = inspect_wheel(wheel)
    names = {item["path"] for item in inspected["entries"]}
    assert not any(".data/data/share/engineering-bootstrap/tests/" in name for name in names)
    with zipfile.ZipFile(wheel) as archive:
        metadata_name = next(name for name in archive.namelist() if name.endswith(".dist-info/METADATA"))
        metadata = archive.read(metadata_name).decode("utf-8")
    unconditional = [line for line in metadata.splitlines() if line.startswith("Requires-Dist:") and "extra ==" not in line]
    assert unconditional == []


def test_certificate_version_matches_artifact_version() -> None:
    root = Path(tempfile.mkdtemp())
    records = _artifact_set(root, version="1.2.3")
    assert bind_artifact_set(root, records, source_product_digest="a" * 64, version="1.2.3")["valid"]
    assert not bind_artifact_set(root, records, source_product_digest="a" * 64, version="1.2.4")["valid"]
