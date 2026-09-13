from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import zipfile

import pytest

from runtime.release_artifacts import materialize_release_source

from runtime.release_distribution import (
    bind_artifact_set,
    build_release_artifacts_once,
    file_record,
    generate_artifact_manifest,
    install_exact_wheel,
    inspect_sdist,
    inspect_wheel,
    validate_artifact_manifest,
    verify_built_artifact,
    verify_declared_projection_duplicates,
    verify_artifact_records,
)


ROOT = Path(__file__).parents[1]
BUILD_TIMEOUT_SECONDS = 480


@pytest.fixture(scope="module")
def built_distribution(tmp_path_factory):
    temporary = tmp_path_factory.mktemp("artifact-manifest")
    source = temporary / "source"
    materialize_release_source(ROOT, source)
    output = temporary / "dist"
    output.mkdir()
    process = subprocess.run(
        [
            sys.executable,
            "-m",
            "build",
            "--no-isolation",
            "--wheel",
            "--sdist",
            "--outdir",
            str(output),
        ],
        cwd=source,
        text=True,
        capture_output=True,
        timeout=BUILD_TIMEOUT_SECONDS,
    )
    assert process.returncode == 0, process.stdout + process.stderr
    manifest = generate_artifact_manifest(source)
    return source, next(output.glob("*.whl")), next(output.glob("*.tar.gz")), manifest


def _modified_wheel(
    source: Path,
    destination: Path,
    *,
    omit: str | None = None,
    extra: str | None = None,
) -> Path:
    with (
        zipfile.ZipFile(source) as original,
        zipfile.ZipFile(destination, "w") as changed,
    ):
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
        archive.writestr(
            f"engineering_loop_bootstrap-{version}.dist-info/METADATA",
            f"Metadata-Version: 2.4\nName: engineering-loop-bootstrap\nVersion: {version}\n",
        )
    sdist = root / f"engineering_loop_bootstrap-{version}.tar.gz"
    with tarfile.open(sdist, "w:gz") as archive:
        data = f"Metadata-Version: 2.4\nName: engineering-loop-bootstrap\nVersion: {version}\n".encode()
        info = tarfile.TarInfo(f"engineering_loop_bootstrap-{version}/PKG-INFO")
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))
    return [file_record(wheel, "wheel"), file_record(sdist, "sdist")]


def test_artifact_manifest_projects_declared_package_data() -> None:
    manifest = generate_artifact_manifest(ROOT)
    matching = [
        record
        for record in manifest["records"]
        if record["source_path"] == "runtime/studio_operations.json"
    ]
    assert manifest["valid"], manifest["errors"]
    assert {
        (record["package_target"], record["installed_path"])
        for record in matching
    } == {
        ("wheel", "engineering_bootstrap/studio_operations.json"),
        (
            "sdist",
            "engineering_loop_bootstrap-0.7.0/runtime/studio_operations.json",
        ),
    }


def test_release_build_occurs_once() -> None:
    root = Path(tempfile.mkdtemp())
    output = root / "artifacts"
    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        _artifact_set(output)
        return subprocess.CompletedProcess(command, 0, "", "")

    result = build_release_artifacts_once(
        root, output, python_executable="python", environment={}, runner=runner
    )
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
        root,
        output,
        python_executable="python",
        environment={},
        intermediate_quarantine=custody,
        runner=runner,
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
    monkeypatch.setattr(
        "runtime.release_distribution.venv.EnvBuilder.create",
        lambda self, target: Path(target).mkdir(parents=True),
    )
    monkeypatch.setenv("SYSTEMROOT", r"C:\Windows")
    monkeypatch.setenv("WINDIR", r"C:\Windows")
    monkeypatch.setenv("PROGRAMDATA", r"C:\ProgramData")
    monkeypatch.setenv("GITHUB_TOKEN", "must-not-cross-boundary")
    calls = []
    environments = []

    def runner(command, **kwargs):
        calls.append(command)
        environments.append(kwargs["env"])
        return subprocess.CompletedProcess(command, 0, "", "")

    result = install_exact_wheel(wheel, expected, root / "venv", runner=runner)
    assert result["valid"]
    assert result["installed_wheel_sha256"] == expected
    assert str(wheel.resolve()) in calls[0]
    assert environments[0]["SYSTEMROOT"] == r"C:\Windows"
    assert environments[0]["WINDIR"] == r"C:\Windows"
    assert environments[0]["PROGRAMDATA"] == r"C:\ProgramData"
    assert "GITHUB_TOKEN" not in environments[0]
    assert environments[0]["PIP_NO_INDEX"] == "1"


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
    result = bind_artifact_set(
        root, records, source_product_digest="a" * 64, version="1.2.3"
    )
    assert result["valid"], result["errors"]
    assert result["source_product_digest"] == "a" * 64


