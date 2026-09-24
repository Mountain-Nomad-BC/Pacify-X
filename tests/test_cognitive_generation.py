from __future__ import annotations

import importlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

EXTERNAL_ROOT = os.environ.get("PX_PERSISTENT_MEMORY_EXTERNAL_ROOT")
if EXTERNAL_ROOT:
    sys.path.insert(0, EXTERNAL_ROOT)
    importlib.invalidate_caches()
PACKAGE_AVAILABLE = importlib.util.find_spec("pacifyx_memory") is not None
if PACKAGE_AVAILABLE:
    from pacifyx_memory.cognitive_generation import CognitiveEdge, CognitiveGenerationPublisher, CognitiveObjectRef, VectorBinding
    from pacifyx_memory.cognitive_storage import CognitivePaths
else:
    CognitiveEdge = CognitiveGenerationPublisher = CognitiveObjectRef = VectorBinding = CognitivePaths = None


def obj(object_id: str, revision: int, locator: str, sha: str, *, vector_id: int | None = None, namespace: str = "private") -> CognitiveObjectRef:
    vector = None if vector_id is None else VectorBinding(vector_id, "embed:qwen", "r1", "retrieval:gen1")
    return CognitiveObjectRef(
        object_id=object_id,
        revision=revision,
        kind="knowledge" if object_id.startswith("knowledge:") else "memory",
        title=object_id,
        summary="bounded summary",
        content_sha256=sha,
        locator=locator,
        privacy_namespace=namespace,
        project_id="project:px",
        status="trusted",
        subjects=("subject:pacify-x",),
        relations=("relation:depends-on",),
        retrieval_active=True,
        vector=vector,
    )


