"""Causal release metadata, exact Git path and product-denominator contracts."""

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

import runtime.release_identity as identity
from tests.test_release_identity_controls import _repository, _run


def surfaces(tmp_path, version="1.2.3", readme="**Current release:** v1.2.3\n"):
    (tmp_path / "runtime").mkdir(exist_ok=True)
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nversion=" + json.dumps(version) + "\n", encoding="utf-8"
    )
    (tmp_path / "runtime/version.py").write_text(
        "VERSION = " + json.dumps(version) + "\n", encoding="utf-8"
    )
    (tmp_path / "README.md").write_text(readme, encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize(
    "token",
    ["1.2.3.dev0", "1.2.3rc1", "1.2.3-alpha.1", "1.2.3garbage", "", "1.2.3+local"],
)
def test_development_readme_does_not_hide_nonstable_token(tmp_path, token):
    root = surfaces(tmp_path, "1.2.4.dev0", f"**Current release:** v{token}\n")
    assert identity.validate_version_surfaces(root)["valid"] is False


@pytest.mark.parametrize("version", ["1.2.3", "1.2.4.dev0"])
def test_complete_supported_surfaces_preserve_values(tmp_path, version):
    result = identity.validate_version_surfaces(surfaces(tmp_path, version))
    assert result["valid"] and result["authoritative_version"] == version
    assert result["readme_version"] == "1.2.3"


@pytest.mark.parametrize(
    "name,text",
    [
        ("README.md", "**Current release:** v1.2.3\n**Current release:** v1.2.3\n"),
        ("runtime/version.py", 'VERSION = "1.2.3"\nVERSION = "1.2.3"\n'),
    ],
)
def test_duplicate_version_declaration_refuses(tmp_path, name, text):
    root = surfaces(tmp_path)
    (root / name).write_text(text, encoding="utf-8")
    assert identity.validate_version_surfaces(root)["valid"] is False


@pytest.mark.parametrize("value", [1.2, True, {}, "1.2.3rc1", " 1.2.3", "1.2.3\n"])
def test_asserted_version_requires_exact_supported_type(tmp_path, value):
    with pytest.raises((ValueError, TypeError)):
        identity.validate_version_surfaces(surfaces(tmp_path), asserted=value)


def test_original_linked_version_surface_refuses(tmp_path):

    root = tmp_path / "root"
    root.mkdir()
    surfaces(root)
    external = tmp_path / "external"
    external.mkdir()
    (external / "version.py").write_text('VERSION = "1.2.3"\n')
    (root / "runtime/version.py").unlink()
    (root / "runtime").rmdir()
    if os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(external), str(root / "runtime"))
    else:
        (root / "runtime").symlink_to(external, target_is_directory=True)
    with pytest.raises((ValueError, OSError)):
        identity.validate_version_surfaces(root)


def test_metadata_budget_precedes_body(tmp_path, monkeypatch):
    root = surfaces(tmp_path)
    (root / "pyproject.toml").write_bytes(b"#" * (1024 * 1024 + 1))
    original = Path.open

    def guarded(path, *args, **kwargs):
        if path == root / "pyproject.toml":
            raise AssertionError("oversized version metadata must not be read")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded)
    with pytest.raises(ValueError):
        identity.authoritative_version(root)


@pytest.mark.parametrize(
    "path",
    [
        " leading.txt",
        "trailing.txt ",
        "both space ",
        "tab\tname",
        "line\r\nname",
        "dir/back\\slash",
    ],
)
def test_git_paths_preserve_exact_nul_identity(tmp_path, monkeypatch, path):
    monkeypatch.setattr(identity, "_git", lambda root, *args: path + "\0")
    assert identity._git_changed_paths(tmp_path) == [path]


@pytest.mark.parametrize(
    "output",
    [
        "unterminated",
        "a\0\0",
        "/absolute\0",
        "../escape\0",
        "a/../b\0",
        "a//b\0",
        "x" * 4097 + "\0",
    ],
)
def test_malformed_git_path_records_refuse(tmp_path, monkeypatch, output):
    monkeypatch.setattr(identity, "_git", lambda root, *args: output)
    with pytest.raises(ValueError):
        identity._git_changed_paths(tmp_path)


def test_raw_record_count_is_checked_before_deduplication(tmp_path, monkeypatch):
    monkeypatch.setattr(identity, "MAX_GIT_PATHS", 2, raising=False)
    monkeypatch.setattr(identity, "_git", lambda root, *args: "a\0a\0a\0")
    with pytest.raises(ValueError):
        identity._git_changed_paths(tmp_path)


