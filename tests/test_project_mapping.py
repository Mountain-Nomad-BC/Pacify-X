from pathlib import Path
import json
import subprocess
import sys
from runtime.contracts import validate_instance
from runtime.project_intelligence import (
    build_project_map,
    validate_project_map,
    diff_project_maps,
    project_map_status,
)
from runtime.project_impact import (
    analyze_project_impact,
    validate_project_change_intelligence_orchestration,
)
from runtime.project_map_retrieval import query_project_map
from runtime import project_map_retrieval


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


def test_project_map_status_supports_honest_fast_projection_check(tmp_path: Path):
    project = tmp_path / "projection-status"
    project.mkdir()
    (project / "service.py").write_text("def ready(): return True\n", encoding="utf-8")
    build_project_map(project)

    quick = project_map_status(project, verify_integrity=False)
    assert quick["valid"]
    assert quick["validation_scope"] == "sealed-projection-metadata"
    assert quick["content_hashes_verified"] is False

    receipt_path = project / ".engineering-bootstrap/project-map/map-receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["map_revision"] = "forged"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    rejected = project_map_status(project, verify_integrity=False)
    assert not rejected["valid"]
    assert "map receipt hash mismatch" in rejected["errors"]


def test_project_map_query_reuses_stat_bound_json_cache(tmp_path: Path):
    project = tmp_path / "cached-query"
    project.mkdir()
    (project / "service.py").write_text(
        "def health_check(): return True\n", encoding="utf-8"
    )
    build_project_map(project)
    project_map_retrieval._load_json_cached.cache_clear()

    query_project_map(project, "health check")
    before = project_map_retrieval._load_json_cached.cache_info()
    query_project_map(project, "health check")
    after = project_map_retrieval._load_json_cached.cache_info()

    assert after.hits >= before.hits + 2