@unittest.skipUnless(PACKAGE_AVAILABLE, "external cognitive package source not supplied to test environment")
class CognitiveGenerationTests(unittest.TestCase):
    def setup_root(self, td: str):
        root = Path(td) / "external"
        CognitivePaths(root).init()
        a = root / "Cog _Nets" / "Private" / "Memory" / "Records" / "aa" / "memory-a" / "1.json"
        b = root / "Cog _Nets" / "Private" / "Knowldge" / "Records" / "knowledge-b" / "revisions" / ("b" * 64 + ".json")
        a.parent.mkdir(parents=True, exist_ok=True); b.parent.mkdir(parents=True, exist_ok=True)
        a.write_text('{"id":"memory:a"}\n', encoding="utf-8")
        b.write_text('{"id":"knowledge:b"}\n', encoding="utf-8")
        return root, a.relative_to(root).as_posix(), b.relative_to(root).as_posix()

    def test_atomic_generation_publish_and_idempotent_repeat(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root, a_loc, b_loc = self.setup_root(td)
            pub = CognitiveGenerationPublisher(root)
            objects = [obj("memory:a", 1, a_loc, "a" * 64, vector_id=11), obj("knowledge:b", 1, b_loc, "b" * 64, vector_id=12)]
            edges = [CognitiveEdge("memory:a", 1, "depends-on", "knowledge:b", 1)]
            first = pub.publish(objects, edges, privacy_namespace="private", source_event_seq=10, supplied_authority=True)
            self.assertTrue(first["published"])
            current_before = pub.current.read_bytes()
            second = pub.publish(objects, edges, privacy_namespace="private", source_event_seq=10, supplied_authority=True)
            self.assertFalse(second["published"])
            self.assertEqual(first["generation_id"], second["generation_id"])
            self.assertEqual(current_before, pub.current.read_bytes())
            verified = pub.verify_current()
            self.assertTrue(verified["verified"])
            graph = json.loads((pub.generations / first["generation_id"] / "graph.json").read_text())
            self.assertEqual(1, len(graph["edges"]))

    def test_crash_before_current_switch_keeps_prior_generation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root, a_loc, b_loc = self.setup_root(td)
            pub = CognitiveGenerationPublisher(root)
            old = [obj("memory:a", 1, a_loc, "a" * 64)]
            first = pub.publish(old, [], privacy_namespace="private", source_event_seq=1, supplied_authority=True)
            old_current = pub.current.read_bytes()
            updated_file = root / "Cog _Nets" / "Private" / "Memory" / "Records" / "aa" / "memory-a" / "2.json"
            updated_file.write_text('{"id":"memory:a","revision":2}\n', encoding="utf-8")
            new = [obj("memory:a", 2, updated_file.relative_to(root).as_posix(), "c" * 64)]
            def fault(stage: str) -> None:
                if stage == "generation:committed-before-current":
                    raise RuntimeError("injected crash")
            with self.assertRaisesRegex(RuntimeError, "injected"):
                pub.publish(new, [], privacy_namespace="private", source_event_seq=2, expected_current_generation=first["generation_id"], supplied_authority=True, fault_injector=fault)
            self.assertEqual(old_current, pub.current.read_bytes())
            self.assertEqual(first["generation_id"], pub.verify_current()["generation_id"])
            recovered = pub.publish(new, [], privacy_namespace="private", source_event_seq=2, expected_current_generation=first["generation_id"], supplied_authority=True)
            self.assertNotEqual(first["generation_id"], recovered["generation_id"])
            self.assertEqual(recovered["generation_id"], pub.verify_current()["generation_id"])

    def test_crash_after_current_switch_can_reconstruct_missing_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root, a_loc, _ = self.setup_root(td)
            pub = CognitiveGenerationPublisher(root)
            objects = [obj("memory:a", 1, a_loc, "a" * 64)]
            def fault(stage: str) -> None:
                if stage == "generation:current-published":
                    raise RuntimeError("after-current")
            with self.assertRaisesRegex(RuntimeError, "after-current"):
                pub.publish(objects, [], privacy_namespace="private", source_event_seq=1, supplied_authority=True, fault_injector=fault)
            current = pub.verify_current()
            receipt = pub.receipts / f"{current['generation_id']}.json"
            self.assertFalse(receipt.exists())
            retry = pub.publish(objects, [], privacy_namespace="private", source_event_seq=1, supplied_authority=True)
            self.assertFalse(retry["published"])
            self.assertTrue(receipt.is_file())

    def test_fail_closed_on_missing_endpoint_mixed_privacy_and_vector_collision(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root, a_loc, b_loc = self.setup_root(td)
            pub = CognitiveGenerationPublisher(root)
            a = obj("memory:a", 1, a_loc, "a" * 64, vector_id=1)
            b = obj("knowledge:b", 1, b_loc, "b" * 64, vector_id=1)
            with self.assertRaisesRegex(ValueError, "vector_id collision"):
                pub.publish([a, b], [], privacy_namespace="private", source_event_seq=1, supplied_authority=True)
            with self.assertRaisesRegex(ValueError, "endpoint"):
                pub.publish([a], [CognitiveEdge("memory:a", 1, "depends-on", "knowledge:missing", 1)], privacy_namespace="private", source_event_seq=1, supplied_authority=True)
            public_b = obj("knowledge:b", 1, b_loc, "b" * 64, namespace="public")
            with self.assertRaisesRegex(ValueError, "mix privacy"):
                pub.publish([a, public_b], [], privacy_namespace="private", source_event_seq=1, supplied_authority=True)
            with self.assertRaises(PermissionError):
                pub.publish([a], [], privacy_namespace="private", source_event_seq=1, supplied_authority=False)

    def test_locator_change_creates_new_generation_without_rewriting_edge_identity(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root, a_loc, b_loc = self.setup_root(td)
            pub = CognitiveGenerationPublisher(root)
            edge = CognitiveEdge("memory:a", 1, "depends-on", "knowledge:b", 1)
            first = pub.publish([obj("memory:a", 1, a_loc, "a"*64), obj("knowledge:b", 1, b_loc, "b"*64)], [edge], privacy_namespace="private", source_event_seq=1, supplied_authority=True)
            moved = root / "Cog _Nets" / "Private" / "Memory" / "Cold" / "Daily" / "2026" / "09" / "memory-a.json"
            moved.parent.mkdir(parents=True, exist_ok=True); moved.write_text('{"id":"memory:a"}\n', encoding="utf-8")
            second = pub.publish([obj("memory:a", 1, moved.relative_to(root).as_posix(), "a"*64), obj("knowledge:b", 1, b_loc, "b"*64)], [edge], privacy_namespace="private", source_event_seq=2, expected_current_generation=first["generation_id"], supplied_authority=True)
            self.assertNotEqual(first["generation_id"], second["generation_id"])
            g1 = json.loads((pub.generations / first["generation_id"] / "graph.json").read_text())
            g2 = json.loads((pub.generations / second["generation_id"] / "graph.json").read_text())
            self.assertEqual(g1["edges"], g2["edges"])


if __name__ == "__main__":
    unittest.main()
