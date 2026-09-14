"""Causal memory frontier, namespace, accounting and pointer-custody cases."""

from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import inspect
import json
import math
import os
from pathlib import Path
import pytest

from runtime.memory_fabric import MemoryRecord
from runtime.memory_intelligence import (
    RankedMemory,
    assemble_context,
    compact_tool_results,
    restore_offload,
)
from runtime.memory_operations import (
    GraphNode,
    SessionEvent,
    SessionSummaryLedger,
    build_graph_clusters,
)

NOW = datetime(2026, 9, 9, tzinfo=timezone.utc)


def hit(identity="m", *, layer="L1", summary="fact", score=0.5):
    record = MemoryRecord(
        identity,
        "w",
        "p",
        "owner",
        "session",
        "lease",
        "Title",
        "fact",
        summary,
        "source",
        "a" * 64,
        "E-1",
        "observation",
        0.9,
        "direct",
        "internal",
        ("p",),
        NOW,
        NOW,
        layer=layer,
    )
    return RankedMemory(record, score, {}, ())


def messages(content="x" * 3000):
    return [
        {"id": "m1", "role": "tool", "tool_call_id": "call-1", "content": content},
        {"id": "m2", "role": "user", "content": "keep"},
    ]


def restore_custody_probe(root, pointer):
    # Exercise both the original unsafe API and the explicit-project repair.
    kwargs = (
        {"project_id": "p"}
        if "project_id" in inspect.signature(restore_offload).parameters
        else {}
    )
    return restore_offload(root, pointer, **kwargs)


def legacy(root, session, *, recorded_session=None, end=3):
    directory = root / session
    directory.mkdir()
    payload = {
        "schema_version": "1.0",
        "session_id": recorded_session or session,
        "start_event_id": 1,
        "end_event_id": end,
        "processed_event_count": end,
        "lifecycle": "checkpoint",
        "summary": ["legacy"],
        "source_sha256": "a" * 64,
        "created_utc": NOW.isoformat(),
    }
    path = directory / "000001-checkpoint.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_context_accounting_includes_every_rendered_separator():
    package = assemble_context([hit("a"), hit("b")], max_chars=1000)
    assert package.used_chars == len(package.text)


@pytest.mark.parametrize(
    "rows", [[hit(score=math.nan)], [hit(), hit()], [hit(layer="unknown")]]
)
def test_context_rejects_nonfinite_ambiguous_or_unknown_records(rows):
    with pytest.raises(ValueError):
        assemble_context(rows)


def test_context_oversized_frontier_is_not_silently_consumed():
    def records():
        for i in range(10001):
            yield hit(str(i), layer="L0")
        pytest.fail("context consumed beyond its bounded witness")

    with pytest.raises(ValueError):
        assemble_context(records())


def test_graph_reads_only_selected_prefix_and_one_truncation_witness():
    def nodes():
        for i in range(4):
            yield GraphNode(str(i), "text", ())
        pytest.fail("graph consumed the unselected tail")

    result = build_graph_clusters(nodes(), [], max_initial_nodes=3)
    assert result.truncated
    assert sum(len(c.member_ids) for c in result.clusters) == 3


def test_graph_rejects_duplicate_retained_identity():
    with pytest.raises(ValueError):
        build_graph_clusters([GraphNode("x", "a", ()), GraphNode("x", "b", ())], [])


def test_graph_bounds_edge_observations_even_when_duplicates_collapse():
    def edges():
        for _ in range(20001):
            yield ("a", "b")
        pytest.fail("edge stream consumed beyond budget witness")

    with pytest.raises(ValueError):
        build_graph_clusters(
            [GraphNode("a", "text", ()), GraphNode("b", "text", ())], edges()
        )


@pytest.mark.parametrize("bound", [True, 1.5, 10001])
def test_graph_bounds_are_exact_declared_integers(bound):
    with pytest.raises(ValueError):
        build_graph_clusters([], [], max_initial_nodes=bound)


def test_summary_dot_identity_never_writes_above_root(tmp_path, monkeypatch):
    import runtime.memory_operations as operations

    root = tmp_path / "summaries"
    root.mkdir()
    original = operations._write_new

    def contained(path, payload):
        assert path.resolve().is_relative_to(root.resolve()), "summary escaped root"
        original(path, payload)

    monkeypatch.setattr(operations, "_write_new", contained)
    ledger = SessionSummaryLedger(root)
    result = ledger.summarize("..", [SessionEvent(1, "message", "fact", NOW)])
    assert result and (root / result.path).resolve().is_relative_to(root.resolve())


@pytest.mark.parametrize("identities", [("a/b", "a?b"), ("Alpha", "alpha")])
def test_session_identity_encoding_does_not_share_cursors(tmp_path, identities):
    ledger = SessionSummaryLedger(tmp_path)
    results = [
        ledger.summarize(identity, [SessionEvent(1, "message", identity, NOW)])
        for identity in identities
    ]
    assert all(results)
    assert results[0].path.casefold() != results[1].path.casefold()