def test_wheel_metadata_version_matches_tag() -> None:
    root = Path(tempfile.mkdtemp())
    records = _artifact_set(root)
    result = bind_artifact_set(
        root, records, source_product_digest="a" * 64, version="1.2.4"
    )
    assert not result["valid"]
    assert any("wheel metadata version" in error for error in result["errors"])


def test_sdist_metadata_version_matches_tag() -> None:
    root = Path(tempfile.mkdtemp())
    records = _artifact_set(root)
    result = bind_artifact_set(
        root, records, source_product_digest="a" * 64, version="1.2.4"
    )
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


def test_frozen_artifact_manifest_remains_authoritative_after_live_state_changes(
    built_distribution,
) -> None:
    source, wheel, sdist, manifest = built_distribution
    records = [file_record(wheel, "wheel"), file_record(sdist, "sdist")]
    build_time = bind_artifact_set(
        wheel.parent,
        records,
        source_product_digest="a" * 64,
        version="0.7.0",
        source_root=source,
    )
    mutable = source / "runtime/studio_operations.json"
    original = mutable.read_bytes()
    mutable.write_bytes(original + b"\n")
    try:
        live_manifest = generate_artifact_manifest(source)
    finally:
        mutable.write_bytes(original)
    result = bind_artifact_set(
        wheel.parent,
        records,
        source_product_digest="a" * 64,
        version="0.7.0",
        artifact_manifest=manifest,
    )

    assert build_time["valid"], build_time["errors"]
    assert build_time["artifact_manifest_sha256"] == manifest["manifest_sha256"]
    assert live_manifest["manifest_sha256"] != manifest["manifest_sha256"]
    assert result["valid"], result["errors"]
    assert result["artifact_manifest_sha256"] == manifest["manifest_sha256"]


def test_tampered_frozen_artifact_manifest_fails_intrinsic_digest_check(
    built_distribution,
) -> None:
    _, wheel, sdist, manifest = built_distribution
    changed = json.loads(json.dumps(manifest))
    changed["records"][0]["source_sha256"] = "0" * 64
    records = [file_record(wheel, "wheel"), file_record(sdist, "sdist")]

    result = bind_artifact_set(
        wheel.parent,
        records,
        source_product_digest="a" * 64,
        version="0.7.0",
        artifact_manifest=changed,
    )

    assert not validate_artifact_manifest(changed)["valid"]
    assert not result["valid"]
    assert "artifact manifest intrinsic digest mismatch" in result["errors"]


def test_artifact_manifest_authority_must_not_be_ambiguous(
    built_distribution,
) -> None:
    source, wheel, sdist, manifest = built_distribution
    records = [file_record(wheel, "wheel"), file_record(sdist, "sdist")]

    result = bind_artifact_set(
        wheel.parent,
        records,
        source_product_digest="a" * 64,
        version="0.7.0",
        source_root=source,
        artifact_manifest=manifest,
    )

    assert not result["valid"]
    assert "artifact manifest authority is ambiguous" in result["errors"]


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
    assert any(
        "required wheel resource is missing" in error for error in result["errors"]
    )


def test_undeclared_package_file_fails_build(built_distribution, tmp_path) -> None:
    _, wheel, _, manifest = built_distribution
    changed = _modified_wheel(
        wheel, tmp_path / wheel.name, extra="engineering_bootstrap/undeclared.py"
    )
    result = verify_built_artifact(changed, manifest, package_target="wheel")
    assert not result["valid"]
    assert (
        "undeclared wheel file: engineering_bootstrap/undeclared.py" in result["errors"]
    )


