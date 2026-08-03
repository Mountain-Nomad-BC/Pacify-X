from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import tracemalloc
import unittest

from builders.common import BuilderError
from builders.orchestration_builder import OrchestrationRequest, ResourceBudget, WorkflowStep, propose_orchestration
from runtime.commissioning import commission, project_check
from runtime.graphs import validate_orchestration
from runtime.intake import inspect_existing_project
from runtime.lazy_loader import LazySkillLoader
from runtime.recovery import DurableState, reconcile_resume
from runtime.registry import skill_navigation_index, validate_registry
from runtime.scheduler import ResourcePolicy, ResourceScheduler
from runtime.skill_navigator import select_working_set
from runtime.skill_navigator import CapabilitySummary
from runtime.startup import bounded_startup


ROOT = Path(__file__).parents[1]


def contract(capability_id: str, consumes: tuple[str, ...], provides: tuple[str, ...], effects: tuple[str, ...] = ("read_local",)) -> dict:
    return {
        "id": capability_id, "status": "active", "consumes": list(consumes), "provides": list(provides),
        "dependencies": [], "conflicts": [], "effects": list(effects),
        "cost": {"max_tool_calls": 1}, "latency": {"max_seconds": 1},
        "validation": {"failed": 0}, "evidence": {"status": "current"},
    }