def test_binary_git_acquisition_preserves_crlf_path_bytes(tmp_path, monkeypatch):
    def run(*args, **kwargs):
        assert kwargs.get("text") is not True
        return SimpleNamespace(returncode=0, stdout=b" x\r\ny \0", stderr=b"")

    monkeypatch.setattr(identity.subprocess, "run", run)
    assert identity._git(tmp_path, "ls-files", "-z") == " x\r\ny \0"


def test_git_error_is_bounded_and_does_not_reflect_stderr(tmp_path, monkeypatch):
    monkeypatch.setattr(
        identity.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(
            returncode=1, stdout=b"", stderr=b"PRIVATE-DIAGNOSTIC" * 10000
        ),
    )
    with pytest.raises(ValueError) as error:
        identity._git(tmp_path, "rev-parse", "HEAD")
    assert "PRIVATE-DIAGNOSTIC" not in str(error.value) and len(str(error.value)) < 1000


@pytest.mark.parametrize(
    "field,value",
    [
        ("tag", "--all"),
        ("tag", 7),
        ("commit_sha", "HEAD"),
        ("commit_sha", "a" * 39),
        ("tree_sha", True),
        ("repository", []),
        ("commit_sha", "A" * 40),
    ],
)
def test_bad_recorded_identity_refuses_before_git(tmp_path, monkeypatch, field, value):
    record = {
        "repository": identity.EXPECTED_REPOSITORY,
        "tag": "v1.2.3",
        "commit_sha": "a" * 40,
        "tree_sha": "b" * 40,
    }
    record[field] = value

    def forbidden(*a, **k):
        raise AssertionError("malformed recorded identity reached Git")

    monkeypatch.setattr(identity, "_git", forbidden)
    assert identity.verify_recorded_git_identity(tmp_path, record)["valid"] is False


@pytest.mark.parametrize("version", [False, 1, "", "1.2.3 --all", "1.2.3rc1"])
def test_invalid_capture_version_refuses_before_git(tmp_path, monkeypatch, version):
    def forbidden(*a, **k):
        raise AssertionError("invalid version reached Git")

    monkeypatch.setattr(identity, "_git", forbidden)
    assert identity.capture_git_identity(tmp_path, version=version)["valid"] is False


def test_ignored_product_input_is_in_release_denominator():
    root = _repository()
    _run(root, "git", "config", "core.excludesFile", ".git/owned-ignore")
    (root / ".git/owned-ignore").write_text("runtime/hidden.py\n")
    (root / "runtime/hidden.py").write_text("hidden = True\n")
    result = identity.capture_git_identity(root, version="1.2.3")
    assert result["valid"] is False and result["dirty"] is True
    assert "runtime/hidden.py" in result["dirty_paths"]


def test_ignored_mutable_control_does_not_become_product_input():
    root = _repository()
    _run(root, "git", "config", "core.excludesFile", ".git/owned-ignore")
    (root / ".git/owned-ignore").write_text("registry/control.json\n")
    (root / "registry").mkdir()
    (root / "registry/control.json").write_text('{"sequence":1}\n')
    assert identity.capture_git_identity(root, version="1.2.3")["valid"] is True


def test_exact_recorded_git_objects_preserve_historical_verification():
    root = _repository()
    captured = identity.capture_git_identity(root, version="1.2.3")
    assert captured["valid"]
    assert identity.verify_recorded_git_identity(root, captured)["valid"]


def test_significant_leading_space_is_reported_by_actual_git():
    root = _repository()
    (root / "runtime/ leading.py").write_text("value = 1\n")
    result = identity.capture_git_identity(root, version="1.2.3")
    assert result["valid"] is False
    assert result["dirty_paths"] == ["runtime/ leading.py"]


@pytest.mark.parametrize(
    "readme", ["", "**Current release:** v1.2.3\n**Current release:** vbad\n"]
)
def test_development_requires_one_real_stable_release_marker(tmp_path, readme):
    assert (
        identity.validate_version_surfaces(surfaces(tmp_path, "1.2.4.dev0", readme))[
            "valid"
        ]
        is False
    )


