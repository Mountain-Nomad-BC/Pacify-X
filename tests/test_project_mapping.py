from pathlib import Path
import json
import subprocess
import sys
from runtime.project_intelligence import (
    build_project_map,
    validate_project_map,
    diff_project_maps,
)
from runtime.project_map_retrieval import query_project_map


def test_build_validate_query_and_incremental(tmp_path: Path):
    p = tmp_path / "sample"
    p.mkdir()
    (p / "app.py").write_text(
        'from fastapi import FastAPI\napp=FastAPI()\n@app.get("/health")\ndef health(): return {"ok": True}\n',
        encoding="utf-8",
    )
    (p / "test_app.py").write_text(
        'from app import health\ndef test_health(): assert health()["ok"]\n',
        encoding="utf-8",
    )
    first = build_project_map(p)
    assert first["valid"]
    assert validate_project_map(p, check_freshness=True)["valid"]
    q = query_project_map(p, "health api endpoint")
    assert q["valid"] and q["hits"] and q["hydration_plan"]
    second = build_project_map(p)
    assert second["incremental_reuse"]["reused"] >= 2
    assert diff_project_maps(Path(first["map_dir"]), Path(second["map_dir"]))["valid"]


def test_configuration_values_not_persisted(tmp_path: Path):
    p = tmp_path / "sample"
    p.mkdir()
    (p / ".env").write_text(
        "API_TOKEN=do-not-store\nPUBLIC_MODE=true\n", encoding="utf-8"
    )
    build_project_map(p)
    text = (p / ".engineering-bootstrap/project-map/configuration-map.json").read_text(
        encoding="utf-8"
    )
    assert "do-not-store" not in text


def test_packaged_skill_tools_execute_against_a_real_map(tmp_path: Path):
    project = tmp_path / "cli-project"
    project.mkdir()
    (project / "service.py").write_text("def health(): return True\n", encoding="utf-8")
    tools = Path(__file__).parents[1] / ".agents" / "skills"
    build_tool = tools / "map-project-intelligence" / "scripts" / "build_project_map.py"
    validate_tool = (
        tools / "map-project-intelligence" / "scripts" / "validate_project_map.py"
    )
    query_tool = tools / "query-project-map" / "scripts" / "query_project_map.py"
    built = subprocess.run(
        [sys.executable, "-B", str(build_tool), str(project)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(built.stdout)["valid"]
    checked = subprocess.run(
        [sys.executable, "-B", str(validate_tool), str(project), "--fresh"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(checked.stdout)["valid"]
    queried = subprocess.run(
        [sys.executable, "-B", str(query_tool), str(project), "health service"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(queried.stdout)["hits"]