def test_declared_projection_duplicates_match_expected_hashes(
    built_distribution,
) -> None:
    _, wheel, sdist, manifest = built_distribution
    wheel_entries = {item["path"]: item for item in inspect_wheel(wheel)["entries"]}
    sdist_entries = {item["path"]: item for item in inspect_sdist(sdist)["entries"]}
    result = verify_declared_projection_duplicates(
        manifest, wheel_entries, sdist_entries
    )
    assert result["valid"], result["errors"]
    assert result["duplicate_source_count"] > 0


def test_runtime_wheel_contains_only_declared_distribution_classes(
    built_distribution,
) -> None:
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


def test_runtime_install_requires_only_declared_runtime_dependencies(
    built_distribution,
) -> None:
    _, wheel, _, _ = built_distribution
    inspected = inspect_wheel(wheel)
    names = {item["path"] for item in inspected["entries"]}
    assert not any(
        ".data/data/share/engineering-bootstrap/tests/" in name for name in names
    )
    with zipfile.ZipFile(wheel) as archive:
        metadata_name = next(
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        )
        metadata = archive.read(metadata_name).decode("utf-8")
    unconditional = [
        line
        for line in metadata.splitlines()
        if line.startswith("Requires-Dist:") and "extra ==" not in line
    ]
    assert unconditional == ["Requires-Dist: PyYAML==6.0.3"]


def test_certificate_version_matches_artifact_version() -> None:
    root = Path(tempfile.mkdtemp())
    records = _artifact_set(root, version="1.2.3")
    assert bind_artifact_set(
        root, records, source_product_digest="a" * 64, version="1.2.3"
    )["valid"]
    assert not bind_artifact_set(
        root, records, source_product_digest="a" * 64, version="1.2.4"
    )["valid"]


def _control_projection_fixture(root):
    (root / 'pkg').mkdir()
    (root / 'pkg/__init__.py').write_text('VALUE = 1\n')
    (root / 'registry/deltas').mkdir(parents=True)
    (root / 'registry/product.json').write_text('{}')
    (root / 'registry/current.json').write_text('{}')
    (root / 'policies').mkdir()
    (root / 'policies/release-artifact-policy.json').write_text(json.dumps(dict(
        control_output_paths=['registry/current.json'], control_output_prefixes=['registry/deltas/'])))
    (root / 'pyproject.toml').write_text('[build-system]\nrequires=["setuptools", "wheel"]\nbuild-backend="setuptools.build_meta"\n'
        '[project]\nname="capture-fixture"\nversion="1.0.0"\nlicense-files=[]\n'
        '[tool.setuptools]\npackages=["pkg"]\ninclude-package-data=false\n'
        '[tool.setuptools.package-dir]\n""="."\n'
        '[tool.setuptools.data-files]\n"share/fixture"=["registry/product.json"]\n')
    (root / 'MANIFEST.in').write_text('recursive-include pkg *.py\nrecursive-include registry *.json\n'
        'include policies/release-artifact-policy.json\nexclude registry/current.json\nprune registry/deltas\n')


def test_control_subtree_is_pruned_before_projection_budget(tmp_path, monkeypatch):
    import runtime.release_distribution as owner
    import os
    _control_projection_fixture(tmp_path)
    (tmp_path / 'registry/deltas/oversized.json').write_bytes(b'x' * 1024)
    scandir = os.scandir
    def bounded(path):
        if Path(path) == tmp_path / 'registry/deltas':
            raise AssertionError('control subtree was enumerated')
        return scandir(path)
    monkeypatch.setattr(os, 'scandir', bounded)
    result = owner.generate_artifact_manifest(tmp_path)
    assert result['valid'], result['errors']
    paths = {r['source_path'] for r in result['records']}
    assert 'registry/product.json' in paths
    assert not any(p.startswith('registry/deltas/') or p == 'registry/current.json' for p in paths)