def test_policy_prefixes_match_directory_boundaries_without_shadowing(tmp_path):
    (tmp_path / "policies").mkdir()
    (tmp_path / "policies/release-artifact-policy.json").write_text(
        json.dumps(
            {
                "control_output_paths": [],
                "control_output_prefixes": [
                    "registry/a/",
                    "registry/a/child/",
                    "registry/b/",
                ],
            }
        )
    )
    assert identity._declared_mutable_output(tmp_path, "registry/a/z.json")
    assert identity._declared_mutable_output(tmp_path, "registry/b/x.json")
    assert not identity._declared_mutable_output(tmp_path, "registry/ab/x.json")


def test_duplicate_mutable_policy_fields_refuse(tmp_path):
    (tmp_path / "policies").mkdir()
    (tmp_path / "policies/release-artifact-policy.json").write_text(
        '{"control_output_paths":[],"control_output_paths":["runtime/hidden.py"]}'
    )
    with pytest.raises(ValueError):
        identity._declared_mutable_output(tmp_path, "runtime/hidden.py")


def test_directory_as_pyproject_does_not_fallback_to_installed_version(
    tmp_path, monkeypatch
):
    (tmp_path / "pyproject.toml").mkdir()
    monkeypatch.setattr(identity.importlib.metadata, "version", lambda *a: "1.2.3")
    with pytest.raises((ValueError, OSError)):
        identity.authoritative_version(tmp_path)


def test_missing_pyproject_preserves_installed_metadata_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(identity.importlib.metadata, "version", lambda *a: "1.2.3.dev4")
    assert identity.authoritative_version(tmp_path) == "1.2.3.dev4"


def test_unrecognized_second_runtime_assignment_refuses(tmp_path):
    root = surfaces(tmp_path)
    (root / "runtime/version.py").write_text('VERSION = "1.2.3"\nVERSION = str(9)\n')
    assert identity.validate_version_surfaces(root)["valid"] is False


def test_missing_product_policy_cannot_prove_clean_release(tmp_path, monkeypatch):
    monkeypatch.setattr(identity, "_git", lambda root, *args: "")
    with pytest.raises(ValueError):
        identity._release_dirty_state(tmp_path)


def test_classification_policy_must_match_admitted_image(tmp_path, monkeypatch):
    import runtime.release_artifacts as artifacts

    (tmp_path / "policies").mkdir()
    (tmp_path / "policies/release-artifact-policy.json").write_text(
        '{"control_output_paths":[]}'
    )
    monkeypatch.setattr(identity, "_git", lambda root, *args: "")
    monkeypatch.setattr(
        artifacts,
        "classify_tree",
        lambda root: {"valid": True, "records": [], "policy_sha256": "0" * 64},
    )
    with pytest.raises(ValueError):
        identity._release_dirty_state(tmp_path)


def provenance_arguments():
    return {
        "release": "1.2.3",
        "source_control": {
            "valid": True,
            "repository": identity.EXPECTED_REPOSITORY,
            "tag": "v1.2.3",
            "commit_sha": "a" * 40,
            "tree_sha": "b" * 40,
        },
        "product_digest": "c" * 64,
        "artifacts": [
            {"filename": "package.whl", "sha256": "d" * 64, "size_bytes": 123}
        ],
        "toolchain": {"python": "3.14.0"},
    }


def test_provenance_consumes_actual_capture_keys(tmp_path):
    from runtime.release_certification import _write_supply_chain_evidence

    root = _repository()
    arguments = provenance_arguments()
    arguments["source_control"] = identity.capture_git_identity(root, version="1.2.3")
    assert arguments["source_control"]["valid"]
    result = _write_supply_chain_evidence(tmp_path, **arguments)
    assert result == {
        "checksums": "SHA256SUMS.txt",
        "sbom": "sbom.cdx.json",
        "provenance": "provenance.intoto.json",
    }
    provenance = json.loads((tmp_path / result["provenance"]).read_text())
    dependency = provenance["predicate"]["buildDefinition"]["resolvedDependencies"][0]
    assert dependency["digest"] == {
        "gitCommit": arguments["source_control"]["commit_sha"],
        "gitTree": arguments["source_control"]["tree_sha"],
        "productSha256": "c" * 64,
    }
    assert (tmp_path / result["checksums"]).read_bytes() == (
        "d" * 64 + "  package.whl\n"
    ).encode()
    sbom = json.loads((tmp_path / result["sbom"]).read_text())
    assert sbom["components"][0]["type"] == "file"