def test_sensitive_sources_are_excluded_before_inventory_and_retrieval(tmp_path: Path):
    p = tmp_path / "sample"
    p.mkdir()
    (p / ".env").write_text(
        "API_TOKEN=canary-secret-do-not-store\nPUBLIC_MODE=dev\n", encoding="utf-8"
    )
    (p / ".env.production").write_text(
        "DATABASE_URL=postgresql://canary-secret-do-not-store\n", encoding="utf-8"
    )
    (p / "service-account.json").write_text(
        '{"private_key":"canary-secret-do-not-store"}\n', encoding="utf-8"
    )
    (p / "tls.pem").write_text("canary-secret-do-not-store\n", encoding="utf-8")
    (p / "dev_platform.py").write_text(
        "def development_mode(): return 'dev'\n", encoding="utf-8"
    )
    result = build_project_map(p)
    map_dir = p / ".engineering-bootstrap/project-map"
    combined = b"\n".join(path.read_bytes() for path in map_dir.iterdir() if path.is_file())
    assert b"canary-secret-do-not-store" not in combined
    inventory = [
        json.loads(line)
        for line in (map_dir / "file-inventory.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    retrieval = json.loads((map_dir / "retrieval-index.json").read_text(encoding="utf-8"))
    admitted_paths = {record["path"] for record in inventory}
    admitted_paths.update(
        str(record.get("path"))
        for record in retrieval.get("documents", [])
        if record.get("path")
    )
    assert not {".env", ".env.production", "service-account.json", "tls.pem"} & admitted_paths
    assert b"dev_platform.py" in combined
    assert b"development_mode" in combined
    assert result["valid"]
    manifest = json.loads((map_dir / "project-manifest.json").read_text(encoding="utf-8"))
    assert manifest["exclusion_counts"]["sensitive_file"] == 3
    assert manifest["exclusion_counts"]["sensitive_key_material"] == 1


def test_caller_declared_prefixes_are_excluded_and_freshness_is_reproducible(
    tmp_path: Path,
):
    project = tmp_path / "sample"
    project.mkdir()
    (project / "app.py").write_text("def run(): return True\n", encoding="utf-8")
    skipped = project / "external-references"
    skipped.mkdir()
    (skipped / "dead-link-placeholder.txt").write_text(
        "unavailable external reference\n", encoding="utf-8"
    )

    result = build_project_map(project, exclude_prefixes=["external-references"])

    assert result["valid"]
    assert validate_project_map(project, check_freshness=True)["valid"]
    manifest = json.loads(
        (project / ".engineering-bootstrap/project-map/project-manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["caller_exclude_prefixes"] == ["external-references"]
    assert manifest["exclusion_counts"]["caller_declared"] == 1
    inventory = (
        project / ".engineering-bootstrap/project-map/file-inventory.jsonl"
    ).read_text(encoding="utf-8")
    assert "dead-link-placeholder" not in inventory


def test_malformed_url_port_does_not_abort_project_mapping(tmp_path: Path):
    project = tmp_path / "sample"
    project.mkdir()
    (project / "config.py").write_text(
        'BROKEN_EXAMPLE = "http://localhost:8080;\\\\n"\n', encoding="utf-8"
    )

    result = build_project_map(project)

    assert result["valid"]
    assert validate_project_map(project, check_freshness=True)["valid"]


def test_list_valued_openapi_named_json_does_not_abort_mapping(tmp_path: Path):
    project = tmp_path / "sample"
    project.mkdir()
    (project / "archived_openapi_examples.json").write_text(
        '[{"path":"/health"}]\n', encoding="utf-8"
    )

    result = build_project_map(project)

    assert result["valid"]
    assert validate_project_map(project, check_freshness=True)["valid"]


def test_packaged_skill_tools_execute_against_a_real_map(tmp_path: Path):
    project = tmp_path / "cli-project"
    project.mkdir()
    (project / "service.py").write_text("def health(): return True\n", encoding="utf-8")
    tools = Path(__file__).parents[1] / ".px" / "skills"
    build_tool = tools / "map-project-intelligence" / "scripts" / "build_project_map.py"
    validate_tool = (
        tools / "map-project-intelligence" / "scripts" / "validate_project_map.py"
    )
    query_tool = tools / "query-project-map" / "scripts" / "query_project_map.py"
    map_output = tmp_path / "audit-custody" / "project-map"
    built = subprocess.run(
        [
            sys.executable,
            "-B",
            str(build_tool),
            str(project),
            "--output-dir",
            str(map_output),
            "--max-bytes",
            str(16 * 1024 * 1024),
            "--max-files",
            "100",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(built.stdout)["valid"]
    checked = subprocess.run(
        [sys.executable, "-B", str(validate_tool), str(map_output), "--fresh"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(checked.stdout)["valid"]
    queried = subprocess.run(
        [sys.executable, "-B", str(query_tool), str(map_output), "health service"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(queried.stdout)["hits"]


def test_native_impact_traces_callers_routes_tests_and_freshness(tmp_path: Path):
    project = tmp_path / "impact-project"
    project.mkdir()
    (project / "core.py").write_text(
        "def calculate():\n    return 1\n", encoding="utf-8"
    )
    (project / "api.py").write_text(
        "from fastapi import FastAPI\n"
        "from core import calculate\n"
        "app = FastAPI()\n"
        "@app.get('/value')\n"
        "def value():\n"
        "    return {'value': calculate()}\n",
        encoding="utf-8",
    )
    (project / "test_api.py").write_text(
        "from api import value\n\n"
        "def test_value():\n"
        "    assert value()['value'] == 1\n",
        encoding="utf-8",
    )
    build_project_map(project)

    result = analyze_project_impact(project, "core.py::calculate")

    assert result["valid"]
    assert result["freshness_checked"] is True
    assert any(item["path"] == "api.py" for item in result["affected_files"])
    assert any(item["qualname"] == "value" for item in result["affected_symbols"])
    assert result["affected_routes"]
    assert "test_api.py" in result["affected_tests"]
    validate_instance(
        result, Path(__file__).parents[1] / "contracts/project-impact.schema.json"
    )

    (project / "core.py").write_text(
        "def calculate():\n    return 2\n", encoding="utf-8"
    )
    stale = analyze_project_impact(project, "core.py::calculate")
    assert not stale["valid"]
    assert any("stale" in error for error in stale["errors"])


def test_native_impact_requires_disambiguation(tmp_path: Path):
    project = tmp_path / "ambiguous-project"
    project.mkdir()
    (project / "one.py").write_text("def run(): return 1\n", encoding="utf-8")
    (project / "two.py").write_text("def run(): return 2\n", encoding="utf-8")
    build_project_map(project)

    result = analyze_project_impact(project, "run")

    assert not result["valid"]
    assert len(result["candidates"]) == 2
    assert "ambiguous" in result["error"]


def test_native_project_change_intelligence_workflow_is_wired():
    root = Path(__file__).parents[1]
    result = validate_project_change_intelligence_orchestration(root)
    assert result["valid"], result["errors"]
    bindings = json.loads(
        (root / "registry/workflow_execution_bindings.json").read_text(encoding="utf-8")
    )
    assert any(
        item["path"] == "orchestration/workflows/project-change-intelligence.yaml"
        and item["entrypoint"]
        == "runtime.project_impact:validate_project_change_intelligence_orchestration"
        for item in bindings["bindings"]
    )
    orchestrations = json.loads(
        (root / "registry/skill_orchestrations.json").read_text(encoding="utf-8")
    )
    assert any(
        item["id"] == "project-change-intelligence"
        for item in orchestrations["workflows"]
    )
