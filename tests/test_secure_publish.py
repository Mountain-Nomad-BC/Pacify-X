"""Causal persistence regressions for PX-AUD-031..036/046/048/059."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import os

import pytest

from runtime.secure_publish import atomic_write_bytes


def test_cleanup_refusal_does_not_hide_writer_failure_and_exposes_retained_image(tmp_path, monkeypatch):
    from runtime import secure_publish
    target = tmp_path / "cleanup-refused.json"
    target.write_bytes(b"previous")
    failure = ValueError("primary writer failure")
    def writer(stream):
        stream.write(b"unpublished partial image")
        raise failure
    def refuse(*args, **kwargs):
        raise PermissionError("injected cleanup sharing refusal")
    monkeypatch.setattr(secure_publish.os, "unlink", refuse)
    with pytest.raises(ValueError) as caught:
        secure_publish.atomic_write_stream(target, writer)
    assert caught.value is failure
    assert target.read_bytes() == b"previous"
    retained = list(tmp_path.glob("*.prepared"))
    assert len(retained) == 1
    assert retained[0].read_bytes() == b"unpublished partial image"
    assert caught.value.publication_cleanup["retained_image"] == str(retained[0])
    assert caught.value.publication_cleanup["cleanup_verified"] is False


def _writer(case, root, monkeypatch):
    if case in {"intent", "lease", "queue"}:
        from runtime.effect_intent import EffectIntentLedger
        from runtime.scope_lease import ScopeLeaseStore
        from runtime.mutation_queue import MutationQueue
        cls, prefix, image = {
            "intent": (EffectIntentLedger, "effect-intents", {"intents": [], "checkpoints": []}),
            "lease": (ScopeLeaseStore, "scope-leases", []),
            "queue": (MutationQueue, "mutation-queue", []),
        }[case]
        owner = cls(root)
        return owner.path, owner.path.parent / f".{prefix}-{os.getpid()}.prepared", lambda: owner._store(image)
    if case == "plan":
        from runtime.plan_registry import _write_digest_bound
        target = root / "plan.json"
        return target, target.with_name(target.name + ".new"), lambda: _write_digest_bound(target, {"value": 1})
    if case == "entity":
        from runtime.semantic_entity import EntityRegistry, publish_registry, published_registry_path
        registry = EntityRegistry()
        target = published_registry_path(root)
        name = f".entity-registry-{hashlib.sha256(registry.snapshot_bytes()).hexdigest()[:16]}.prepared"
        return target, target.parent / name, lambda: publish_registry(registry, root)
    if case == "nsai":
        from runtime import nsai_knowledge as owner
        library = root / "knowledge/nsai"
        library.mkdir(parents=True)
        monkeypatch.setattr(owner, "build_nsai_index", lambda *a, **k: {"objects": []})
        target = library / "index.json"
        return target, target.with_name(target.name + ".tmp"), lambda: owner.write_nsai_index(library)
    if case == "sandbox":
        from runtime.vscode_model_bridge import set_sandbox_mode
        target = root / ".agentic_engineering_os_px/sandbox/isolated-agent-sandbox.json"
        return target, target.with_name(target.name + ".prepared"), lambda: set_sandbox_mode(
            root, root, {"schema_version": "px.isolated-agent-sandbox-request/1.0", "mode": "OFF"})
    if case == "boundary":
        from runtime import source_boundary as owner
        monkeypatch.setattr(owner, "validate_artifacts", lambda r: {"valid": True})
        monkeypatch.setattr(owner, "assert_generated_never_canonical_authority", lambda r: {"valid": True})
        target = root / owner.BOUNDARY_RELATIVE
        return target, target.with_name(target.name + ".new"), lambda: owner.write_boundary(root)
    if case == "freeze":
        from runtime import source_freeze as owner
        (root / "authored.txt").write_text("source", encoding="utf-8")
        monkeypatch.setattr(owner, "authored_paths", lambda r: ["authored.txt"])
        monkeypatch.setattr(owner, "_versions", lambda r: {})
        target = root / owner.FREEZE_RELATIVE
        return target, target.with_name(target.name + ".new"), lambda: owner.freeze_source(root, freeze_id="test")
    if case in {"tool", "tool-state"}:
        from runtime import tool_intake as owner
        monkeypatch.setattr(owner, "scan_project_tooling", lambda *a, **k: {"decision": "no_external_tooling"})
        # Tool intake publishes through the transactional WAL under the same
        # commissioning namespace the real owner reads, so the fixture must
        # hold a valid checkpoint there instead of a second legacy authority.
        # That namespace is the canonical control directory: the owner resolves
        # `control_path(root, "project-management")`, and a fixture seeded in the
        # legacy tree silently tests the wrong authority.
        directory = root / ".agentic_engineering_os_px/project-management"
        directory.mkdir(parents=True)
        (directory / "state.json").write_text(
            '{"checkpoint":{"revision":0},"evidence":{},"work":{}}', encoding="utf-8"
        )
        target = directory / ("state.json" if case == "tool-state" else "tool-intake.json")
        return target, target.with_suffix(".json.next"), lambda: owner.record_tool_intake(root, root, apply=True)
    raise AssertionError(case)


@pytest.mark.parametrize("case", ["intent", "lease", "queue", "plan", "entity", "nsai", "sandbox", "boundary", "freeze", "tool", "tool-state"])
def test_writer_never_opens_attacker_planted_staging(case, tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    target, staging, publish = _writer(case, root, monkeypatch)
    staging.parent.mkdir(parents=True, exist_ok=True)
    external = tmp_path / "external.txt"
    external.write_bytes(b"external must remain unchanged")
    os.link(external, staging)
    publish()
    assert external.read_bytes() == b"external must remain unchanged"
    assert staging.read_bytes() == external.read_bytes()
    assert target.is_file()


@pytest.mark.parametrize("case", ["intent", "lease", "queue", "plan", "entity", "nsai", "sandbox", "boundary", "freeze", "tool", "tool-state"])
def test_writer_failed_replace_preserves_previous_target(case, tmp_path, monkeypatch):
    from runtime import secure_publish
    root = tmp_path / "project"
    root.mkdir()
    target, _, publish = _writer(case, root, monkeypatch)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_bytes(b'{"previous":"image"}' if case == "tool" else b"previous image")
    previous = target.read_bytes()
    def fail(*a, **k):
        raise PermissionError("injected owner publication failure")
    monkeypatch.setattr(secure_publish.os, "replace", fail)
    with pytest.raises(PermissionError) as failure:
        publish()
    assert target.read_bytes() == previous
    retained = list(root.rglob("*.prepared"))
    if case in {"tool", "tool-state"}:
        # The transactional intake owner retains failed WAL allocation evidence;
        # staging for this attempt must not exist outside its journal and the
        # outcome must be explicit.
        journal = root / ".agentic_engineering_os_px/project-management/tool-intake-wal"
        assert all(path.is_relative_to(journal) for path in retained)
        staged = [path for path in root.rglob("*.json.next") if not path.is_relative_to(journal)]
        assert staged == []
        outcome = failure.value.wal_outcome
        assert outcome["acknowledgement"] == "failed"
        assert outcome["publication"] == "not_started"
    else:
        assert not retained


def test_failed_replace_preserves_prior_image_and_cleans_owned_staging(tmp_path, monkeypatch):
    from runtime import secure_publish
    target = tmp_path / "state.json"
    target.write_bytes(b"old")
    def refuse(*args, **kwargs):
        raise PermissionError("injected replace failure")
    with monkeypatch.context() as patch:
        patch.setattr(secure_publish.os, "replace", refuse)
        with pytest.raises(PermissionError):
            atomic_write_bytes(target, b"new")
    assert target.read_bytes() == b"old"
    assert list(tmp_path.iterdir()) == [target]
    atomic_write_bytes(target, b"new")
    assert target.read_bytes() == b"new"


def test_interrupted_stream_never_publishes_partial_image(tmp_path):
    from runtime.secure_publish import atomic_write_stream
    target = tmp_path / "archive.zip"
    target.write_bytes(b"previous archive")
    def interrupted(stream):
        stream.write(b"partial archive")
        raise RuntimeError("injected producer interruption")
    with pytest.raises(RuntimeError):
        atomic_write_stream(target, interrupted)
    assert target.read_bytes() == b"previous archive"
    assert list(tmp_path.iterdir()) == [target]


def test_atomic_publication_concurrent_whole_images(tmp_path):
    target = tmp_path / "state.json"
    images = [bytes([i]) * 8192 for i in range(12)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda image: atomic_write_bytes(target, image), images))
    assert target.read_bytes() in images
    assert list(tmp_path.iterdir()) == [target]


def test_reject_destination_hardlink_without_modifying_external(tmp_path):
    external = tmp_path / "external"
    external.write_bytes(b"old")
    target = tmp_path / "state"
    os.link(external, target)
    with pytest.raises(ValueError):
        atomic_write_bytes(target, b"new")
    assert external.read_bytes() == b"old"


@pytest.mark.parametrize("name", ["../escape", "bad.json:stream", "NUL", "name."])
def test_reject_unsupported_path(tmp_path, name):
    with pytest.raises(ValueError):
        atomic_write_bytes(tmp_path / name, b"data")


def test_windows_ancestor_cannot_be_renamed_during_publication(tmp_path):
    if os.name != "nt":
        pytest.skip("Windows pinned-handle host proof")
    from runtime.secure_publish import _windows_parent
    directory = tmp_path / "parent"
    target = directory / "state"
    with _windows_parent(target):
        with pytest.raises(OSError):
            directory.rename(tmp_path / "moved")
    directory.rename(tmp_path / "moved")


def test_reject_linked_ancestor_before_writing(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            raise
        import subprocess
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], check=True, capture_output=True)
    try:
        with pytest.raises((ValueError, OSError)):
            atomic_write_bytes(link / "state", b"new")
        assert list(outside.iterdir()) == []
    finally:
        if link.is_symlink():
            link.unlink()
        else:
            link.rmdir()


def test_pre_replace_writer_failure_names_the_image_that_survived(tmp_path, monkeypatch):
    """A writer failure before os.replace must not erase its own evidence.

    The prepared image is the only copy of what the writer produced. When the
    reclaim succeeds, the error still names that image and reports the reclaim as
    observed; when the reclaim is refused, the image is still on disk and the error
    says so rather than silently looking clean.
    """
    from runtime import secure_publish

    target = tmp_path / "pre-replace-failure.json"
    target.write_bytes(b"previous")

    def writer(stream):
        stream.write(b"partial image")
        raise ValueError("writer failed before replace")

    with pytest.raises(ValueError) as caught:
        secure_publish.atomic_write_stream(target, writer)

    record = caught.value.publication_cleanup
    assert record["reason"] == "failed_pre_replace_image"
    assert record["retained_image"].endswith(".prepared")
    # The destination is untouched and the failure is attributed to the writer,
    # not to a cleanup attempt.
    assert target.read_bytes() == b"previous"
    assert str(caught.value) == "writer failed before replace"

    # Now force the reclaim to be refused: custody must report a retained image.
    target.write_bytes(b"previous")
    def refuse(*args, **kwargs):
        raise PermissionError("injected refusal")
    monkeypatch.setattr(secure_publish.os, "unlink", refuse)
    with pytest.raises(ValueError) as refused:
        secure_publish.atomic_write_stream(target, writer)
    refused_record = refused.value.publication_cleanup
    assert refused_record["cleanup_verified"] is False
    assert refused_record["retained"] is True
