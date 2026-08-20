from pathlib import Path

from runtime.python_surface_certification import certify_python_surfaces


def test_repository_local_interpreters_are_dependencies_not_owned_source(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='fixture'\nversion='1.0'\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_owned.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    (tmp_path / "runtime").mkdir()
    (tmp_path / "runtime" / "owned.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / ".venv-certify" / "Lib" / "site-packages").mkdir(parents=True)
    (tmp_path / ".venv-certify" / "Lib" / "site-packages" / "foreign.py").write_text("VALUE = 2\n", encoding="utf-8")
    (tmp_path / "Python" / "Lib").mkdir(parents=True)
    (tmp_path / "Python" / "Lib" / "foreign.py").write_text("VALUE = 3\n", encoding="utf-8")

    result = certify_python_surfaces(
        tmp_path,
        {"results": [], "wrapper_results": []},
        require_map_current=False,
    )

    paths = {record["path"] for record in result["records"]}
    assert paths == {"runtime/owned.py", "tests/test_owned.py"}
    assert result["role_counts"].get("unknown", 0) == 0