@pytest.mark.parametrize(
    "field,value",
    [
        ("valid", False),
        ("valid", 1),
        ("commit_sha", ""),
        ("tree_sha", "HEAD"),
        ("tag", "v2.0.0"),
        ("repository", "other/repo"),
    ],
)
def test_invalid_source_binding_writes_no_provenance(tmp_path, field, value):
    from runtime.release_certification import _write_supply_chain_evidence

    arguments = provenance_arguments()
    arguments["source_control"][field] = value
    with pytest.raises((ValueError, TypeError)):
        _write_supply_chain_evidence(tmp_path, **arguments)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("filename", "../outside.whl"),
        ("filename", "x\nforged"),
        ("filename", True),
        ("sha256", "g" * 64),
        ("size_bytes", True),
        ("size_bytes", "123"),
        ("size_bytes", -1),
    ],
)
def test_invalid_artifact_metadata_writes_no_evidence(tmp_path, field, value):
    from runtime.release_certification import _write_supply_chain_evidence

    arguments = provenance_arguments()
    arguments["artifacts"][0][field] = value
    with pytest.raises((ValueError, TypeError)):
        _write_supply_chain_evidence(tmp_path, **arguments)
    assert list(tmp_path.iterdir()) == []


def test_alias_artifact_names_refuse_before_evidence_creation(tmp_path):
    from runtime.release_certification import _write_supply_chain_evidence

    arguments = provenance_arguments()
    arguments["artifacts"].append(
        {"filename": "PACKAGE.whl", "sha256": "e" * 64, "size_bytes": 123}
    )
    with pytest.raises(ValueError):
        _write_supply_chain_evidence(tmp_path, **arguments)
    assert list(tmp_path.iterdir()) == []


def test_bad_toolchain_is_rejected_before_checksum_creation(tmp_path):
    from runtime.release_certification import _write_supply_chain_evidence

    arguments = provenance_arguments()
    arguments["toolchain"] = {"number": float("nan")}
    with pytest.raises(ValueError):
        _write_supply_chain_evidence(tmp_path, **arguments)
    assert list(tmp_path.iterdir()) == []


def test_existing_provenance_outputs_are_not_overwritten(tmp_path):
    from runtime.release_certification import _write_supply_chain_evidence

    (tmp_path / "provenance.intoto.json").write_bytes(b"retained evidence")
    with pytest.raises(ValueError):
        _write_supply_chain_evidence(tmp_path, **provenance_arguments())
    assert list(tmp_path.iterdir()) == [tmp_path / "provenance.intoto.json"]
    assert (tmp_path / "provenance.intoto.json").read_bytes() == b"retained evidence"


@pytest.mark.parametrize("newline", [b"\n", b"\r\n", b"\r"])
def test_version_surface_line_endings_preserve_text_semantics(tmp_path, newline):
    root = surfaces(tmp_path)
    for relative in ["pyproject.toml", "runtime/version.py", "README.md"]:
        path = root / relative
        raw = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        path.write_bytes(raw.replace(b"\n", newline))
    result = identity.validate_version_surfaces(root)
    assert result["valid"], result["errors"]


def test_actual_packaging_manifest_preserves_authoritative_version(tmp_path):
    import tomllib

    source = Path(__file__).resolve().parents[1] / "pyproject.toml"
    raw = source.read_bytes()
    assert 65536 < len(raw) <= 1024 * 1024
    (tmp_path / "pyproject.toml").write_bytes(raw)
    expected = tomllib.loads(raw.decode("utf-8"))["project"]["version"]
    assert identity.authoritative_version(tmp_path) == expected


def test_complete_large_packaging_table_preserves_version(tmp_path):
    raw = b'[project]\nversion="1.2.3"\n[tool.setuptools.data-files]\n'
    raw += b'"share/px" = [' + b'"runtime/example.py",' * 12000 + b']\n'
    assert 65536 < len(raw) < 1024 * 1024
    (tmp_path / "pyproject.toml").write_bytes(raw)
    assert identity.authoritative_version(tmp_path) == "1.2.3"


@pytest.mark.parametrize("tail", [b'[project]\nversion="9.9.9"\n', b'broken = [\n'])
def test_large_metadata_late_invalid_declaration_is_not_truncated(tmp_path, tail):
    raw = b'[project]\nversion="1.2.3"\n' + b'# padding\n' * 10000 + tail
    (tmp_path / "pyproject.toml").write_bytes(raw)
    with pytest.raises(ValueError):
        identity.authoritative_version(tmp_path)