def test_foreign_legacy_history_cannot_supply_a_cursor(tmp_path):
    legacy(tmp_path, "session", recorded_session="foreign", end=99)
    with pytest.raises(ValueError):
        SessionSummaryLedger(tmp_path).last_event_id("session")


def test_matching_legacy_history_retains_cursor_without_rewrite(tmp_path):
    path = legacy(tmp_path, "session")
    before = path.read_bytes()
    ledger = SessionSummaryLedger(tmp_path)
    assert ledger.last_event_id("session") == 3
    result = ledger.summarize("session", [SessionEvent(4, "message", "new fact", NOW)])
    assert result.start_event_id == 4
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    "event",
    [
        SessionEvent(True, "message", "fact", NOW),
        SessionEvent(1, "message", 42, NOW),
        SessionEvent(-1, "message", "fact", NOW),
    ],
)
def test_summary_events_are_typed_before_cursor_or_write(tmp_path, event):
    with pytest.raises(ValueError):
        SessionSummaryLedger(tmp_path).summarize("session", [event])
    assert not list(tmp_path.iterdir())


def test_protected_tail_overflow_fails_before_any_apply_write(tmp_path):
    with pytest.raises(ValueError, match="budget|fit|overflow"):
        compact_tool_results(
            tmp_path,
            messages(),
            project_id="p",
            max_chars=100,
            protected_tail=2,
            apply=True,
        )
    assert not list(tmp_path.iterdir())


def test_compaction_cannot_publish_an_unhelpful_larger_replacement(tmp_path):
    with pytest.raises(ValueError, match="budget|fit|overflow"):
        compact_tool_results(
            tmp_path,
            messages("x" * 150),
            project_id="p",
            max_chars=100,
            threshold=10,
            protected_tail=1,
            apply=True,
        )
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    "limits",
    [
        {"apply": "false"},
        {"max_chars": True},
        {"protected_tail": True},
        {"threshold": "2000"},
    ],
)
def test_compaction_rejects_coercible_or_boolean_control_values(tmp_path, limits):
    with pytest.raises(ValueError):
        compact_tool_results(tmp_path, messages(), project_id="p", **limits)
    assert not list(tmp_path.iterdir())


def test_preview_pointer_is_explicitly_not_reversible(tmp_path):
    preview, pointers = compact_tool_results(
        tmp_path, messages(), project_id="p", max_chars=1000, protected_tail=1
    )
    assert pointers and pointers[0].reversible is False
    assert preview[0].get("_offloaded") is not True
    assert not list(tmp_path.iterdir())


def test_restore_requires_expected_project_before_object_read(tmp_path):
    _, pointers = compact_tool_results(
        tmp_path,
        messages(),
        project_id="p",
        max_chars=1000,
        protected_tail=1,
        apply=True,
    )
    with pytest.raises(ValueError, match="project"):
        restore_offload(tmp_path, pointers[0], project_id="foreign")


def test_restore_rejects_off_root_locator_before_read(tmp_path, monkeypatch):
    _, pointers = compact_tool_results(
        tmp_path,
        messages(),
        project_id="p",
        max_chars=1000,
        protected_tail=1,
        apply=True,
    )
    original = Path.open

    def no_foreign(path, *args, **kwargs):
        assert path.resolve().is_relative_to(tmp_path.resolve()), (
            "foreign object opened"
        )
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", no_foreign)
    with pytest.raises(ValueError):
        restore_custody_probe(
            tmp_path, replace(pointers[0], storage_locator="../foreign.txt")
        )


def test_object_digest_alone_is_not_a_persisted_pointer_receipt(tmp_path):
    from runtime.memory_intelligence import OffloadPointer

    content = "body"
    digest = hashlib.sha256(content.encode()).hexdigest()
    relative = f".memory-control/offload/objects/{digest[:2]}/{digest}.txt"
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.write_text(content)
    pointer = OffloadPointer(
        "off_" + "a" * 24, "p", "m", "call", digest, "summary", relative
    )
    with pytest.raises(ValueError):
        restore_custody_probe(tmp_path, pointer)


def test_applied_offload_roundtrip_preserves_crlf_and_unicode(tmp_path):
    content = "a\r\n\u03bb\n" * 700
    _, pointers = compact_tool_results(
        tmp_path,
        messages(content),
        project_id="p",
        max_chars=1000,
        protected_tail=1,
        apply=True,
    )
    assert restore_custody_probe(tmp_path, pointers[0]) == content


def test_malformed_history_lifecycle_is_a_typed_failure(tmp_path):
    path = legacy(tmp_path, "session")
    data = json.loads(path.read_text())
    data["lifecycle"] = []
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        SessionSummaryLedger(tmp_path).last_event_id("session")


def test_legacy_summary_requires_valid_utf8_text(tmp_path):
    path = legacy(tmp_path, "session")
    data = json.loads(path.read_text())
    data["summary"] = ["\ud800"]
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        SessionSummaryLedger(tmp_path).last_event_id("session")


