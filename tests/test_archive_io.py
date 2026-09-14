"""Owned archive/input fixtures; no build backend, install or custody moves."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
from pathlib import Path
import struct
import tarfile
import zipfile

import pytest

from runtime.archive_io import (
    ArchiveLimits,
    reject_path_links,
    read_stream_bytes,
    validated_sdist,
    validated_zip,
)
from runtime.release_distribution import (
    bind_artifact_set,
    file_record,
    inspect_sdist,
    inspect_wheel,
    validate_artifact_manifest,
    verify_artifact_records,
    verify_built_artifact,
    generate_artifact_manifest,
    verify_commissioned_skill_projection,
)


def test_path_component_images_allow_regular_and_missing_descendants(tmp_path):
    regular = tmp_path / "file"
    regular.write_text("fixture", encoding="utf-8")
    for path in (tmp_path, regular, tmp_path / "missing" / "child", regular / "not-a-directory"):
        assert reject_path_links(path) is None


def test_path_component_images_reject_actual_linked_ancestor(tmp_path):
    import os

    target = tmp_path / "target"
    target.mkdir()
    linked = tmp_path / "linked"
    if os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(target), str(linked))
    else:
        linked.symlink_to(target, target_is_directory=True)
    for path in (linked, linked / "missing" / "child"):
        with pytest.raises(ValueError, match="linked"):
            reject_path_links(path)


def test_path_component_images_reject_actual_leaf_symlink(tmp_path):
    target = tmp_path / "target"
    target.write_text("fixture", encoding="utf-8")
    linked = tmp_path / "linked"
    try:
        linked.symlink_to(target)
    except OSError as error:
        pytest.skip(str(error))
    with pytest.raises(ValueError, match="linked"):
        reject_path_links(linked)


def test_path_component_images_propagate_unknown_metadata_errors(tmp_path, monkeypatch):
    def denied(path):
        raise PermissionError("unreadable path component")

    monkeypatch.setattr(Path, "lstat", denied)
    with pytest.raises(PermissionError):
        reject_path_links(tmp_path / "file")


def _wheel(tmp_path, extras=()):
    path = tmp_path / "fixture-1.2.3-py3-none-any.whl"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "fixture-1.2.3.dist-info/METADATA",
            "Metadata-Version: 2.4\nName: fixture\nVersion: 1.2.3\n",
        )
        for name, data in extras:
            archive.writestr(name, data)
    return path


def _sdist(tmp_path, extras=()):
    path = tmp_path / "fixture-1.2.3.tar.gz"
    metadata = b"Metadata-Version: 2.4\nName: fixture\nVersion: 1.2.3\n"
    with tarfile.open(path, "w:gz") as archive:
        info = tarfile.TarInfo("fixture-1.2.3/PKG-INFO")
        info.size = len(metadata)
        archive.addfile(info, io.BytesIO(metadata))
        for info, data in extras:
            archive.addfile(info, io.BytesIO(data))
    return path


def _seal(manifest):
    manifest["manifest_sha256"] = hashlib.sha256(
        json.dumps(
            {
                k: v
                for k, v in manifest.items()
                if k not in {"errors", "valid", "manifest_sha256"}
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return manifest


def _manifest():
    row = {
        "source_path": "runtime/example.py",
        "installed_path": "fixture/example.py",
        "artifact_type": "runtime-module",
        "owner": "engineering-bootstrap-runtime",
        "source_sha256": hashlib.sha256(b"").hexdigest(),
        "source_size_bytes": 0,
        "required": True,
        "package_target": "wheel",
        "designation": "authoritative",
        "generated": False,
    }
    return _seal(
        {
            "schema_version": "1.0",
            "distribution_model": "lean-runtime-wheel-complete-sdist",
            "project": "fixture",
            "version": "1.2.3",
            "records": [
                row,
                {
                    **row,
                    "package_target": "sdist",
                    "installed_path": "fixture-1.2.3/runtime/example.py",
                },
            ],
            "allowed_generated": {
                "wheel": ["fixture-1.2.3.dist-info/METADATA"],
                "sdist": ["fixture-1.2.3/PKG-INFO"],
            },
            "skill_projection": {
                "valid": True,
                "source_file_count": 0,
                "source_only_count": 0,
                "wheel_projected_count": 0,
                "sdist_projected_count": 0,
                "errors": [],
            },
            "errors": [],
            "valid": True,
        }
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "empty",
        "bool-size",
        "negative-size",
        "string-required",
        "number-generated",
        "invalid-digest",
        "unsafe-source",
        "duplicate",
        "case-alias",
        "empty-skill-proof",
    ],
)
def test_frozen_manifest_rejects_invalid_shape_even_with_recomputed_digest(mutation):
    manifest = _manifest()
    row = manifest["records"][0]
    if mutation == "empty":
        manifest["records"] = []
    elif mutation == "bool-size":
        row["source_size_bytes"] = False
    elif mutation == "negative-size":
        row["source_size_bytes"] = -1
    elif mutation == "string-required":
        row["required"] = "yes"
    elif mutation == "number-generated":
        row["generated"] = 1
    elif mutation == "invalid-digest":
        row["source_sha256"] = "not-a-digest"
    elif mutation == "unsafe-source":
        row["source_path"] = "../example.py"
    elif mutation == "duplicate":
        manifest["records"].append(dict(row))
    elif mutation == "case-alias":
        manifest["records"].append(
            {**row, "installed_path": row["installed_path"].upper()}
        )
    else:
        manifest["skill_projection"] = {}
    assert not validate_artifact_manifest(_seal(manifest))["valid"]


def test_valid_minimum_manifest_keeps_its_exact_denominator():
    result = validate_artifact_manifest(_manifest())
    assert result["valid"] and result["record_count"] == 2


def test_direct_artifact_verifier_compares_manifest_sizes_with_observed_bytes(tmp_path):
    path = _wheel(tmp_path, [("fixture/example.py", b"")])
    manifest = _manifest()
    assert verify_built_artifact(path, manifest, package_target="wheel")["valid"]
    for row in manifest["records"]:
        row["source_size_bytes"] = 7
    assert validate_artifact_manifest(_seal(manifest))["valid"]
    result = verify_built_artifact(path, manifest, package_target="wheel")
    assert not result["valid"]
    assert any("size mismatch" in error for error in result["errors"])


def test_skill_temporary_suffix_exclusion_does_not_hide_declared_package_data(tmp_path):
    root = _project(tmp_path)
    (root / "pkg/template.tmp").write_bytes(b"declared template")
    with (root / "pyproject.toml").open("a", encoding="utf-8") as stream:
        stream.write('[tool.setuptools.package-data]\nfixture=["template.tmp"]\n')
    result = generate_artifact_manifest(root)
    assert result["valid"], result["errors"]
    assert {
        row["package_target"]
        for row in result["records"]
        if row["source_path"] == "pkg/template.tmp"
    } == {"wheel", "sdist"}


@pytest.mark.parametrize(
    "name", ["pkg/A.py", "pkg/../bad.py", "pkg/bad:stream", "pkg/CON.txt"]
)
def test_wheel_rejects_portable_path_collisions_and_unsafe_names(tmp_path, name):
    path = _wheel(tmp_path, [("pkg/a.py", b"a"), (name, b"b")])
    assert not inspect_wheel(path)["valid"]


def test_wheel_rejects_unix_symlink_members(tmp_path):
    info = zipfile.ZipInfo("pkg/link")
    info.create_system = 3
    info.external_attr = 0o120777 << 16
    path = _wheel(tmp_path, [(info, b"target")])
    assert not inspect_wheel(path)["valid"]


def test_wheel_directory_size_rejection_precedes_member_decompression(
    tmp_path, monkeypatch
):
    path = _wheel(tmp_path, [("pkg/body.py", b"small")])
    raw = bytearray(path.read_bytes())
    first = raw.index(b"PK\x01\x02")
    second = raw.index(b"PK\x01\x02", first + 4)
    struct.pack_into("<I", raw, second + 24, 0x40000000)
    path.write_bytes(raw)

    def forbidden(*args, **kwargs):
        raise AssertionError("oversized directory must fail before any member opens")

    monkeypatch.setattr(zipfile.ZipFile, "open", forbidden)
    assert not inspect_wheel(path)["valid"]


def test_sdist_rejects_special_files_and_case_aliases(tmp_path):
    fifo = tarfile.TarInfo("fixture-1.2.3/fifo")
    fifo.type = tarfile.FIFOTYPE
    path = _sdist(tmp_path, [(fifo, b"")])
    assert not inspect_sdist(path)["valid"]
    one = tarfile.TarInfo("fixture-1.2.3/A.py")
    one.size = 1
    two = tarfile.TarInfo("fixture-1.2.3/a.py")
    two.size = 1
    path = _sdist(tmp_path, [(one, b"a"), (two, b"b")])
    assert not inspect_sdist(path)["valid"]


@pytest.mark.parametrize("kind", ["wheel", "sdist"])
def test_malformed_archive_returns_structured_invalid_result(tmp_path, kind):
    path = tmp_path / (
        "fixture-1.2.3-py3-none-any.whl" if kind == "wheel" else "fixture-1.2.3.tar.gz"
    )
    path.write_bytes(b"not an archive")
    result = (inspect_wheel if kind == "wheel" else inspect_sdist)(path)
    assert not result["valid"] and result["errors"]


@pytest.mark.parametrize(
    "mutation", ["empty", "unknown-type", "bool-size", "extra-file"]
)
def test_artifact_record_set_has_exact_typed_nonempty_coverage(tmp_path, mutation):
    path = tmp_path / "one.whl"
    path.write_bytes(b"x")
    rows = [file_record(path, "wheel")]
    if mutation == "empty":
        rows = []
    elif mutation == "unknown-type":
        rows[0]["type"] = "anything"
    elif mutation == "bool-size":
        rows[0]["size_bytes"] = True
    else:
        (tmp_path / "unexpected.txt").write_bytes(b"extra")
    assert not verify_artifact_records(tmp_path, rows)["valid"]


def test_invalid_manifest_stops_before_archive_access(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("invalid manifest must stop archive inspection")

    monkeypatch.setattr("runtime.release_distribution.inspect_wheel", forbidden)
    result = verify_built_artifact(tmp_path / "missing.whl", {}, package_target="wheel")
    assert not result["valid"]


def test_invalid_artifact_record_stops_binding_before_archive_access(
    tmp_path, monkeypatch
):
    wheel = _wheel(tmp_path)
    sdist = _sdist(tmp_path)
    rows = [file_record(wheel, "wheel"), file_record(sdist, "sdist")]
    rows[0]["sha256"] = "0" * 64

    def forbidden(*args, **kwargs):
        raise AssertionError("invalid records must stop archive inspection")

    monkeypatch.setattr("runtime.release_distribution.inspect_wheel", forbidden)
    result = bind_artifact_set(
        tmp_path, rows, source_product_digest="a" * 64, version="1.2.3"
    )
    assert not result["valid"]


def test_synthetic_archives_preserve_version_hash_and_set_binding(tmp_path):
    wheel = _wheel(tmp_path)
    sdist = _sdist(tmp_path)
    assert inspect_wheel(wheel)["version"] == "1.2.3"
    assert inspect_sdist(sdist)["version"] == "1.2.3"
    result = bind_artifact_set(
        tmp_path,
        [file_record(wheel, "wheel"), file_record(sdist, "sdist")],
        source_product_digest="a" * 64,
        version="1.2.3",
    )
    assert result["valid"], result["errors"]


def _project(tmp_path):
    root = tmp_path / "project"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg/__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        '[project]\nname="fixture"\nversion="1.2.3"\n[tool.setuptools]\npackages=["fixture"]\n[tool.setuptools.package-dir]\nfixture="pkg"\n',
        encoding="utf-8",
    )
    (root / "MANIFEST.in").write_text(
        "include pyproject.toml MANIFEST.in\nrecursive-include pkg *.py\n",
        encoding="utf-8",
    )
    return root


def test_skill_projection_keeps_upstream_failure_with_an_empty_source_tree(tmp_path):
    result = verify_commissioned_skill_projection(
        tmp_path,
        {"valid": False, "records": [], "errors": ["source byte budget exceeded"]},
    )
    assert result["valid"] is False
    assert result["source_evaluated"] is False
    assert "source byte budget exceeded" in " ".join(result["errors"])


def test_skill_projection_failure_precedes_dependent_source_acquisition(
    tmp_path, monkeypatch
):
    import runtime.release_distribution as distribution

    def forbidden(*args):
        raise AssertionError("an invalid producer must stop dependent acquisition")

    monkeypatch.setattr(distribution, "commissioned_skill_sources", forbidden)
    result = verify_commissioned_skill_projection(
        tmp_path, {"valid": False, "records": [], "errors": ["upstream cause"]}
    )
    assert result["valid"] is False
    assert "upstream cause" in " ".join(result["errors"])


@pytest.mark.parametrize("valid", [0, 1, None, "false"])
def test_skill_projection_refuses_untyped_producer_validity(tmp_path, valid):
    result = verify_commissioned_skill_projection(
        tmp_path, {"valid": valid, "records": [], "errors": []}
    )
    assert result["valid"] is False
    assert result["source_evaluated"] is False


def _synthetic_projection_inputs(tmp_path, monkeypatch, paths):
    from types import SimpleNamespace
    import runtime.release_distribution as distribution

    entries = [SimpleNamespace(relative=p, path=tmp_path / p, size=0) for p in paths]
    monkeypatch.setattr(
        distribution, "bounded_walk", lambda *a, **k: SimpleNamespace(files=entries)
    )
    return distribution._ProjectionInputs(tmp_path, [], {}, ArchiveLimits())


def test_projection_literal_selection_does_not_scan_unrelated_inventory(
    tmp_path, monkeypatch
):
    import runtime.release_distribution as distribution

    paths = [f"skills/skill-{i:04d}/body.md" for i in range(2000)]
    inputs = _synthetic_projection_inputs(tmp_path, monkeypatch, paths)

    def forbidden(*args, **kwargs):
        raise AssertionError("literal lookup must not invoke the wildcard matcher")

    monkeypatch.setattr(distribution, "_glob_match", forbidden)
    assert inputs.matching("SKILLS/skill-0123/body.md") == [paths[123]]
    assert inputs.matching("skills/missing/body.md") == []


def test_projection_wildcard_work_is_limited_to_its_literal_prefix(
    tmp_path, monkeypatch
):
    import runtime.release_distribution as distribution

    paths = [f"skills/skill-{i:04d}/body.md" for i in range(2000)]
    inputs = _synthetic_projection_inputs(tmp_path, monkeypatch, paths)
    original = distribution._glob_match
    calls = []

    def counted(path, pattern, **kwargs):
        calls.append(path)
        return original(path, pattern, **kwargs)

    monkeypatch.setattr(distribution, "_glob_match", counted)
    assert inputs.matching("SKILLS/skill-00??/*.md") == paths[:100]
    assert set(calls) == set(paths[:100])


def test_projection_matching_preserves_independent_component_glob_semantics(
    tmp_path, monkeypatch
):
    from pathlib import PurePosixPath

    paths = [
        "a/top.md",
        "a/deep/body.md",
        "a/deep/tail.json",
        "a/deeper/body.txt",
        "a/deep/nested/body.md",
        "elsewhere/body.md",
        "skills/Café/body.md",
    ]
    inputs = _synthetic_projection_inputs(tmp_path, monkeypatch, paths)
    for pattern in [
        "a/*.md",
        "A/**/*.MD",
        "a/deep/*",
        "a/deep/**",
        "**/body.*",
        "a/d[ae]ep/body.md",
        "a/d?ep/*.json",
        "missing/**",
        "SKILLS/CAFÉ/body.md",
        "skills/Cafe\u0301/body.md",
        "**",
    ]:
        expected = sorted(
            (
                p
                for p in paths
                if PurePosixPath(p).full_match(pattern, case_sensitive=False)
            ),
            key=lambda p: (p.casefold(), p),
        )
        assert inputs.matching(pattern) == expected, pattern


@pytest.mark.parametrize("errors", ["error", [None], ["x" * 4097], ["x"] * 1025])
def test_skill_projection_bounds_upstream_diagnostics_before_acquisition(
    tmp_path, monkeypatch, errors
):
    import runtime.release_distribution as distribution

    def forbidden(*args):
        raise AssertionError(
            "invalid upstream metadata must precede source acquisition"
        )

    monkeypatch.setattr(distribution, "commissioned_skill_sources", forbidden)
    result = verify_commissioned_skill_projection(
        tmp_path, {"valid": False, "records": [], "errors": errors}
    )
    assert result["valid"] is False and result["source_evaluated"] is False
    assert len(json.dumps(result).encode()) < 1024


def test_projection_source_hash_and_size_share_one_acquired_image(
    tmp_path, monkeypatch
):
    root = _project(tmp_path)
    body = root / "pkg/__init__.py"
    original = Path.open
    reads = []

    def counted(path, *args, **kwargs):
        if path == body:
            reads.append(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", counted)
    result = generate_artifact_manifest(root)
    assert result["valid"], result["errors"]
    assert validate_artifact_manifest(result)["valid"]
    assert len(reads) == 1


def test_projection_duplicate_destination_fails_before_source_body_reads(
    tmp_path, monkeypatch
):
    root = _project(tmp_path)
    body = root / "pkg/__init__.py"
    with (root / "pyproject.toml").open("a", encoding="utf-8") as stream:
        stream.write('[tool.setuptools.package-data]\nfixture=["__init__.py"]\n')
    original = Path.open

    def guarded(path, *args, **kwargs):
        if path == body:
            raise AssertionError(
                "duplicate projection must fail before body acquisition"
            )
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded)
    result = generate_artifact_manifest(root)
    assert not result["valid"] and result["errors"]


def test_projection_original_root_link_and_outside_directory_fail_before_acquisition(
    tmp_path, monkeypatch
):
    root = _project(tmp_path)
    linked_root = tmp_path / "linked-root"
    if __import__("os").name == "nt":
        import _winapi

        _winapi.CreateJunction(str(root), str(linked_root))
    else:
        linked_root.symlink_to(root, target_is_directory=True)
    result = generate_artifact_manifest(linked_root)
    assert not result["valid"]
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "__init__.py").write_bytes(b"fixture")
    config = root / "pyproject.toml"
    config.write_text(
        config.read_text().replace('fixture="pkg"', 'fixture="../outside"'),
        encoding="utf-8",
    )
    original_open = Path.open

    def guarded(path, *args, **kwargs):
        if path.resolve().is_relative_to(outside):
            raise AssertionError("outside source must not be read")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded)
    assert not generate_artifact_manifest(root)["valid"]


def test_source_only_skills_still_require_sdist_and_unknown_skill_projections_fail(
    tmp_path,
):
    root = _project(tmp_path)
    source = root / ".px/skills/example/SKILL.md"
    source.parent.mkdir(parents=True)
    source.write_text("# Example\n", encoding="utf-8")
    result = verify_commissioned_skill_projection(
        root, {"records": []}, source_only={".px/skills/example/SKILL.md"}
    )
    assert not result["valid"]
    assert any("sdist" in error for error in result["errors"])
    result = verify_commissioned_skill_projection(
        root,
        {
            "records": [
                {
                    "source_path": ".px/skills/unknown/SKILL.md",
                    "package_target": "sdist",
                }
            ]
        },
    )
    assert not result["valid"]
    assert any("unknown skill projection source" in error for error in result["errors"])


def test_zip_exact_limits_and_budget_rejection_before_parser(monkeypatch):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("a", b"123")
        archive.writestr("b", b"45")
    raw = stream.getvalue()
    with validated_zip(
        raw,
        ArchiveLimits(
            max_archive_bytes=len(raw),
            max_expanded_bytes=5,
            max_member_bytes=3,
            max_members=2,
        ),
    ) as (_, members):
        assert [member.file_size for member in members] == [3, 2]
    for limits in (
        ArchiveLimits(max_expanded_bytes=4),
        ArchiveLimits(max_member_bytes=2),
    ):
        with pytest.raises(ValueError, match="byte budget"):
            with validated_zip(raw, limits):
                pass

    def forbidden(*args, **kwargs):
        raise AssertionError(
            "directory/compressed budget must precede ZipFile allocation"
        )

    monkeypatch.setattr(zipfile, "ZipFile", forbidden)
    for limits in (
        ArchiveLimits(max_archive_bytes=len(raw) - 1),
        ArchiveLimits(max_members=1),
        ArchiveLimits(max_directory_bytes=1),
    ):
        with pytest.raises(ValueError, match="budget"):
            with validated_zip(raw, limits):
                pass


def test_stream_exact_zero_and_probe_limits():
    assert read_stream_bytes(io.BytesIO(), max_bytes=0, expected_size=0) == b""
    assert read_stream_bytes(io.BytesIO(b"abc"), max_bytes=3, expected_size=3) == b"abc"
    with pytest.raises(ValueError, match="byte budget"):
        read_stream_bytes(io.BytesIO(b"abcd"), max_bytes=3)
    with pytest.raises(ValueError, match="declared size"):
        read_stream_bytes(io.BytesIO(b"ab"), max_bytes=3, expected_size=3)


@pytest.mark.parametrize("archive_format", [tarfile.PAX_FORMAT, tarfile.GNU_FORMAT])
def test_sdist_admits_safe_long_names_and_rejects_expansion_before_tar_parser(
    monkeypatch, archive_format
):
    stream = io.BytesIO()
    name = "fixture-1.2.3/" + "long" * 40 + ".txt"
    with tarfile.open(fileobj=stream, mode="w:gz", format=archive_format) as archive:
        info = tarfile.TarInfo(name)
        info.size = 3
        archive.addfile(info, io.BytesIO(b"abc"))
    raw = stream.getvalue()
    expanded_size = len(gzip.decompress(raw))
    with validated_sdist(raw, ArchiveLimits(max_expanded_bytes=expanded_size)) as (
        archive,
        members,
    ):
        assert [member.name for member in members] == [name]
        with archive.extractfile(members[0]) as body:
            assert body.read() == b"abc"

    def forbidden(*args, **kwargs):
        raise AssertionError("gzip expansion budget must precede TAR parser")

    monkeypatch.setattr(tarfile, "open", forbidden)
    with pytest.raises(ValueError, match="expanded byte budget"):
        with validated_sdist(raw, ArchiveLimits(max_expanded_bytes=expanded_size - 1)):
            pass


@pytest.mark.parametrize(
    "key,value", [("size", "1"), ("GNU.sparse.size", "1"), ("path", "../escape")]
)
def test_sdist_rejects_pax_framing_and_path_overrides_before_parser(
    monkeypatch, key, value
):
    stream = io.BytesIO()
    with tarfile.open(
        fileobj=stream, mode="w:gz", format=tarfile.PAX_FORMAT
    ) as archive:
        info = tarfile.TarInfo("fixture/file")
        info.size = 1
        info.pax_headers = {key: value}
        archive.addfile(info, io.BytesIO(b"x"))

    def forbidden(*args, **kwargs):
        raise AssertionError("unsafe PAX metadata must precede TAR parser")

    monkeypatch.setattr(tarfile, "open", forbidden)
    with pytest.raises(ValueError):
        with validated_sdist(stream.getvalue()):
            pass


def test_sdist_rejects_recursive_extension_header_chain_before_parser(monkeypatch):
    info = tarfile.TarInfo("././@LongLink")
    info.type = tarfile.GNUTYPE_LONGNAME
    info.size = 2
    raw = (
        info.tobuf(format=tarfile.GNU_FORMAT) + b"a\0" + b"\0" * 510
    ) * 1100 + b"\0" * 1024
    compressed = gzip.compress(raw)

    def forbidden(*args, **kwargs):
        raise AssertionError("recursive extension header chain must precede TAR parser")

    monkeypatch.setattr(tarfile, "open", forbidden)
    with pytest.raises(ValueError, match="extension header"):
        with validated_sdist(compressed):
            pass


@pytest.mark.parametrize(
    "metadata",
    [
        "Name: fixture\nVersion: 1.2.3\nVersion: 1.2.3\n",
        "Name: fixture\nName: fixture\nVersion: 1.2.3\n",
        "Name: other\nVersion: 1.2.3\n",
    ],
)
def test_wheel_rejects_ambiguous_metadata_identity(tmp_path, metadata):
    path = tmp_path / "fixture-1.2.3-py3-none-any.whl"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("fixture-1.2.3.dist-info/METADATA", metadata)
    assert not inspect_wheel(path)["valid"]


def test_wheel_rejects_multiple_metadata_owners_before_decompression(
    tmp_path, monkeypatch
):
    path = _wheel(
        tmp_path, [("other-1.2.3.dist-info/METADATA", b"Name: other\nVersion: 1.2.3\n")]
    )
    monkeypatch.setattr(
        zipfile.ZipFile, "open", lambda *a, **k: pytest.fail("ambiguous owner opened")
    )
    assert not inspect_wheel(path)["valid"]


def test_projection_globs_respect_package_depth_and_source_manifest_recursion(tmp_path):
    root = _project(tmp_path)
    child = root / "pkg/child/nested.py"
    child.parent.mkdir()
    child.write_bytes(b"nested")
    result = generate_artifact_manifest(root)
    assert result["valid"], result["errors"]
    assert {
        row["source_path"]
        for row in result["records"]
        if row["package_target"] == "wheel"
    } == {"pkg/__init__.py"}
    assert {
        row["source_path"]
        for row in result["records"]
        if row["package_target"] == "sdist"
    } == {"pyproject.toml", "MANIFEST.in", "pkg/__init__.py", "pkg/child/nested.py"}


def test_projection_policy_is_acquired_once_and_part_of_source_budget(
    tmp_path, monkeypatch
):
    root = _project(tmp_path)
    policy = root / "policies/release-artifact-policy.json"
    policy.parent.mkdir()
    policy.write_bytes(b'{"skill_source_only": []}')
    original = Path.open
    reads = []

    def counted(path, *args, **kwargs):
        if path == policy:
            reads.append(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", counted)
    total = sum(
        path.stat().st_size
        for path in [
            policy,
            root / "pyproject.toml",
            root / "MANIFEST.in",
            root / "pkg/__init__.py",
        ]
    )
    result = generate_artifact_manifest(
        root, limits=ArchiveLimits(max_expanded_bytes=total)
    )
    assert result["valid"], result["errors"]
    assert len(reads) == 1

    def guarded(path, *args, **kwargs):
        if path == root / "pkg/__init__.py":
            pytest.fail("aggregate metadata budget must precede payload")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded)
    assert not generate_artifact_manifest(
        root, limits=ArchiveLimits(max_expanded_bytes=total - 1)
    )["valid"]


def test_projection_duplicate_package_declarations_fail_before_payload(
    tmp_path, monkeypatch
):
    root = _project(tmp_path)
    config = root / "pyproject.toml"
    config.write_text(
        config.read_text().replace(
            'packages=["fixture"]', 'packages=["fixture","fixture"]'
        )
    )
    original = Path.open

    def guarded(path, *args, **kwargs):
        if path == root / "pkg/__init__.py":
            pytest.fail("duplicate declarations must precede payload")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded)
    assert not generate_artifact_manifest(root)["valid"]


def test_projection_supports_current_release_declaration_scale(tmp_path):
    root = _project(tmp_path)
    # Current repository pyproject metadata has 1,090 data-file destinations.
    # Exercise that shape on one owned body, without generating root projections.
    (root / "shared.txt").write_bytes(b"shared")
    with (root / "pyproject.toml").open("a", encoding="utf-8") as stream:
        stream.write("[tool.setuptools.data-files]\n")
        for index in range(1090):
            stream.write(f'"share/fixture/{index}"=["shared.txt"]\n')
    result = generate_artifact_manifest(root)
    assert result["valid"], result["errors"]
    assert sum(row["package_target"] == "wheel" for row in result["records"]) == 1091
    assert (
        sum(
            row["source_path"] == "shared.txt" and row["package_target"] == "sdist"
            for row in result["records"]
        )
        == 1
    )