@pytest.mark.parametrize('pattern', ['registry/*.json', 'registry/deltas/*.json', 'registry/**/*.json'])
def test_required_wheel_control_overlap_refuses_before_traversal(tmp_path, monkeypatch, pattern):
    import runtime.release_distribution as owner
    _control_projection_fixture(tmp_path)
    path = tmp_path / 'pyproject.toml'
    path.write_text(path.read_text().replace('registry/product.json', pattern))
    def refuse(*args, **kwargs):
        raise AssertionError('traversal before declaration refusal')
    monkeypatch.setattr(owner, 'bounded_walk', refuse)
    result = owner.generate_artifact_manifest(tmp_path)
    assert not result['valid'] and any('wheel declaration intersects' in error for error in result['errors'])


def test_manifest_reinclude_is_ordered_and_control_reinclude_refuses(tmp_path):
    import runtime.release_distribution as owner
    _control_projection_fixture(tmp_path)
    path = tmp_path / 'MANIFEST.in'
    path.write_text(path.read_text() + 'exclude registry/product.json\ninclude registry/product.json\n')
    assert owner.generate_artifact_manifest(tmp_path)['valid']
    path.write_text(path.read_text() + 'recursive-include registry/deltas *.json\n')
    result = owner.generate_artifact_manifest(tmp_path)
    assert not result['valid'] and any('complete mutable control subtree' in error for error in result['errors'])


def test_alternate_manifest_helper_uses_ordered_rules(tmp_path):
    from runtime.release_distribution import _manifest_sources
    _control_projection_fixture(tmp_path)
    sources = _manifest_sources(tmp_path, tmp_path / 'MANIFEST.in')
    assert tmp_path / 'registry/product.json' in sources
    assert tmp_path / 'registry/current.json' not in sources


def test_explicit_sdist_exclusion_of_required_wheel_source_refuses(tmp_path):
    _control_projection_fixture(tmp_path)
    path = tmp_path / 'MANIFEST.in'
    path.write_text(path.read_text() + 'exclude registry/product.json\n')
    result = generate_artifact_manifest(tmp_path)
    assert not result['valid'] and any('excludes a required wheel source' in e for e in result['errors'])