def test_oversized_history_is_rejected_before_open(tmp_path, monkeypatch):
    path = legacy(tmp_path, "session")
    path.write_bytes(b" " * (256 * 1024 + 1))
    original = Path.open

    def forbidden(source, *args, **kwargs):
        if source == path:
            pytest.fail("oversized history body opened")
        return original(source, *args, **kwargs)

    monkeypatch.setattr(Path, "open", forbidden)
    with pytest.raises(ValueError, match="budget"):
        SessionSummaryLedger(tmp_path).last_event_id("session")


def test_late_pointer_conflict_prevents_all_new_object_writes(tmp_path):
    source = [
        {"id": "a", "role": "tool", "tool_call_id": "ca", "content": "a" * 3000},
        {"id": "b", "role": "tool", "tool_call_id": "cb", "content": "b" * 3000},
        {"id": "tail", "role": "user", "content": "keep"},
    ]
    _, pointers = compact_tool_results(
        tmp_path, source, project_id="p", max_chars=2000, protected_tail=1
    )
    assert len(pointers) == 2
    conflict = (
        tmp_path
        / ".memory-control/offload/pointers"
        / (pointers[-1].pointer_id + ".json")
    )
    conflict.parent.mkdir(parents=True)
    conflict.write_text('{"wrong":true}')
    with pytest.raises(ValueError):
        compact_tool_results(
            tmp_path,
            source,
            project_id="p",
            max_chars=2000,
            protected_tail=1,
            apply=True,
        )
    assert not (tmp_path / ".memory-control/offload/objects").exists()


def test_protected_tail_and_original_message_are_unchanged(tmp_path):
    import copy

    source = messages()
    source[-1]["metadata"] = {"constraint": "preserve exactly"}
    before = copy.deepcopy(source)
    result, _ = compact_tool_results(
        tmp_path, source, project_id="p", max_chars=1000, protected_tail=1, apply=True
    )
    assert source == before and result[-1] == before[-1]
    assert sum(len(row["content"]) for row in result) <= 1000


def test_context_iterator_exhaustion_checks_its_cooperative_deadline(monkeypatch):
    import runtime.numeric_inputs as bounds

    clock = [0.0]
    monkeypatch.setattr(bounds.time, "monotonic", lambda: clock[0])

    def slow_exhaustion():
        yield hit()
        clock[0] = 61.0

    with pytest.raises(ValueError, match="duration"):
        assemble_context(slow_exhaustion())


@pytest.mark.skipif(os.name != "nt", reason="Windows junction contract")
@pytest.mark.parametrize("operation", ["summary", "compact", "restore"])
def test_memory_paths_refuse_actual_windows_junctions(tmp_path, operation):
    import _winapi

    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    if operation == "compact":
        _winapi.CreateJunction(str(outside), str(project / ".memory-control"))
        with pytest.raises(ValueError, match="linked"):
            compact_tool_results(
                project,
                messages(),
                project_id="p",
                max_chars=1000,
                protected_tail=1,
                apply=True,
            )
        assert not list(outside.iterdir())
    else:
        if operation == "restore":
            _, pointers = compact_tool_results(
                project,
                messages(),
                project_id="p",
                max_chars=1000,
                protected_tail=1,
                apply=True,
            )
        link = tmp_path / "linked"
        _winapi.CreateJunction(str(project), str(link))
        with pytest.raises(ValueError, match="linked"):
            if operation == "summary":
                SessionSummaryLedger(link)
            else:
                restore_offload(link, pointers[0], project_id="p")


def test_clustering_matches_exhaustive_shortest_path_order_for_four_nodes():
    from itertools import combinations, permutations

    names = tuple("abcd")
    pairs = tuple(combinations(names, 2))
    for mask in range(1 << len(pairs)):
        edges = [edge for index, edge in enumerate(pairs) if mask & (1 << index)]
        adjacency = {frozenset(edge) for edge in edges}
        for limit in range(1, 5):
            remaining = set(names)
            expected = []
            while remaining:
                seed = min(remaining)
                best = {seed: (seed,)}
                for length in range(1, len(remaining)):
                    for tail in permutations(sorted(remaining - {seed}), length):
                        path = (seed,) + tail
                        if all(
                            frozenset(edge) in adjacency for edge in zip(path, path[1:])
                        ):
                            old = best.get(path[-1])
                            if old is None or (len(path), path) < (len(old), old):
                                best[path[-1]] = path
                ordered = sorted(
                    best, key=lambda target: (len(best[target]), best[target])
                )[:limit]
                expected.append(tuple(ordered))
                remaining.difference_update(ordered)
            result = build_graph_clusters(
                [GraphNode(name, name, ("E-" + name,)) for name in names],
                edges,
                max_cluster_size=limit,
            )
            assert [row.member_ids for row in result.clusters] == expected
