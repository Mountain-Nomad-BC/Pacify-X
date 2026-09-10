from pathlib import Path
import json
import math
import subprocess
import sys
import pytest
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


def _retrieval_fixture(tmp_path, mutate=None):
    docs = [{"id": f"d{i}", "kind": "file", "title": "needle" if i == 0 else f"neighbor{i}",
             "path": f"file{i}.py", "language": "python", "role": "source",
             "line_start": 1, "line_end": 1, "summary": "metadata", "relations": []}
            for i in range(4)]
    docs[0]["relations"] = ["d1", "d2", "d3"]
    index = {"schema_version": "1.1", "algorithm": "bm25_metadata_plus_relation_expansion",
             "document_count": 4, "documents": docs, "document_lengths": [1, 0, 0, 0],
             "average_document_length": 0.25, "postings": {"needle": [[0, 1]]},
             "idf": {"needle": math.log(1 + 3.5 / 1.5)}}
    if mutate:
        mutate(index)
    (tmp_path / "retrieval-index.json").write_text(json.dumps(index), encoding="utf-8")
    (tmp_path / "project-manifest.json").write_text('{"map_revision":"fixture"}', encoding="utf-8")
    return index


@pytest.mark.parametrize("mutation", ["negative-index", "bool-index", "large-index", "duplicate-id",
    "missing-length", "nonfinite-idf", "unknown-relation", "negative-frequency", "bool-count", "wrong-idf"])
def test_retrieval_rejects_corrupt_index_denominators(tmp_path, mutation):
    def corrupt(index):
        if mutation == "negative-index": index["postings"]["needle"][0][0] = -1
        elif mutation == "bool-index": index["postings"]["needle"][0][0] = True
        elif mutation == "large-index": index["postings"]["needle"][0][0] = 4
        elif mutation == "duplicate-id": index["documents"][1]["id"] = "d0"
        elif mutation == "missing-length": index["document_lengths"].pop()
        elif mutation == "nonfinite-idf": index["idf"]["needle"] = float("nan")
        elif mutation == "unknown-relation": index["documents"][0]["relations"] = ["absent"]
        elif mutation == "negative-frequency": index["postings"]["needle"][0][1] = -1
        elif mutation == "bool-count": index["document_count"] = True
        else: index["idf"]["needle"] = 5.0
    _retrieval_fixture(tmp_path, corrupt)
    with pytest.raises(ValueError):
        query_project_map(tmp_path, "needle")


@pytest.mark.parametrize("arguments", [{"top_k": True}, {"relation_depth": 1.5},
    {"context_lines": -1}, {"context_lines": True}, {"max_hydration_files": -1},
    {"max_hydration_files": 1.5}, {"kinds": "file"}, {"query": 42}])
def test_retrieval_validates_request_before_loading_map(tmp_path, monkeypatch, arguments):
    def forbidden(*args):
        raise AssertionError("invalid requests must not acquire map files")
    monkeypatch.setattr(project_map_retrieval, "_map_dir", forbidden)
    with pytest.raises(ValueError):
        query_project_map(tmp_path, **{"query": "needle", **arguments})


def test_retrieval_frontier_reports_partial_expansion(tmp_path):
    _retrieval_fixture(tmp_path)
    result = query_project_map(tmp_path, "needle", top_k=1, relation_depth=3,
                               max_relation_nodes=2, max_relation_edges=2)
    assert result["hits"][0]["id"] == "d0"
    assert result["relation_expansion"]["visited_nodes"] == 2
    assert result["relation_expansion"]["examined_edges"] <= 2
    assert result["relation_expansion"]["truncated"] is True


def test_retrieval_hydration_limits_total_lines_including_whole_file_hits(tmp_path):
    _retrieval_fixture(tmp_path, lambda index: index["documents"][0].update(line_end=10_000_000))
    result = query_project_map(tmp_path, "needle", top_k=1, max_hydration_lines=25)
    ranges = [r for item in result["hydration_plan"] for r in item["ranges"]]
    assert sum(r["end_line"] - r["start_line"] + 1 for r in ranges) == 25
    assert result["hydration_truncated"]


def test_retrieval_result_budget_counts_complete_utf8_envelope(tmp_path):
    _retrieval_fixture(tmp_path, lambda index: index["documents"][0].update(summary="🌍" * 1000))
    with pytest.raises(ValueError):
        query_project_map(tmp_path, "needle", max_result_bytes=1024)


def test_retrieval_exact_result_budget_preserves_all_utf8_fields(tmp_path):
    _retrieval_fixture(tmp_path, lambda index: index["documents"][0].update(summary="🌍" * 20))
    expected = query_project_map(tmp_path, "needle", top_k=1)
    size = len(json.dumps(expected, ensure_ascii=False, indent=2).encode("utf-8"))
    assert query_project_map(tmp_path, "needle", top_k=1, max_result_bytes=size) == expected
    with pytest.raises(ValueError):
        query_project_map(tmp_path, "needle", top_k=1, max_result_bytes=size - 1)


def test_retrieval_scoring_has_a_complete_posting_budget(tmp_path):
    def two_postings(index):
        index["postings"]["other"] = [[1, 1]]
        index["idf"]["other"] = math.log(1 + 3.5 / 1.5)
        index["document_lengths"][1] = 1
        index["average_document_length"] = 0.5
    _retrieval_fixture(tmp_path, two_postings)
    with pytest.raises(ValueError, match="computation budget"):
        query_project_map(tmp_path, "needle other", max_query_postings=1)
    result = query_project_map(tmp_path, "needle other", max_query_postings=2)
    assert result["valid"] and result["scored_postings"] == 2


def test_retrieval_response_does_not_mutate_cached_relations(tmp_path):
    _retrieval_fixture(tmp_path)
    result = query_project_map(tmp_path, "needle", top_k=1)
    result["hits"][0]["relations"].clear()
    again = query_project_map(tmp_path, "needle", top_k=1)
    assert again["hits"][0]["relations"] == ["d1", "d2", "d3"]


def test_retrieval_rejects_oversized_map_before_decoding(tmp_path, monkeypatch):
    _retrieval_fixture(tmp_path)
    monkeypatch.setattr(project_map_retrieval, "MAX_INDEX_BYTES", 256, raising=False)
    with pytest.raises(ValueError):
        query_project_map(tmp_path, "needle")


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