def test_synthetic_backend_direct_and_sdist_wheel_match_projection(tmp_path):
    import os
    from runtime.test_runner import run_test_command
    source = tmp_path / 'source'
    source.mkdir()
    _control_projection_fixture(source)
    (source / 'registry/deltas/preserve.json').write_text('{"control":true}')
    manifest = generate_artifact_manifest(source)
    assert manifest['valid'], manifest['errors']
    output = tmp_path / 'artifacts'
    output.mkdir()
    environment = {k:v for k,v in os.environ.items() if k != 'PYTHONPATH' and not k.startswith('PX_LIFECYCLE_')}
    environment.update(PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8')
    result = run_test_command([sys.executable, '-m', 'build', '--no-isolation', '--wheel', '--sdist', '--outdir', str(output)],
        cwd=source, environment=environment, timeout_seconds=90, run_id='synthetic-distribution-direct', lane_id='distribution-fixture', manage_process_temp=True)
    assert result['valid'], result.get('stdout', '') + result.get('stderr', '')
    wheel = next(output.glob('*.whl'))
    sdist = next(output.glob('*.tar.gz'))
    for artifact, target in [(wheel, 'wheel'), (sdist, 'sdist')]:
        checked = verify_built_artifact(artifact, manifest, package_target=target)
        assert checked['valid'], checked['errors']
    restored = tmp_path / 'restored'
    restored.mkdir()
    with tarfile.open(sdist) as archive:
        archive.extractall(restored, filter='data')
    unpacked = next(restored.iterdir())
    rebuilt = tmp_path / 'rebuilt'
    rebuilt.mkdir()
    result = run_test_command([sys.executable, '-m', 'build', '--no-isolation', '--wheel', '--outdir', str(rebuilt)],
        cwd=unpacked, environment=environment, timeout_seconds=90, run_id='synthetic-distribution-from-sdist', lane_id='distribution-fixture', manage_process_temp=True)
    assert result['valid'], result.get('stdout', '') + result.get('stderr', '')
    checked = verify_built_artifact(next(rebuilt.glob('*.whl')), manifest, package_target='wheel')
    assert checked['valid'], checked['errors']
    assert (source / 'registry/deltas/preserve.json').read_text() == '{"control":true}'


"""Unexecuted cases to integrate into test_release_distribution_controls."""


def test_operational_ledger_producer_files_are_declared_control_outputs():
    import json
    import tomllib
    from pathlib import Path
    from runtime.operational_gap_ledger import LEDGER_RELATIVE, SNAPSHOT_RELATIVE
    from runtime.release_distribution import _manifest_rules, _manifest_selected

    root = Path(__file__).resolve().parents[1]
    policy = json.loads((root / 'policies/release-artifact-policy.json').read_bytes())
    expected = {LEDGER_RELATIVE.as_posix(), SNAPSHOT_RELATIVE.as_posix()}
    assert expected <= set(policy['control_output_paths'])
    rules = _manifest_rules((root / 'MANIFEST.in').read_text(encoding='utf-8'))
    assert all(not _manifest_selected(name, rules) for name in expected)
    packaging = tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8'))
    data = packaging['tool']['setuptools']['data-files']
    assert not expected.intersection(name for files in data.values() for name in files)


def test_exact_ledger_control_exclusions_preserve_neighboring_product(tmp_path):
    import json
    from runtime.release_distribution import generate_artifact_manifest
    # Integrate beside the existing synthetic projection fixture.
    _control_projection_fixture(tmp_path)
    policy_path = tmp_path / 'policies/release-artifact-policy.json'
    policy = json.loads(policy_path.read_bytes())
    controls = ['registry/operational_gap_ledger.jsonl', 'registry/operational_gap_ledger.snapshot.json']
    policy['control_output_paths'].extend(controls)
    policy_path.write_text(json.dumps(policy), encoding='utf-8')
    manifest = tmp_path / 'MANIFEST.in'
    manifest.write_text(manifest.read_text() + '\nrecursive-include registry *.jsonl\n' +
                        ''.join('exclude ' + name + '\n' for name in controls) + 'prune registry/deltas\n')
    for name in controls:
        (tmp_path / name).write_text('retained operational data', encoding='utf-8')
    neighbor = 'registry/operational_gap_ledger.snapshot-extra.json'
    (tmp_path / neighbor).write_text('{}', encoding='utf-8')
    result = generate_artifact_manifest(tmp_path)
    assert result['valid'], result['errors']
    selected = {row['source_path'] for row in result['records']}
    assert not selected.intersection(controls)
    assert neighbor in selected
    assert all((tmp_path / name).read_text() == 'retained operational data' for name in controls)


@pytest.mark.parametrize('skill', ['quarantine-external-tools', 'quarantine-review', 'prequarantine-check'])
def test_authored_quarantine_named_skill_is_projected(tmp_path, skill):
    import runtime.release_distribution as owner
    _control_projection_fixture(tmp_path)
    relative = f'.px/skills/{skill}/capability.json'
    source = tmp_path / relative
    source.parent.mkdir(parents=True)
    source.write_text('{}')
    project = tmp_path / 'pyproject.toml'
    project.write_text(project.read_text() + f'"share/engineering-bootstrap/.px/skills/{skill}"=["{relative}"]\n')
    manifest = tmp_path / 'MANIFEST.in'
    manifest.write_text(manifest.read_text() + f'include {relative}\n')
    result = owner.generate_artifact_manifest(tmp_path)
    assert result['valid'], result['errors']
    assert relative in {row['source_path'] for row in result['records']}


@pytest.mark.parametrize('custody', ['quarantine', '.quarantine', '_quarantine', 'repo_quarantine', 'Quarantine'])
def test_actual_quarantine_directory_is_pruned_without_enumeration(tmp_path, monkeypatch, custody):
    import os
    import runtime.release_distribution as owner
    _control_projection_fixture(tmp_path)
    hidden = tmp_path / 'registry' / custody
    hidden.mkdir()
    (hidden / 'retained.json').write_text('{}')
    scandir = os.scandir
    def refuse_custody(path):
        if Path(path) == hidden:
            raise AssertionError('quarantine contents were enumerated')
        return scandir(path)
    monkeypatch.setattr(os, 'scandir', refuse_custody)
    result = owner.generate_artifact_manifest(tmp_path)
    assert result['valid'], result['errors']
    assert not any(f'/{custody}/' in row['source_path'] for row in result['records'])
