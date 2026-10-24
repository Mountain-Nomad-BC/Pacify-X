from pathlib import Path

import pytest

from runtime import semantic_surfaces as surfaces


@pytest.fixture
def native_powershell_parser():
    from runtime.semantic_powershell_source import discover_parser
    if discover_parser() is None:
        pytest.skip("Native PowerShell unavailable; native source parsing unverified")


def test_powershell_census_uses_native_syntax_without_executing_source(tmp_path, native_powershell_parser):
    canary = tmp_path / "must-not-exist.txt"
    literal = str(canary).replace("'", "''")
    put(tmp_path, "scripts/observe.ps1", (
        "# function FromComment {}\n"
        "$text = @'\nfunction FromString {}\n'@\n"
        "function global:Observe-Only { param([string]$Name) }\n"
        "class CensusRecord { [string]$Name }\n"
        f"Set-Content -LiteralPath '{literal}' -Value 'executed'\n"
        "throw 'source must never execute'\n"
    ))
    result = surfaces.collect_corpus_snapshot(tmp_path)
    row = next(r for r in result.report()["files"] if r["path"] == "scripts/observe.ps1")
    assert row["disposition"] == "observed"
    assert {e.name for e in result.entities} == {"observe", "global:Observe-Only", "CensusRecord"}
    assert not canary.exists()
    assert result.report()["source_revision_complete"]
    assert not result.report()["execution_authority"]


def test_powershell_syntax_error_cannot_publish_partial_metadata(tmp_path, native_powershell_parser):
    put(tmp_path, "scripts/broken.ps1", "function Good {}\nfunction Broken {")
    result = surfaces.collect_corpus_snapshot(tmp_path)
    row = next(r for r in result.report()["files"] if r["path"] == "scripts/broken.ps1")
    assert row["disposition"] == "parse_error"
    assert result.entities == ()
    assert not result.report()["extraction_complete"]


def test_missing_powershell_parser_remains_in_census_denominator(tmp_path, monkeypatch):
    from runtime import semantic_powershell_source as parser
    monkeypatch.setattr(parser, "discover_parser", lambda: None)
    put(tmp_path, "scripts/unavailable.ps1", "function Actual {}")
    result = surfaces.collect_corpus_snapshot(tmp_path)
    row = next(r for r in result.report()["files"] if r["path"] == "scripts/unavailable.ps1")
    assert row["disposition"] == "extractor_unavailable" and row["sha256"]
    assert result.report()["accounting_complete"] and result.report()["source_revision_complete"]
    assert not result.report()["extraction_complete"] and result.entities == ()


def test_same_line_powershell_declarations_remain_distinct_observations(tmp_path, native_powershell_parser):
    put(tmp_path, "scripts/repeated.ps1", "function Same {} function Same {}")
    result = surfaces.collect_corpus_snapshot(tmp_path)
    rows = [e for e in result.entities if e.kind == "function"]
    assert len(rows) == 2 and rows[0].key != rows[1].key
    assert rows[0].line == rows[1].line == 1
    assert result.report()["generator_dependencies"]["runtime/semantic_powershell_source.py"]


def put(root, relative, text):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_source_binding_stays_stable_while_complete_audit_changes(tmp_path):
    put(tmp_path, "runtime/a.py", "def run(): pass")
    before = surfaces.collect_corpus_snapshot(tmp_path).report()
    put(tmp_path, ".agentic_engineering_os_px/test-evidence/current-audit.json", "{}")
    after = surfaces.collect_corpus_snapshot(tmp_path).report()
    assert before["source_binding_sha256"] == after["source_binding_sha256"]
    assert before["source_binding"] == after["source_binding"]
    assert before["result_sha256"] != after["result_sha256"]
    assert len(after["files"]) == len(before["files"]) + 1


