from pathlib import Path

from runtime.python_surface_certification import certify_python_surfaces


def test_repository_local_interpreters_are_dependencies_not_owned_source(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='fixture'\nversion='1.0'\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_owned.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    (tmp_path / "runtime").mkdir()
    (tmp_path / "runtime" / "owned.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "conftest.py").write_text(
        "def pytest_configure(config):\n    return None\n", encoding="utf-8"
    )
    (tmp_path / ".venv-certify" / "Lib" / "site-packages").mkdir(parents=True)
    (tmp_path / ".venv-certify" / "Lib" / "site-packages" / "foreign.py").write_text("VALUE = 2\n", encoding="utf-8")
    (tmp_path / "Python" / "Lib").mkdir(parents=True)
    (tmp_path / "Python" / "Lib" / "foreign.py").write_text("VALUE = 3\n", encoding="utf-8")
    atlas_tools = tmp_path / "docs" / "architecture" / "tools"
    atlas_tools.mkdir(parents=True)
    for name in ("build_atlas.py", "verify_atlas_browser.py", "verify_obsidian_native.py"):
        (atlas_tools / name).write_text("VALUE = 4\n", encoding="utf-8")

    result = certify_python_surfaces(
        tmp_path,
        {"results": [], "wrapper_results": []},
        require_map_current=False,
    )

    paths = {record["path"] for record in result["records"]}
    assert paths == {
        "conftest.py", "runtime/owned.py", "tests/test_owned.py",
        "docs/architecture/tools/build_atlas.py",
        "docs/architecture/tools/verify_atlas_browser.py",
        "docs/architecture/tools/verify_obsidian_native.py",
    }
    assert result["role_counts"].get("unknown", 0) == 0
    harness = next(record for record in result["records"] if record["path"] == "conftest.py")
    assert harness["role"] == "release-test-harness"
    assert harness["validation_level"] == "executable-test"
    assert harness["packaged"] is False
    atlas = {
        record["path"]: record
        for record in result["records"]
        if record["path"].startswith("docs/architecture/tools/")
    }
    assert atlas["docs/architecture/tools/build_atlas.py"]["role"] == "source-build-control"
    assert all(record["packaged"] is False for record in atlas.values())


def test_px_pycert_surfaces_are_project_certification_control_not_unknown(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='fixture'\nversion='1.0'\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_dummy.py").write_text("def test_ok():\n    pass\n", encoding="utf-8")
    (tmp_path / "px" / "py_cert" / "runtime").mkdir(parents=True)
    (tmp_path / "px" / "py_cert" / "scripts").mkdir(parents=True)
    (tmp_path / "px" / "py_cert" / "runtime" / "pre_cert_contract.py").write_text("SCHEMA = '1.0'\n", encoding="utf-8")
    (tmp_path / "px" / "py_cert" / "scripts" / "run_pre_cert_repository_convergence.py").write_text("def run():\n    pass\n", encoding="utf-8")

    result = certify_python_surfaces(
        tmp_path,
        {"results": [], "wrapper_results": []},
        require_map_current=False,
    )

    records = {record["path"]: record for record in result["records"]}
    assert "px/py_cert/runtime/pre_cert_contract.py" in records
    assert "px/py_cert/scripts/run_pre_cert_repository_convergence.py" in records

    cert_runtime = records["px/py_cert/runtime/pre_cert_contract.py"]
    cert_script = records["px/py_cert/scripts/run_pre_cert_repository_convergence.py"]

    assert cert_runtime["role"] == "source-certification-control"
    assert cert_runtime["owner"] == "project-certification-control"
    assert cert_runtime["packaged"] is False

    assert cert_script["role"] == "source-certification-control"
    assert cert_script["owner"] == "project-certification-control"
    assert cert_script["packaged"] is False

    assert result["role_counts"].get("unknown", 0) == 0


def test_malformed_semantic_code_fixture_does_not_fail_surface_certification(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='fixture'\nversion='1.0'\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_dummy.py").write_text("def test_ok():\n    pass\n", encoding="utf-8")
    fixture_dir = tmp_path / "tests" / "fixtures" / "semantic_code" / "python_project"
    fixture_dir.mkdir(parents=True)
    broken_file = fixture_dir / "broken.py"
    broken_file.write_text("def broken(\n    return 1\n", encoding="utf-8")

    result = certify_python_surfaces(
        tmp_path,
        {"results": [], "wrapper_results": []},
        require_map_current=False,
    )

    records = {record["path"]: record for record in result["records"]}
    broken_record = records.get("tests/fixtures/semantic_code/python_project/broken.py")
    assert broken_record is not None
    assert broken_record["syntax_valid"] is False
    assert broken_record["role"] == "release-test"
    assert not any("broken.py" in error for error in result["errors"])

