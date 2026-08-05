from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from runtime.classifier import classify_task
from runtime.lazy_loader import LazySkillLoader, SkillDescriptor
from runtime.planner import (
    Requirement,
    build_work_package,
    detect_scope_drift,
    load_work_package,
    save_work_package,
)
from runtime.recovery import DurableState, load_state, persist_state, reconcile_resume
from runtime.scheduler import ResourcePolicy, ResourceScheduler
from runtime.skill_navigator import CapabilitySummary, select_working_set
from runtime.startup import bounded_startup


ROOT = Path(__file__).parents[1]


class RuntimeWave4Tests(unittest.TestCase):
    def test_bounded_startup_loads_metadata_and_gracefully_marks_missing_tools(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            snapshot = bounded_startup(
                ROOT,
                project,
                tool_names=("available", "missing"),
                tool_resolver=lambda name: "/tool" if name == "available" else None,
                max_probe_workers=2,
            )
            self.assertEqual(snapshot.hydrated_skill_bodies, ())
            self.assertEqual(
                dict(snapshot.tools), {"available": "/tool", "missing": None}
            )
            self.assertLessEqual(
                len(snapshot.capabilities),
                snapshot.config.budget.max_initial_registry_records,
            )
            self.assertEqual(snapshot.project_profile["status"], "unconfigured")

    def test_classifier_is_multi_domain_explainable_and_low_confidence_is_bounded(
        self,
    ) -> None:
        record = classify_task("Build a secure retrieval workflow and validate it")
        self.assertIn("retrieval", record.domains)
        self.assertIn("validation", record.domains)
        self.assertIn("mutation", record.task_classes)
        self.assertEqual(record.route, "select")
        low = classify_task("consider the situation")
        self.assertEqual(low.route, "broader_metadata_lookup")
        self.assertTrue(low.explanation)

    def test_selector_enforces_budget_dependencies_redundancy_and_is_deterministic(
        self,
    ) -> None:
        index = (
            CapabilitySummary(
                "base", "support workflow", aliases=("workflow",), risk="R0"
            ),
            CapabilitySummary(
                "primary",
                "build workflow",
                aliases=("build workflow",),
                dependencies=("base",),
                redundancy_group="builders",
            ),
            CapabilitySummary(
                "duplicate",
                "build workflow",
                aliases=("build workflow",),
                redundancy_group="builders",
                cost=4,
            ),
            CapabilitySummary("extra", "build workflow", aliases=("build workflow",)),
        )
        first = select_working_set("build workflow", index, default_limit=3)
        second = select_working_set("build workflow", reversed(index), default_limit=3)
        self.assertEqual(first, second)
        self.assertIn("base", first.capability_ids)
        self.assertLessEqual(len(first.capability_ids), 3)
        self.assertTrue(any("redundant" in reason for _, reason in first.rejected))

    def test_ten_thousand_descriptors_remain_unloaded_until_selected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "body.md").write_text("small body", encoding="utf-8")
            (root / "reference.md").write_text("contract", encoding="utf-8")
            descriptors = tuple(
                SkillDescriptor(f"skill-{index}", "body.md") for index in range(9999)
            ) + (SkillDescriptor("selected", "body.md", references=("reference.md",)),)
            loader = LazySkillLoader(root, descriptors, max_active=2, max_bytes=100)
            self.assertEqual(loader.active_ids, ())
            first = loader.hydrate("selected", include_references=True)
            second = loader.hydrate("selected", include_references=True)
            self.assertIs(first, second)
            self.assertEqual(loader.active_ids, ("selected",))
            self.assertTrue(loader.unload("selected"))
            self.assertEqual(loader.footprint_bytes, 0)

    def test_deferred_skill_body_cannot_be_hydrated_before_admission(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "body.md").write_text("candidate", encoding="utf-8")
            loader = LazySkillLoader(
                root,
                (SkillDescriptor("candidate", "body.md", status="mapped_deferred"),),
            )
            with self.assertRaisesRegex(PermissionError, "not admitted"):
                loader.hydrate("candidate")

    def test_frozen_plan_maps_every_requirement_persists_and_detects_drift(
        self,
    ) -> None:
        requirements = (
            Requirement("r1", "inspect repository", "repository-reader", "existing"),
            Requirement("r2", "unknown adapter", None, "blocked"),
        )
        package = build_work_package(
            "onboard", requirements, deferred=("non-blocking idea",)
        )
        self.assertEqual(package.blocked_requirements, ("r2",))
        self.assertEqual(len(package.nodes), 2)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            save_work_package(package, path)
            self.assertEqual(load_work_package(path), package)
        self.assertFalse(detect_scope_drift(package, requirements))
        self.assertTrue(
            detect_scope_drift(
                package, requirements + (Requirement("r3", "new", "builder"),)
            )
        )

    def test_scheduler_serializes_heavy_lane_and_detects_pressure_and_lost_worker(
        self,
    ) -> None:
        scheduler = ResourceScheduler(
            ResourcePolicy(
                max_agents=2,
                max_light_lanes=2,
                max_heavy_lanes=1,
                lost_worker_seconds=10,
            )
        )
        self.assertTrue(
            scheduler.admit(
                "one", "heavy", {"agents": 0, "memory_percent": 20}
            ).admitted
        )
        self.assertFalse(
            scheduler.admit(
                "two", "heavy", {"agents": 0, "memory_percent": 20}
            ).admitted
        )
        self.assertFalse(
            scheduler.admit(
                "memory", "light", {"agents": 0, "memory_percent": 99}
            ).admitted
        )
        now = datetime.now(timezone.utc)
        scheduler.heartbeat("worker", now - timedelta(seconds=20))
        self.assertEqual(scheduler.lost_workers(now), ("worker",))

    def test_recovery_is_idempotent_and_interrupted_steps_are_non_certifying(
        self,
    ) -> None:
        state = DurableState(
            "pkg",
            ("inspect",),
            (("reader", "1.0"),),
            ("approval-1",),
            ("evidence-1",),
            ("write-1",),
            ("test",),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            persist_state(state, path)
            loaded = load_state(path)
            persist_state(state, path)
            self.assertEqual(
                len(list((path.parent / ".history" / path.name).glob("*.json"))), 1
            )
        self.assertEqual(loaded, state)
        allowed, reasons = reconcile_resume(
            state, actual_evidence=("evidence-1",), requested_idempotency_key="write-1"
        )
        self.assertFalse(allowed)
        self.assertTrue(any("non-certifying" in reason for reason in reasons))
        self.assertTrue(any("idempotency" in reason for reason in reasons))


if __name__ == "__main__":
    unittest.main()
