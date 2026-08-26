import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from runtime.test_profiles import (
    ProcessingOrderBlocked,
    initialize_project_repair_campaign,
    repair_campaign_status,
    require_processing_stage,
)

from runtime.test_profiles import (
    _section_files,
    _structural_scan_files,
    build_test_group_index,
    group_receipt,
    group_status,
    resolve_test_groups,
    resolve_test_profile,
    resolve_test_section,
    read_section_chunk_receipt,
    section_chunk_receipt,
    section_chunk_receipt_path,
    section_receipt,
    section_status,
    write_section_chunk_receipt,
)


ROOT = Path(__file__).resolve().parents[1]


def test_testing_governance_receipt_excludes_mutable_processing_order_state():
    config = json.loads((ROOT / "registry/test_profiles.json").read_text(encoding="utf-8"))
    patterns = config["sections"]["testing-governance"]["source_patterns"]
    assert "registry/repair_campaign.json" not in patterns
    assert not any("processing-order/repair-campaign.json" in pattern for pattern in patterns)


def test_test_group_index_help_is_side_effect_free():
    target = ROOT / "registry/test_group_index.json"
    before = hashlib.sha256(target.read_bytes()).hexdigest()
    result = subprocess.run(
        [sys.executable, "scripts/build_test_group_index.py", "--help"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "usage:" in result.stdout
    assert hashlib.sha256(target.read_bytes()).hexdigest() == before


def test_full_and_release_include_every_discovered_test_file():
    full = resolve_test_profile(ROOT, "full")
    release = resolve_test_profile(ROOT, "release")
    assert full["member_count"] == full["discovered_test_files"]
    assert release["members"] == full["members"]
    assert release["gates"]


def test_fast_keeps_ordinary_contract_checks_and_excludes_expensive_artifact_gates():
    fast = resolve_test_profile(ROOT, "fast")
    assert "tests/test_declared_suite_support.py" in fast["members"]
    assert "tests/test_exact_tool_certification.py" not in fast["members"]
    assert "tests/test_installed_wheel_e2e.py" not in fast["members"]
    assert (
        fast["timeout_seconds"] < resolve_test_profile(ROOT, "full")["timeout_seconds"]
    )
    assert fast["environment"]["PYTHONNOUSERSITE"] == "0"
    assert (
        resolve_test_profile(ROOT, "release")["environment"]["PYTHONNOUSERSITE"] == "1"
    )


def test_sections_are_content_addressed_bounded_and_dependency_governed(tmp_path):
    learning = resolve_test_section(ROOT, "learning-promotion")
    assert learning["inputs"]
    assert len(learning["input_sha256"]) == 64
    assert (
        learning["timeout_seconds"]
        < resolve_test_profile(ROOT, "full")["timeout_seconds"]
    )
    receipt = section_receipt(
        learning, {"exit_code": 0, "timed_out": False, "duration_seconds": 1.2}
    )
    assert receipt["passed"] and len(receipt["receipt_sha256"]) == 64
    assert receipt["cwd"] == "."
    placement = resolve_test_section(ROOT, "execution-placement")
    assert placement["dependencies"] == ["learning-promotion"]


def test_builder_and_trace_control_planes_have_exact_section_owners():
    dashboard = resolve_test_section(ROOT, "dashboard-extension")
    assert "extension/src/studioCatalog.js" in dashboard["inputs"]
    assert "extension/src/workflowTraceProjection.js" in dashboard["inputs"]
    assert "extension/scripts/deduplicate-legacy-css.js" in dashboard["inputs"]
    assert "tests/ui-scaffold.test.js" in dashboard["command"]
    governed_dashboard_owners = [
        "tests/studio-catalog-agent-builder.test.js",
        "tests/workflow-trace-projection.test.js",
        "tests/ui-action-inventory.test.js",
        "tests/operational-walk-status.test.js",
        "tests/operational-fault-recovery-walk.test.js",
        "tests/contained-ui-action-walk.test.js",
    ]
    assert [
        command
        for command in dashboard["command"]
        if command in governed_dashboard_owners
    ] == governed_dashboard_owners

    studios = resolve_test_section(ROOT, "studio-memory-graph")
    assert "runtime/agent_builder.py" in studios["inputs"]
    assert "runtime/studio_terminal_observer.py" in studios["inputs"]
    assert "tests/test_agent_builder.py" in studios["inputs"]
    assert "tests/test_agent_builder.py" in studios["command"]

    governance = resolve_test_section(ROOT, "testing-governance")
    reconciliation_test = "tests/test_reconcile_unverified_operational_controls.py"
    assert reconciliation_test in governance["inputs"]
    assert governance["command"].count(reconciliation_test) == 1
    assert "runtime/repository_scope.py" in governance["inputs"]
    assert "scripts/audit_source_archive.py" in governance["inputs"]
    assert "scripts/clean_source_export.py" in governance["inputs"]
    for boundary_test in (
        "tests/test_repository_scope.py",
        "tests/test_effect_surface.py",
        "tests/test_clean_source_export.py",
    ):
        assert boundary_test in governance["inputs"]
        assert governance["command"].count(boundary_test) == 1
    assert "scripts/cleanup_python_caches.py" in governance["inputs"]
    assert "tests/test_cache_quarantine.py" in governance["inputs"]
    assert governance["command"].count("tests/test_cache_quarantine.py") == 1


def test_repository_scope_change_stales_testing_governance_identity(tmp_path):
    config = {
        "sections": {
            "testing-governance": {
                "source_patterns": [
                    "runtime/repository_scope.py",
                    "scripts/cleanup_python_caches.py",
                    "tests/test_repository_scope.py",
                    "tests/test_effect_surface.py",
                    "tests/test_clean_source_export.py",
                    "tests/test_cache_quarantine.py",
                ],
                "command": ["python", "-m", "pytest", "tests/test_repository_scope.py"],
                "timeout_seconds": 30,
            }
        }
    }
    (tmp_path / "registry").mkdir()
    (tmp_path / "runtime").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "registry/test_profiles.json").write_text(
        json.dumps(config), encoding="utf-8"
    )
    for relative in config["sections"]["testing-governance"]["source_patterns"]:
        (tmp_path / relative).write_text(f"# {relative}\n", encoding="utf-8")

    predecessor = resolve_test_section(tmp_path, "testing-governance")
    (tmp_path / "runtime/repository_scope.py").write_text(
        "# changed boundary\n", encoding="utf-8"
    )
    current = resolve_test_section(tmp_path, "testing-governance")

    assert predecessor["input_sha256"] != current["input_sha256"]
    cleanup = tmp_path / "scripts/cleanup_python_caches.py"
    cleanup.write_text("# changed cleanup boundary\n", encoding="utf-8")
    cleanup_current = resolve_test_section(tmp_path, "testing-governance")
    assert cleanup_current["input_sha256"] not in {
        predecessor["input_sha256"],
        current["input_sha256"],
    }


def test_studio_section_is_bounded_into_independently_addressed_chunks():
    studios = resolve_test_section(ROOT, "studio-memory-graph")
    chunks = studios["chunks"]
    members = [
        value for value in studios["command"] if value.startswith("tests/")
    ]
    # Several Studio members launch supervised child Python processes. Keep the
    # governed section serial so Windows process/resource contention cannot turn
    # a passing member into an output-less worker exit.
    assert studios["max_parallel_chunks"] == 1
    assert len(chunks) == (len(members) + 1) // 2
    assert all(1 <= chunk["member_count"] <= 2 for chunk in chunks)
    # The workflow/skill and workspace/dashboard pairs include real subprocess
    # boundaries and measured above 300 seconds on a loaded Windows host. Each
    # chunk remains bounded, but the bound must cover its owned behavior rather
    # than truncate a still-progressing test process.
    assert all(chunk["timeout_seconds"] == 900 for chunk in chunks)
    assert len({chunk["input_sha256"] for chunk in chunks}) == len(chunks)
    assert [member for chunk in chunks for member in chunk["members"]] == members
    first_inputs = set(chunks[0]["inputs"])
    second_inputs = set(chunks[1]["inputs"])
    assert "tests/test_agent_builder.py" in first_inputs
    assert "tests/test_agent_builder.py" not in second_inputs
    assert "runtime/studio_api.py" in first_inputs & second_inputs


def test_section_chunk_receipt_is_atomic_bounded_and_content_addressed(tmp_path):
    section = {
        "section": "studio-memory-graph",
    }
    chunk = {
        "chunk_id": "chunk-03",
        "input_sha256": "a" * 64,
        "member_count": 2,
    }
    receipt = section_chunk_receipt(
        section,
        chunk,
        {
            "valid": True,
            "exit_code": 0,
            "timed_out": False,
            "duration_seconds": 0.25,
        },
    )
    target = write_section_chunk_receipt(tmp_path, receipt)
    assert target == section_chunk_receipt_path(
        tmp_path, "studio-memory-graph", "chunk-03"
    )
    assert read_section_chunk_receipt(
        tmp_path, "studio-memory-graph", "chunk-03"
    ) == receipt
    assert receipt["passed"] is True
    assert len(receipt["receipt_sha256"]) == 64
    assert not list(target.parent.glob("*.tmp"))
    target.write_text(
        json.dumps({**receipt, "passed": False}), encoding="utf-8"
    )
    assert read_section_chunk_receipt(
        tmp_path, "studio-memory-graph", "chunk-03"
    ) == {}


def test_trailing_recursive_section_pattern_includes_nested_files(tmp_path):
    nested = tmp_path / "extension" / "media" / "nested" / "view.js"
    nested.parent.mkdir(parents=True)
    nested.write_text("export const ready = true;\n", encoding="utf-8")
    assert _section_files(tmp_path, ["extension/media/**"]) == [
        "extension/media/nested/view.js"
    ]


def test_section_status_refuses_missing_or_stale_receipts(monkeypatch):
    from runtime import test_profiles

    original = test_profiles.resolve_test_section

    def stale(root, name):
        value = original(root, name)
        return {**value, "input_sha256": "0" * 64}

    monkeypatch.setattr(test_profiles, "resolve_test_section", stale)
    status = section_status(ROOT)
    assert not status["valid"]
    assert set(status["required_sections"]) == {
        "testing-governance",
        "dashboard-extension",
        "studio-memory-graph",
        "learning-promotion",
        "execution-placement",
        "hardware-routing",
    }


def test_certification_groups_are_exhaustive_exclusive_and_bounded():
    groups = resolve_test_groups(ROOT)
    members = [member for group in groups for member in group["members"]]
    discovered = sorted(
        path.relative_to(ROOT).as_posix() for path in (ROOT / "tests").glob("test_*.py")
    )
    assert sorted(members) == discovered
    assert len(members) == len(set(members))
    assert sum(group["parallel_safe"] for group in groups) == 0
    assert all(group["inputs"] and len(group["input_sha256"]) == 64 for group in groups)
    names = [group["group"] for group in groups]
    core_groups = [
        group for group in groups if group["group"].startswith("core-")
    ]
    assert all(group["parallel_safe"] is False for group in core_groups)
    assert names.index("derived-integrity") > names.index("structural-adversarial")
    derived = next(group for group in groups if group["group"] == "derived-integrity")
    assert "tests/test_completion_status.py" in derived["members"]
    exact = next(group for group in groups if group["group"] == "exact-installed")
    assert "tests/test_installed_wheel_e2e.py" in exact["members"]
    assert "registry/python_surface_ownership.json" in exact["inputs"]
    assert "registry/artifact_reachability.json" in exact["inputs"]
    structural = next(
        group for group in groups if group["group"] == "structural-adversarial"
    )
    assert structural["scan_inventory_current"] is True
    assert not any(
        path.startswith((".tmp/", ".px/preserved-extension-installations/"))
        for path in structural["scan_inputs"]
    )
    assert ".tmp_query_controls.js" not in structural["scan_inputs"]
    assert ".tmp_surface_controls.js" not in structural["scan_inputs"]
    assert (
        ".px/skills/audit-incomplete-implementations/scripts/audit_incomplete.py"
        in structural["inputs"]
    )
    assert "registry/incomplete_finding_reviews.json" in structural["inputs"]
    receipt = group_receipt(
        exact,
        {
            "exit_code": 0,
            "timed_out": False,
            "duration_seconds": 1.0,
            "stdout": "21 passed\n",
            "stderr": "",
        },
    )
    assert receipt["passed"] and len(receipt["receipt_sha256"]) == 64
    assert receipt["output_evidence"]["stdout_bytes"] == len("21 passed\n")
    assert receipt["output_evidence"]["failure_nodes"] == []

    failed = group_receipt(
        exact,
        {
            "exit_code": 1,
            "timed_out": False,
            "duration_seconds": 1.0,
            "stdout": "FAILED tests/test_example.py::test_case - AssertionError: secret\n",
            "stderr": "private diagnostic",
        },
    )
    assert failed["output_evidence"]["failure_nodes"] == [
        "tests/test_example.py::test_case"
    ]
    assert "secret" not in json.dumps(failed)
    assert "private diagnostic" not in json.dumps(failed)


def test_structural_group_identity_rejects_new_scannable_file(tmp_path):
    root = tmp_path / "project"
    (root / "tests").mkdir(parents=True)
    (root / "runtime").mkdir()
    (root / "registry").mkdir()
    (root / "tests/test_structural_integrity.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8"
    )
    (root / "registry/test_profiles.json").write_text(
        json.dumps(
            {
                "environment": {},
                "certification": {"required_groups": ["structural-adversarial"]},
                "groups": {
                    "structural-adversarial": {
                        "include_patterns": ["tests/test_*.py"],
                        "input_patterns": [],
                        "parallel_safe": False,
                        "timeout_seconds": 30,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    index = build_test_group_index(root)
    (root / "registry/test_group_index.json").write_text(
        json.dumps(index), encoding="utf-8"
    )
    assert resolve_test_groups(root)[0]["index_current"] is True
    (root / "runtime/new_surface.py").write_text("VALUE = 1\n", encoding="utf-8")
    assert "runtime/new_surface.py" in _structural_scan_files(root)
    changed = resolve_test_groups(root)[0]
    assert changed["scan_inventory_current"] is False
    assert changed["index_current"] is False


def test_group_status_is_receipt_driven_and_covers_every_test_file():
    status = group_status(ROOT)
    assert status["member_count"] == len(tuple((ROOT / "tests").glob("test_*.py")))
    assert set(status["required_groups"]) == {
        "core-a-f",
        "core-g-m",
        "core-n-s",
        "core-t-z",
        "process-recovery",
        "exact-installed",
        "release-build",
        "release-audit",
        "derived-integrity",
        "structural-adversarial",
    }


def _write_repair_campaign(root: Path, **changes: object) -> None:
    value = {
        "schema_version": "px.repair-campaign/1.0",
        "campaign_id": "test-campaign",
        "phase": "repair",
        "intake_open": True,
        "unresolved": ["studio-operability"],
    }
    value.update(changes)
    path = root / "registry/repair_campaign.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_processing_order_allows_focused_work_but_blocks_expensive_closure(tmp_path):
    _write_repair_campaign(tmp_path)
    assert require_processing_stage(tmp_path, "focused_test")["stage_allowed"] is True
    assert require_processing_stage(tmp_path, "governed_section")["stage_allowed"] is True
    for stage in ("revision_reconciliation", "full_profile", "validate", "package", "certify"):
        with pytest.raises(ProcessingOrderBlocked, match=stage):
            require_processing_stage(tmp_path, stage)


def test_processing_order_open_work_blocks_closure_even_with_advanced_phase(tmp_path):
    _write_repair_campaign(tmp_path, phase="validated")
    with pytest.raises(ProcessingOrderBlocked, match="intake_open=true"):
        require_processing_stage(tmp_path, "package")
    _write_repair_campaign(tmp_path, phase="validated", intake_open=False)
    with pytest.raises(ProcessingOrderBlocked, match="studio-operability"):
        require_processing_stage(tmp_path, "package")


def test_processing_order_advances_only_after_each_predecessor(tmp_path):
    _write_repair_campaign(tmp_path, phase="repair_frozen", intake_open=False, unresolved=[])
    assert require_processing_stage(tmp_path, "revision_reconciliation")["stage_allowed"] is True
    with pytest.raises(ProcessingOrderBlocked, match="full_profile"):
        require_processing_stage(tmp_path, "full_profile")
    _write_repair_campaign(tmp_path, phase="sections_current", intake_open=False, unresolved=[])
    assert require_processing_stage(tmp_path, "full_profile")["stage_allowed"] is True
    with pytest.raises(ProcessingOrderBlocked, match="validate"):
        require_processing_stage(tmp_path, "validate")


def test_processing_order_absent_campaign_preserves_unmanaged_repository(tmp_path):
    status = repair_campaign_status(tmp_path)
    assert status["managed"] is False
    assert require_processing_stage(tmp_path, "certify")["managed"] is False


def test_managed_project_missing_campaign_fails_closed_and_initializer_is_idempotent(
    tmp_path,
):
    marker = tmp_path / ".engineering-bootstrap/project-record.json"
    marker.parent.mkdir(parents=True)
    marker.write_text(
        json.dumps({"project_id": "prj_demo"}) + "\n", encoding="utf-8"
    )
    with pytest.raises(ProcessingOrderBlocked, match="managed project is missing"):
        require_processing_stage(tmp_path, "focused_test")
    created = initialize_project_repair_campaign(tmp_path)
    assert created["initialized"] is True
    assert created["phase"] == "intake"
    assert created["intake_open"] is True
    assert created["unresolved"] == ["initial-operational-intake"]
    repeated = initialize_project_repair_campaign(tmp_path)
    assert repeated["initialized"] is False
    with pytest.raises(ProcessingOrderBlocked, match="certify requires"):
        require_processing_stage(tmp_path, "certify")