def test_native_observation_custody_does_not_change_source_binding(tmp_path, native_powershell_parser):
    put(tmp_path, "scripts/a.ps1", "function Actual {}")
    before = surfaces.collect_corpus_snapshot(tmp_path).report()
    after = surfaces.collect_corpus_snapshot(tmp_path).report()
    assert before["source_binding_sha256"] == after["source_binding_sha256"]
    assert before["source_binding"] == after["source_binding"]
    assert before["result_sha256"] != after["result_sha256"]
    assert before["entities_sha256"] == after["entities_sha256"]


def test_source_binding_invalidates_source_generator_scope_and_budget_changes(tmp_path, monkeypatch):
    path = put(tmp_path, "runtime/a.py", "def run(): pass")
    baseline = surfaces.collect_corpus_snapshot(tmp_path).report()
    path.write_text("def changed(): pass", encoding="utf-8")
    assert surfaces.collect_corpus_snapshot(tmp_path).report()["source_binding_sha256"] != baseline["source_binding_sha256"]
    path.write_text("def run(): pass", encoding="utf-8")
    assert surfaces.collect_corpus_snapshot(tmp_path, surfaces=["runtime"]).report()["source_binding_sha256"] != baseline["source_binding_sha256"]
    sampled = surfaces.collect_corpus_snapshot(tmp_path, per_surface_limit=1).report()
    assert sampled["source_binding_sha256"] != baseline["source_binding_sha256"]
    assert not sampled["source_binding"]["extraction_complete"]
    monkeypatch.setattr(surfaces, "CENSUS_GENERATOR", "px.semantic-surfaces/test-new-generator")
    assert surfaces.collect_corpus_snapshot(tmp_path).report()["source_binding_sha256"] != baseline["source_binding_sha256"]


def test_source_binding_preserves_unclassified_and_incomplete_source(tmp_path):
    put(tmp_path, "knowledge/opaque.unknown", "authored unclassified material")
    report = surfaces.collect_corpus_snapshot(tmp_path).report()
    binding = report["source_binding"]
    assert binding["authored_files"][0]["path"] == "knowledge/opaque.unknown"
    assert binding["authored_files"][0]["disposition"] == "unsupported_surface"
    assert not binding["extraction_complete"] and not binding["canonical_identity_authority"]
    assert not binding["execution_authority"]


def test_source_binding_records_parser_unavailability(tmp_path, native_powershell_parser, monkeypatch):
    from runtime import semantic_powershell_source as parser
    put(tmp_path, "scripts/a.ps1", "function Actual {}")
    before = surfaces.collect_corpus_snapshot(tmp_path).report()
    monkeypatch.setattr(parser, "discover_parser", lambda: None)
    after = surfaces.collect_corpus_snapshot(tmp_path).report()
    assert before["source_revision"] == after["source_revision"]
    assert before["source_binding_sha256"] != after["source_binding_sha256"]
    assert after["source_binding"]["authored_files"][0]["disposition"] == "extractor_unavailable"
    assert not after["source_binding"]["extraction_complete"]