class IntegrationAcceptanceTests(unittest.TestCase):
    def test_working_set_never_leaves_orphan_dependencies_after_bundle_rejection(self) -> None:
        index = (
            CapabilitySummary("best", "exact goal", aliases=("exact goal",), status="active"),
            CapabilitySummary("parent", "goal", dependencies=("dep-a", "dep-b"), status="active"),
            CapabilitySummary("dep-a", "support", status="active"),
            CapabilitySummary("dep-b", "support", status="active"),
        )
        selected = select_working_set("exact goal", index, default_limit=2)
        self.assertEqual(selected.capability_ids, ("best",))
        self.assertNotIn("dep-a", selected.capability_ids)
        self.assertIn(("parent", "dependency bundle does not fit: dep-b"), selected.rejected)

    def test_full_skill_catalog_starts_dormant_selects_bounded_set_and_unloads(self) -> None:
        tracemalloc.start()
        snapshot = bounded_startup(ROOT, ROOT, tool_names=(), max_probe_workers=1)
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        self.assertEqual(snapshot.hydrated_skill_bodies, ())
        self.assertEqual(len(snapshot.skill_catalog_metadata), 89)
        self.assertLess(peak, 8 * 1024 * 1024)
        loader = LazySkillLoader.from_catalog(ROOT, max_active=3, max_bytes=262144)
        index = skill_navigation_index(ROOT)
        for goal in ("python repair diagnosis", "security authorization governance", "research capability", "deployment testing evidence"):
            selected = select_working_set(goal, index)
            self.assertLessEqual(len(selected.capability_ids), 3)
            self.assertEqual(loader.active_ids, ())
            if selected.capability_ids:
                chosen = selected.capability_ids[0]
                loader.hydrate(chosen)
                self.assertEqual(loader.active_ids, (chosen,))
                loader.unload_all()
                self.assertEqual(loader.footprint_bytes, 0)

    def test_linear_branching_optional_cycle_privilege_adapter_and_resume_paths(self) -> None:
        contracts = (
            contract("read", ("request",), ("normalized",)),
            contract("check", ("normalized",), ("decision",)),
            contract("write", ("normalized",), ("receipt",), ("write_workspace",)),
        )
        valid = {
            "id": "branch", "version": "1", "status": "candidate", "inputs": ["request"], "outputs": ["decision"],
            "steps": [
                {"id": "read", "capability": "read", "depends_on": [], "effects": ["read_local"]},
                {"id": "left", "capability": "check", "depends_on": ["read"], "effects": ["read_local"]},
                {"id": "right", "capability": "check", "depends_on": ["read"], "optional_depends_on": ["telemetry"], "effects": ["read_local"]},
            ],
            "parallelism": {"max_agents": 2, "max_test_runners": 1}, "stop_conditions": ["policy_denied"],
            "resource_budget": {"max_tool_calls": 3, "max_seconds": 3},
        }
        self.assertEqual(validate_orchestration(valid, contracts), ())
        cycle = {**valid, "steps": [
            {"id": "a", "capability": "read", "depends_on": ["b"], "effects": ["read_local"]},
            {"id": "b", "capability": "check", "depends_on": ["a"], "effects": ["read_local"]},
        ]}
        self.assertTrue(any("cycle" in error for error in validate_orchestration(cycle, contracts)))

        proposal = propose_orchestration(
            OrchestrationRequest("mutating", ("normalized",), ("receipt",), (WorkflowStep("write", "write"),), ("policy_denied",), ResourceBudget(1, 1)),
            contracts,
        )
        self.assertTrue(proposal["body"]["approval_gates"][0]["required"])
        with self.assertRaisesRegex(BuilderError, "eligible producers"):
            propose_orchestration(
                OrchestrationRequest("missing-adapter", ("request",), ("decision",), (WorkflowStep("check", "check"),), ("blocked",), ResourceBudget(1, 1)),
                contracts,
            )
        interrupted = DurableState("pkg", ("read",), (("read", "1"),), (), ("E1",), (), ("check",))
        allowed, reasons = reconcile_resume(interrupted, actual_evidence=("E1",))
        self.assertFalse(allowed)
        self.assertIn("interrupted steps are non-certifying", reasons)

    def test_two_agent_resource_policy_enforces_ownership_heavy_lane_pressure_and_recovery(self) -> None:
        policy = ResourcePolicy(max_agents=2, max_light_lanes=2, max_heavy_lanes=1, lost_worker_seconds=5)
        scheduler = ResourceScheduler(policy)
        safe = {"agents": 0, "memory_percent": 20, "wsl_memory_percent": 20, "docker_memory_percent": 20, "gpu_percent": 20}
        self.assertTrue(scheduler.admit("primary", "heavy", safe, owned_paths=("runtime",)).admitted)
        self.assertFalse(scheduler.admit("overlap", "light", safe, owned_paths=("runtime/cli.py",)).admitted)
        self.assertFalse(scheduler.admit("heavy-two", "heavy", safe, owned_paths=("tests",)).admitted)
        self.assertTrue(scheduler.admit("helper", "light", safe, owned_paths=("builders",)).admitted)
        scheduler.assign_worker("agent-primary", "primary")
        scheduler.assign_worker("agent-helper", "helper")
        now = datetime.now(timezone.utc)
        scheduler.heartbeat("agent-helper", now - timedelta(seconds=10))
        self.assertEqual(scheduler.recover_lost(now), ("helper",))
        self.assertFalse(scheduler.admit("pressure", "light", {**safe, "wsl_memory_percent": 99}).admitted)

    def test_new_and_existing_project_modes_are_accepted_without_unauthorized_installation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            new_project = root / "new"
            result = commission(new_project, "new", apply=True, source_root=ROOT)
            self.assertEqual(result["effects"], ["read_local", "write_workspace"])
            self.assertTrue(project_check(new_project)["valid"])
            existing = root / "existing"
            existing.mkdir()
            (existing / "pyproject.toml").write_text("[project]\nname='existing'\n", encoding="utf-8")
            before = (existing / "pyproject.toml").read_bytes()
            intake = inspect_existing_project(existing)
            proposal = commission(existing, "existing", source_root=ROOT)
            self.assertEqual(proposal["effects"], ["read_local"])
            self.assertEqual(before, (existing / "pyproject.toml").read_bytes())
            self.assertEqual(intake["mode"], "read_only")
            self.assertNotIn("install_tool", proposal["effects"])
        self.assertTrue(validate_registry(ROOT)["valid"])


if __name__ == "__main__":
    unittest.main()