def test_complete_audit_and_source_binding_checksums_are_independent(tmp_path):
    import hashlib
    import json
    put(tmp_path, "runtime/a.py", "def run(): pass")
    report = surfaces.collect_corpus_snapshot(tmp_path).report()
    def digest(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()
    assert report["source_binding_sha256"] == digest(report["source_binding"])
    claimed = report.pop("result_sha256")
    assert claimed == digest(report)


def test_source_binding_contract_cannot_grant_authority(tmp_path):
    from copy import deepcopy
    from runtime.contracts import validate_instance, ContractValidationError
    put(tmp_path, "runtime/a.py", "def run(): pass")
    binding = surfaces.collect_corpus_snapshot(tmp_path).report()["source_binding"]
    validate_instance(binding, surfaces.SOURCE_BINDING_SCHEMA)
    for field in ["canonical_identity_authority", "execution_authority"]:
        changed = deepcopy(binding)
        changed[field] = True
        with pytest.raises(ContractValidationError):
            validate_instance(changed, surfaces.SOURCE_BINDING_SCHEMA)


def test_source_binding_contract_is_owned_by_actual_producer_and_consumers():
    from scripts.build_contract_ownership_registry import build
    root = Path(__file__).resolve().parents[1]
    record = next(r for r in build(root)["records"]
                  if r["path"] == "contracts/semantic/source-census-binding.schema.json")
    assert record["owner"] == "runtime/semantic_surfaces.py"
    for consumer in ["runtime/semantic_taxonomy_census.py", "runtime/semantic_prefreeze_census.py"]:
        assert consumer in record["producers"] and consumer in record["consumers"]


def test_changed_proposals_invalidate_binding_without_rewriting_source(tmp_path, monkeypatch):
    put(tmp_path, "runtime/a.py", "def run(): pass")
    before = surfaces.collect_corpus_snapshot(tmp_path).report()
    original = surfaces.observe_python
    def changed_observer(*args, **kwargs):
        rows = original(*args, **kwargs)
        rows[0].doc = "different observed metadata"
        return rows
    monkeypatch.setattr(surfaces, "observe_python", changed_observer)
    after = surfaces.collect_corpus_snapshot(tmp_path).report()
    assert before["source_revision"] == after["source_revision"]
    assert before["entities_sha256"] != after["entities_sha256"]
    assert before["source_binding_sha256"] != after["source_binding_sha256"]


def test_unreadable_source_cannot_publish_current_binding(tmp_path, monkeypatch):
    target = put(tmp_path, "runtime/a.py", "def run(): pass")
    original = Path.open
    def denied(path, *args, **kwargs):
        if path == target:
            raise PermissionError("injected source acquisition denial")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", denied)
    report = surfaces.collect_corpus_snapshot(tmp_path).report()
    assert report["source_binding"] is None and report["source_binding_sha256"] is None
    assert report["files"][0]["disposition"] == "read_error"


def test_python_definitions_are_not_silently_sampled(tmp_path):
    put(tmp_path, "runtime/many.py", "\n".join(f"def f{i}(): pass" for i in range(75)))
    rows = surfaces.collect_corpus(tmp_path, surfaces=["runtime"])
    assert len(rows) == 76


def test_javascript_definitions_are_not_silently_sampled(tmp_path):
    put(tmp_path, "extension/src/many.js", "\n".join(f"function f{i}() {{}}" for i in range(55)))
    assert len(surfaces.collect_corpus(tmp_path, surfaces=["extension"])) == 56


def test_budget_accounts_for_every_file(tmp_path):
    for name in ["a", "b", "c"]:
        put(tmp_path, f"runtime/{name}.py", "def run(): pass")
    result = surfaces.collect_corpus_snapshot(tmp_path, surfaces=["runtime"], per_surface_limit=1)
    assert {row["path"] for row in result.report()["files"]} == {f"runtime/{n}.py" for n in ["a", "b", "c"]}
    assert not result.report()["extraction_complete"]
    assert any(row["disposition"] == "budget_exhausted" for row in result.report()["files"])


def test_parse_failures_and_non_object_json_remain_visible(tmp_path):
    put(tmp_path, "contracts/broken.json", "{")
    put(tmp_path, "contracts/array.json", "[]")
    put(tmp_path, "runtime/broken.py", "def :")
    result = surfaces.collect_corpus_snapshot(tmp_path)
    rows = {r["path"]: r for r in result.report()["files"]}
    assert rows["contracts/broken.json"]["disposition"] == "parse_error"
    assert rows["contracts/array.json"]["disposition"] == "unsupported_structure"
    assert rows["runtime/broken.py"]["disposition"] == "parse_error"
    assert not result.report()["extraction_complete"]
    assert all(r["sha256"] for r in rows.values())


def test_skills_are_observed_without_execution_claim(tmp_path):
    put(tmp_path, ".px/skills/example/SKILL.md", "# Example\nInstructions")
    snapshot = surfaces.collect_corpus_snapshot(tmp_path)
    assert len(snapshot.entities) == 1
    assert snapshot.report()["execution_authority"] is False


def test_unconfigured_authored_files_are_accounted_not_invented(tmp_path):
    put(tmp_path, "scripts/tool.opaque", "Unconfigured authored material")
    snapshot = surfaces.collect_corpus_snapshot(tmp_path)
    assert not snapshot.entities
    row = snapshot.report()["files"][0]
    assert row["path"] == "scripts/tool.opaque"
    assert row["disposition"] == "unsupported_surface"
    assert not snapshot.report()["extraction_complete"]


def test_jsonl_records_are_all_proposed_without_sampling_or_execution(tmp_path):
    import json
    put(tmp_path, "knowledge/records.jsonl", "\n".join(json.dumps({"id": f"record-{index}", "description": "Observed metadata"}) for index in range(75)))
    snapshot = surfaces.collect_corpus_snapshot(tmp_path)
    row = snapshot.report()["files"][0]
    assert row["disposition"] == "observed" and row["record_count"] == 75
    assert row["entity_count"] == 76 and len(snapshot.entities) == 76
    assert len({entity.key for entity in snapshot.entities}) == 76
    assert snapshot.report()["extraction_complete"] and snapshot.report()["execution_authority"] is False


def test_jsonl_malformed_tail_cannot_publish_a_successful_prefix(tmp_path):
    put(tmp_path, "knowledge/records.jsonl", '{"id":"one"}\n{"id":')
    snapshot = surfaces.collect_corpus_snapshot(tmp_path)
    assert not snapshot.entities
    assert snapshot.report()["files"][0]["disposition"] == "parse_error"
    assert not snapshot.report()["extraction_complete"]


@pytest.mark.parametrize("tail", ['{"id":"one","id":"two"}', '{"number":NaN}', '{"number":Infinity}', '', '\ufeff{"id":"two"}'])
def test_jsonl_strict_failures_remain_hashed_and_unobserved(tmp_path, tail):
    put(tmp_path, "knowledge/records.jsonl", '{"id":"one"}\n' + tail + '\n')
    snapshot = surfaces.collect_corpus_snapshot(tmp_path)
    row = snapshot.report()["files"][0]
    assert row["disposition"] == "parse_error" and row["sha256"]
    assert not snapshot.entities and not snapshot.report()["extraction_complete"]


def test_jsonl_primitive_tail_is_unsupported_structure_not_partial_success(tmp_path):
    put(tmp_path, "knowledge/records.jsonl", '{"id":"one"}\n["two"]\n')
    snapshot = surfaces.collect_corpus_snapshot(tmp_path)
    assert snapshot.report()["files"][0]["disposition"] == "unsupported_structure"
    assert not snapshot.entities


def test_jsonl_budget_is_whole_file_and_never_a_sample(tmp_path, monkeypatch):
    put(tmp_path, "knowledge/records.jsonl", '{"id":"one"}\n{"id":"two"}\n')
    monkeypatch.setattr(surfaces, "MAX_JSONL_RECORDS", 1)
    snapshot = surfaces.collect_corpus_snapshot(tmp_path)
    assert snapshot.report()["files"][0]["disposition"] == "budget_exhausted"
    assert not snapshot.entities and not snapshot.report()["extraction_complete"]


def test_jsonl_unicode_separators_and_crlf_preserve_actual_record_lines(tmp_path):
    put(tmp_path, "knowledge/records.jsonl", '{"id":"one\u2028inside"}\r\n{"id":"two"}\r\n')
    snapshot = surfaces.collect_corpus_snapshot(tmp_path)
    assert [entity.line for entity in snapshot.entities] == [0, 1, 2]
    assert snapshot.report()["files"][0]["record_count"] == 2
    assert snapshot.report()["extraction_complete"]


def test_empty_jsonl_container_does_not_invent_experience_records(tmp_path):
    put(tmp_path, "knowledge/usage.jsonl", "")
    snapshot = surfaces.collect_corpus_snapshot(tmp_path)
    row = snapshot.report()["files"][0]
    assert row["disposition"] == "observed" and row["record_count"] == 0
    assert len(snapshot.entities) == 1 and snapshot.entities[0].kind == "document"
    assert snapshot.entities[0].line == 0
    assert snapshot.report()["execution_authority"] is False


def test_both_census_consumers_share_jsonl_accounting(tmp_path):
    put(tmp_path, "knowledge/records.jsonl", '{"id":"one"}\n{"id":"two"}\n')
    from runtime.semantic_taxonomy_census import run_full_census
    from runtime.semantic_prefreeze_census import run_prefreeze_census
    for run in [run_full_census, run_prefreeze_census]:
        report = run(tmp_path)
        row = report["source_census"]["files"][0]
        assert row["record_count"] == 2 and row["entity_count"] == 3
        assert report["source_census"]["execution_authority"] is False


def test_exact_security_graph_owner_uses_native_budget_without_widening_generic(tmp_path):
    import json
    text = '\n'.join(json.dumps({"id": f"node-{index}"}) for index in range(10_001))
    put(tmp_path, "registry/security_capabilities/graph.jsonl", text)
    put(tmp_path, "knowledge/other.jsonl", text)
    report = surfaces.collect_corpus_snapshot(tmp_path).report()
    rows = {row["path"]: row for row in report["files"]}
    graph = rows["registry/security_capabilities/graph.jsonl"]
    assert graph["disposition"] == "observed" and graph["record_count"] == 10_001
    assert graph["surfaces"] == ["security_graph"]
    assert rows["knowledge/other.jsonl"]["disposition"] == "budget_exhausted"
    assert not report["extraction_complete"] and not report["execution_authority"]
    assert "runtime/cybersecurity_provider.py" in report["generator_dependencies"]


def test_security_graph_native_record_limit_rejects_whole_file(tmp_path):
    from runtime.cybersecurity_provider import MAX_SECURITY_JSONL_RECORDS
    put(tmp_path, "registry/security_capabilities/graph.jsonl", '{"id":"node"}\n' * (MAX_SECURITY_JSONL_RECORDS + 1))
    snapshot = surfaces.collect_corpus_snapshot(tmp_path)
    assert snapshot.report()["files"][0]["disposition"] == "budget_exhausted"
    assert not snapshot.entities


def test_security_graph_native_line_limit_rejects_whole_file(tmp_path):
    import json
    from runtime.cybersecurity_provider import MAX_SECURITY_JSONL_LINE_BYTES
    put(tmp_path, "registry/security_capabilities/graph.jsonl", '{"id":"one"}\n' + json.dumps({"id": "x" * MAX_SECURITY_JSONL_LINE_BYTES}))
    snapshot = surfaces.collect_corpus_snapshot(tmp_path)
    assert snapshot.report()["files"][0]["disposition"] == "budget_exhausted"
    assert not snapshot.entities


def test_security_graph_native_decoder_rejects_malformed_tail(tmp_path):
    put(tmp_path, "registry/security_capabilities/graph.jsonl", '{"id":"one"}\n{"id":NaN}')
    snapshot = surfaces.collect_corpus_snapshot(tmp_path)
    assert snapshot.report()["files"][0]["disposition"] == "parse_error"
    assert not snapshot.entities and not snapshot.report()["execution_authority"]


def test_binding_changes_on_source_change_and_is_repeatable(tmp_path):
    path = put(tmp_path, "runtime/a.py", "def run(): pass")
    before = surfaces.collect_corpus_snapshot(tmp_path).report()
    assert before == surfaces.collect_corpus_snapshot(tmp_path).report()
    path.write_text("def changed(): pass", encoding="utf-8")
    after = surfaces.collect_corpus_snapshot(tmp_path).report()
    assert after["source_revision"] != before["source_revision"]
    assert after["result_sha256"] != before["result_sha256"]


def test_both_normal_consumers_expose_accounting(tmp_path):
    put(tmp_path, "runtime/a.py", "def run(): pass")
    from runtime.semantic_taxonomy_census import run_full_census
    from runtime.semantic_prefreeze_census import run_prefreeze_census
    for run in [run_full_census, run_prefreeze_census]:
        report = run(tmp_path, per_surface_limit=1)
        assert report["source_census"]["accounting_complete"]
        assert not report["source_census"]["extraction_complete"]
        assert report["source_census"]["execution_authority"] is False
        assert report["source_binding_sha256"] == report["source_census"]["source_binding_sha256"]
        assert report["source_binding_sha256"]


def test_source_changed_during_observation_is_not_admitted(tmp_path, monkeypatch):
    path = put(tmp_path, "runtime/a.py", "def run(): pass")
    original = surfaces.observe_python
    def change(*args, **kwargs):
        rows = original(*args, **kwargs)
        path.write_text("def new(): pass", encoding="utf-8")
        return rows
    monkeypatch.setattr(surfaces, "observe_python", change)
    snapshot = surfaces.collect_corpus_snapshot(tmp_path)
    assert snapshot.report()["source_binding"] is None
    assert snapshot.report()["source_binding_sha256"] is None
    assert not snapshot.entities
    assert snapshot.report()["files"][0]["disposition"] == "source_drift"
    assert not snapshot.report()["extraction_complete"]


def test_runtime_evidence_is_not_extracted_or_part_of_source_revision(tmp_path):
    put(tmp_path, "runtime/a.py", "def run(): pass")
    state = put(tmp_path, ".agentic_engineering_os_px/test-evidence/report.json", "{}")
    before = surfaces.collect_corpus_snapshot(tmp_path)
    state.write_text('{"run":"changed"}', encoding="utf-8")
    after = surfaces.collect_corpus_snapshot(tmp_path)
    assert before.report()["source_revision"] == after.report()["source_revision"]
    row = next(r for r in after.report()["files"] if r["path"].endswith("report.json"))
    assert row["disposition"] == "excluded" and row["sha256"] is None
    assert len(after.entities) == 2


def test_invalid_budgets_and_unknown_surfaces_fail_closed(tmp_path):
    import pytest
    for limit in [True, 0, -1, 1.5]:
        with pytest.raises(ValueError):
            surfaces.collect_corpus_snapshot(tmp_path, per_surface_limit=limit)
    with pytest.raises(ValueError):
        surfaces.collect_corpus_snapshot(tmp_path, surfaces=["unknown"])


def test_report_copy_cannot_rewrite_proof(tmp_path):
    put(tmp_path, "runtime/a.py", "def run(): pass")
    snapshot = surfaces.collect_corpus_snapshot(tmp_path)
    changed = snapshot.report()
    changed["files"].clear()
    changed["execution_authority"] = True
    assert snapshot.report()["files"]
    assert not snapshot.report()["execution_authority"]


def test_fallback_owner_covers_nested_authored_sources_without_duplicates(tmp_path):
    put(tmp_path, "registry/nested/catalog.json", '{"name":"Declared catalog"}')
    put(tmp_path, "scripts/helper.py", "def run(): pass")
    put(tmp_path, "runtime/a.py", "def run(): pass")
    snapshot = surfaces.collect_corpus_snapshot(tmp_path)
    assert snapshot.report()["extraction_complete"]
    assert len(snapshot.entities) == 5
    row = next(r for r in snapshot.report()["files"] if r["path"] == "runtime/a.py")
    assert row["surfaces"] == ["runtime"]


def test_known_broken_fixture_is_explicitly_excluded_by_existing_policy(tmp_path):
    put(tmp_path, "tests/fixtures/broken.py", "def :")
    snapshot = surfaces.collect_corpus_snapshot(tmp_path)
    row = snapshot.report()["files"][0]
    assert row["disposition"] == "excluded" and row["reason"] == "test-fixture-data"
    assert row["sha256"]
    assert not snapshot.entities


def test_yaml_and_toml_are_metadata_only_and_invalid_syntax_is_visible(tmp_path):
    put(tmp_path, "orchestration/workflows/a.yaml", "name: Declared workflow\n")
    put(tmp_path, "pyproject.toml", 'name = "Declared project"\n')
    put(tmp_path, "policies/broken.yaml", "name: [broken\n")
    snapshot = surfaces.collect_corpus_snapshot(tmp_path)
    assert len(snapshot.entities) == 2
    rows = {r["path"]: r for r in snapshot.report()["files"]}
    assert rows["policies/broken.yaml"]["disposition"] == "parse_error"
    assert not snapshot.report()["extraction_complete"]
    assert not snapshot.report()["execution_authority"]


def test_entity_mutation_cannot_change_snapshot_binding(tmp_path):
    put(tmp_path, "runtime/a.py", "def run(): pass")
    snapshot = surfaces.collect_corpus_snapshot(tmp_path)
    original = snapshot.entities[0].key
    snapshot.entities[0].key = "forged"
    assert snapshot.entities[0].key == original


def test_source_changed_after_extraction_blocks_completeness(tmp_path, monkeypatch):
    path = put(tmp_path, "runtime/a.py", "def old(): pass")
    import runtime.bounded_walk as walk_module
    original = walk_module.bounded_walk
    calls = 0
    def changing_walk(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            path.write_text("def new(): pass", encoding="utf-8")
        return original(*args, **kwargs)
    monkeypatch.setattr(walk_module, "bounded_walk", changing_walk)
    report = surfaces.collect_corpus_snapshot(tmp_path).report()
    assert not report["accounting_complete"]
    assert not report["extraction_complete"]


def test_late_same_size_rewrite_with_preserved_timestamp_cannot_issue_revision(tmp_path, monkeypatch):
    import os
    import runtime.bounded_walk as walk_module
    path = put(tmp_path, "runtime/a.py", "def old(): pass")
    original = walk_module.bounded_walk
    calls = 0
    def changing_walk(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            before = path.stat()
            path.write_text("def new(): pass", encoding="utf-8")
            os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        return original(*args, **kwargs)
    monkeypatch.setattr(walk_module, "bounded_walk", changing_walk)
    report = surfaces.collect_corpus_snapshot(tmp_path).report()
    assert not report["accounting_complete"]
    assert report["source_revision"] is None
    assert not report["extraction_complete"]


def test_unhashed_oversized_source_cannot_issue_a_revision(tmp_path, monkeypatch):
    put(tmp_path, "runtime/a.py", "def run(): pass")
    monkeypatch.setattr(surfaces, "MAX_SOURCE_BYTES", 2)
    report = surfaces.collect_corpus_snapshot(tmp_path).report()
    assert report["files"][0]["disposition"] == "budget_exhausted"
    assert report["source_revision"] is None
    assert not report["source_revision_complete"]
    assert not report["extraction_complete"]


def test_collection_without_newer_pathlib_apis(tmp_path, monkeypatch):
    put(tmp_path, "runtime/a.py", "def run(): pass")
    for name in ["full_match", "is_junction"]:
        owner = next((base for base in Path.__mro__ if name in vars(base)), None)
        if owner is not None:
            monkeypatch.delattr(owner, name)
    snapshot = surfaces.collect_corpus_snapshot(tmp_path)
    assert len(snapshot.entities) == 2
    assert snapshot.report()["extraction_complete"]


def test_portable_globs_preserve_recursive_and_single_level_ownership():
    assert surfaces._source_glob_matches("runtime/a.py", "runtime/**/*.py")
    assert surfaces._source_glob_matches("runtime/nested/a.py", "runtime/**/*.py")
    assert surfaces._source_glob_matches("a.py", "**/*.py")
    assert not surfaces._source_glob_matches("registry/nested/a.json", "registry/*.json")
    assert not surfaces._source_glob_matches("runtime/a.txt", "runtime/**/*.py")
