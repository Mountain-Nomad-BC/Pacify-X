from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest

from runtime.wal_transaction import (
    _REPLACE_RETRY_DELAYS_SECONDS,
    BytesArtifact,
    JsonArtifact,
    JsonTextArtifact,
    JsonWal,
    TextArtifact,
    WalIntegrityError,
    planned_write_boundaries,
)


ROLES = ("state", "event", "receipt", "handoff", "projection")


def _symlink_or_skip(target: Path, link: Path, *, directory: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=directory)
    except (NotImplementedError, OSError) as error:
        pytest.skip(f"symlink creation is unavailable: {error}")


def _artifacts(root: Path, generation: str) -> tuple[JsonArtifact, ...]:
    return tuple(
        JsonArtifact(role, root / "artifacts" / f"{role}.json", {"value": generation})
        for role in ROLES
    )


def _seed(root: Path) -> None:
    for artifact in _artifacts(root, "after"):
        artifact.path.parent.mkdir(parents=True, exist_ok=True)
        artifact.path.write_text('{"value":"before"}\n', encoding="utf-8")


def _values(root: Path) -> set[str]:
    return {
        json.loads(artifact.path.read_text(encoding="utf-8"))["value"]
        for artifact in _artifacts(root, "unused")
    }


def _tree_fingerprint(root: Path) -> str:
    records: list[tuple[object, ...]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(root).as_posix()
        stat = path.lstat()
        if path.is_dir():
            records.append((relative, "directory", stat.st_mtime_ns))
        else:
            payload = path.read_bytes()
            records.append(
                (
                    relative,
                    "file",
                    len(payload),
                    stat.st_mtime_ns,
                    hashlib.sha256(payload).hexdigest(),
                )
            )
    return hashlib.sha256(repr(records).encode("utf-8")).hexdigest()


def test_commit_coordinates_every_semantic_json_artifact(tmp_path: Path) -> None:
    _seed(tmp_path)
    result = JsonWal(tmp_path / "wal", tmp_path).commit(
        _artifacts(tmp_path, "after"), transaction_id="complete"
    )

    assert result["state"] == "committed"
    assert result["artifact_count"] == 5
    assert _values(tmp_path) == {"after"}
    manifest = json.loads(
        (tmp_path / "wal" / "committed" / "complete" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["phase"] == "committed"
    assert [item["role"] for item in manifest["artifacts"]] == list(ROLES)


def test_commit_coordinates_json_text_and_exact_bytes(tmp_path: Path) -> None:
    json_path = tmp_path / "projection.json"
    text_path = tmp_path / "README.md"
    bytes_path = tmp_path / "SHA256SUMS"
    json_path.write_text('{"before":true}\n', encoding="utf-8")
    text_path.write_text("before\n", encoding="utf-8")
    bytes_path.write_bytes(b"before-bytes\n")

    result = JsonWal(tmp_path / "wal", tmp_path).commit(
        (
            JsonArtifact("projection", json_path, {"after": True}),
            TextArtifact("projection", text_path, "after\n"),
            BytesArtifact("projection", bytes_path, b"after-bytes\n"),
        ),
        transaction_id="mixed-artifacts",
    )

    assert result["artifact_count"] == 3
    assert json.loads(json_path.read_text(encoding="utf-8")) == {"after": True}
    assert text_path.read_text(encoding="utf-8") == "after\n"
    assert bytes_path.read_bytes() == b"after-bytes\n"
    staged = tmp_path / "wal" / "committed" / "mixed-artifacts" / "after"
    assert {path.suffix for path in staged.iterdir()} == {".json", ".txt", ".bin"}


def test_text_artifact_rejects_non_utf8_existing_target(tmp_path: Path) -> None:
    target = tmp_path / "README.md"
    target.write_bytes(b"\xff")

    with pytest.raises(WalIntegrityError, match="not UTF-8"):
        JsonWal(tmp_path / "wal", tmp_path).commit(
            (TextArtifact("projection", target, "valid\n"),),
            transaction_id="invalid-existing-text",
        )


def test_json_text_artifact_preserves_exact_valid_serialization(tmp_path: Path) -> None:
    target = tmp_path / "projection.json"
    target.write_text('{"before":true}\n', encoding="utf-8")
    rendered = '{\n  "after": true\n}\n'

    JsonWal(tmp_path / "wal", tmp_path).commit(
        (JsonTextArtifact("projection", target, rendered),),
        transaction_id="exact-json-text",
    )

    assert target.read_text(encoding="utf-8") == rendered


@pytest.mark.parametrize("invalid", ("{", '{"value":NaN}', '{"value":Infinity}'))
def test_json_text_artifact_rejects_invalid_desired_json(
    tmp_path: Path, invalid: str
) -> None:
    with pytest.raises(ValueError, match="not strict JSON"):
        JsonWal(tmp_path / "wal", tmp_path).commit(
            (JsonTextArtifact("projection", tmp_path / "bad.json", invalid),),
            transaction_id="invalid-json-text",
        )


def test_commit_rejects_nominal_symlink_target(tmp_path: Path) -> None:
    actual = tmp_path / "actual.json"
    actual.write_text("{}\n", encoding="utf-8")
    link = tmp_path / "linked.json"
    _symlink_or_skip(actual, link)

    with pytest.raises(WalIntegrityError, match="symlink/reparse"):
        JsonWal(tmp_path / "wal", tmp_path).commit(
            (JsonArtifact("projection", link, {"changed": True}),),
            transaction_id="symlink-target",
        )


def test_commit_rejects_nominal_symlink_parent(tmp_path: Path) -> None:
    actual = tmp_path / "actual"
    actual.mkdir()
    linked = tmp_path / "linked"
    _symlink_or_skip(actual, linked, directory=True)

    with pytest.raises(WalIntegrityError, match="symlink/reparse"):
        JsonWal(tmp_path / "wal", tmp_path).commit(
            (JsonArtifact("projection", linked / "value.json", {"changed": True}),),
            transaction_id="symlink-parent",
        )


def test_constructor_rejects_nominal_symlink_wal_root(tmp_path: Path) -> None:
    actual = tmp_path / "actual-wal"
    actual.mkdir()
    linked = tmp_path / "linked-wal"
    _symlink_or_skip(actual, linked, directory=True)

    with pytest.raises(WalIntegrityError, match="symlink/reparse"):
        JsonWal(linked, tmp_path)


def test_recovery_rejects_staged_before_image_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    target.write_text('{"value":"before"}\n', encoding="utf-8")
    wal = JsonWal(tmp_path / "wal", tmp_path)

    def interrupt_after_applying(boundary: str) -> None:
        if boundary == "manifest:applying:published":
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        wal.commit(
            (JsonArtifact("projection", target, {"value": "after"}),),
            transaction_id="recovery-before-link",
            fault_injector=interrupt_after_applying,
        )
    staged = (
        tmp_path
        / "wal/transactions/recovery-before-link/before/0000.json"
    )
    retained = tmp_path / "retained-before.json"
    retained.write_bytes(staged.read_bytes())
    staged.unlink()
    _symlink_or_skip(retained, staged)

    with pytest.raises(WalIntegrityError, match="symlink/reparse"):
        wal.recover()


def test_recovery_rejects_target_replaced_by_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    target.write_text('{"value":"before"}\n', encoding="utf-8")
    wal = JsonWal(tmp_path / "wal", tmp_path)

    def interrupt_after_applying(boundary: str) -> None:
        if boundary == "manifest:applying:published":
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        wal.commit(
            (JsonArtifact("projection", target, {"value": "after"}),),
            transaction_id="recovery-symlink",
            fault_injector=interrupt_after_applying,
        )
    replacement = tmp_path / "replacement.json"
    replacement.write_text('{"value":"external"}\n', encoding="utf-8")
    target.unlink()
    _symlink_or_skip(replacement, target)

    with pytest.raises(WalIntegrityError, match="symlink/reparse"):
        wal.recover()


def test_commit_retries_transient_permission_denial_during_file_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(tmp_path)
    original_replace = os.replace
    denied = 0

    def transient_replace(source: object, destination: object) -> None:
        nonlocal denied
        target = Path(destination)
        if target.name == "manifest.json" and denied < 2:
            denied += 1
            raise PermissionError("simulated transient manifest handle")
        original_replace(source, destination)

    monkeypatch.setattr("runtime.wal_transaction.os.replace", transient_replace)
    result = JsonWal(tmp_path / "wal", tmp_path).commit(
        _artifacts(tmp_path, "after"), transaction_id="transient-manifest"
    )

    assert result["state"] == "committed"
    assert denied == 2
    assert _values(tmp_path) == {"after"}


def test_commit_retries_transient_permission_denial_during_committed_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(tmp_path)
    original_replace = os.replace
    denied = 0

    def transient_replace(source: object, destination: object) -> None:
        nonlocal denied
        source_path = Path(source)
        target = Path(destination)
        if (
            source_path.parent.name == "transactions"
            and target.parent.name == "committed"
            and denied < 2
        ):
            denied += 1
            raise PermissionError("simulated transient directory handle")
        original_replace(source, destination)

    monkeypatch.setattr("runtime.wal_transaction.os.replace", transient_replace)
    result = JsonWal(tmp_path / "wal", tmp_path).commit(
        _artifacts(tmp_path, "after"), transaction_id="transient-archive"
    )

    assert result["state"] == "committed"
    assert denied == 2
    assert (tmp_path / "wal" / "committed" / "transient-archive").is_dir()


def test_recovery_retries_transient_permission_denial_during_rollback_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    transaction = tmp_path / "wal" / "transactions" / "unprepared"
    transaction.mkdir(parents=True)
    original_replace = os.replace
    denied = 0

    def transient_replace(source: object, destination: object) -> None:
        nonlocal denied
        target = Path(destination)
        if target.parent.name == "rolled-back" and denied < 2:
            denied += 1
            raise PermissionError("simulated transient rollback handle")
        original_replace(source, destination)

    monkeypatch.setattr("runtime.wal_transaction.os.replace", transient_replace)
    result = JsonWal(tmp_path / "wal", tmp_path).recover()

    assert result["rolled_back"] == ["unprepared"]
    assert denied == 2
    assert (tmp_path / "wal" / "rolled-back" / "unprepared").is_dir()


def test_persistent_permission_denial_is_bounded_and_recoverable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(tmp_path)
    original_replace = os.replace
    denied = 0

    def denied_archive(source: object, destination: object) -> None:
        nonlocal denied
        source_path = Path(source)
        target = Path(destination)
        if (
            source_path.parent.name == "transactions"
            and target.parent.name == "committed"
        ):
            denied += 1
            raise PermissionError("simulated persistent directory handle")
        original_replace(source, destination)

    monkeypatch.setattr("runtime.wal_transaction.os.replace", denied_archive)
    wal = JsonWal(tmp_path / "wal", tmp_path)
    with pytest.raises(PermissionError, match="persistent directory handle"):
        wal.commit(_artifacts(tmp_path, "after"), transaction_id="persistent-denial")

    assert denied == len(_REPLACE_RETRY_DELAYS_SECONDS)
    assert (tmp_path / "wal" / "transactions" / "persistent-denial").is_dir()
    assert not (tmp_path / "wal" / "committed" / "persistent-denial").exists()
    assert _values(tmp_path) == {"after"}

    monkeypatch.setattr("runtime.wal_transaction.os.replace", original_replace)
    assert wal.recover()["completed"] == ["persistent-denial"]


def test_non_permission_replace_error_fails_immediately(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(tmp_path)
    original_replace = os.replace
    attempts = 0

    def invalid_replace(source: object, destination: object) -> None:
        nonlocal attempts
        target = Path(destination)
        if target.name == "manifest.json":
            attempts += 1
            raise OSError("simulated non-transient replace failure")
        original_replace(source, destination)

    monkeypatch.setattr("runtime.wal_transaction.os.replace", invalid_replace)
    with pytest.raises(OSError, match="non-transient replace failure"):
        JsonWal(tmp_path / "wal", tmp_path).commit(
            _artifacts(tmp_path, "after"), transaction_id="non-permission"
        )

    assert attempts == 1


def test_real_process_kill_at_every_write_boundary_recovers_atomically(
    tmp_path: Path,
) -> None:
    planning = tmp_path / "boundary-plan"
    _seed(planning)
    boundaries = planned_write_boundaries(_artifacts(planning, "after"))
    assert len(boundaries) == 27
    child = textwrap.dedent(
        """
        import os
        from pathlib import Path
        import sys
        from runtime.wal_transaction import JsonArtifact, JsonWal

        root = Path(sys.argv[1])
        boundary = sys.argv[2]
        roles = ("state", "event", "receipt", "handoff", "projection")
        artifacts = tuple(
            JsonArtifact(role, root / "artifacts" / f"{role}.json", {"value": "after"})
            for role in roles
        )
        def kill(name):
            if name == boundary:
                os._exit(91)
        JsonWal(root / "wal", root).commit(
            artifacts, transaction_id="killed", fault_injector=kill
        )
        """
    )
    for index, boundary in enumerate(boundaries):
        case = tmp_path / f"case-{index:02d}"
        _seed(case)
        completed = subprocess.run(
            [sys.executable, "-c", child, str(case), boundary],
            cwd=Path(__file__).parents[1],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert completed.returncode == 91, (boundary, completed.stderr)

        recovery = JsonWal(case / "wal", case).recover()
        if boundary == "journal:committed:published":
            assert recovery["completed"] == [], boundary
            assert _values(case) == {"after"}, boundary
        elif boundary.startswith("journal:") or boundary == "manifest:prepared:staged":
            assert recovery["rolled_back"] == ["killed"], boundary
            assert _values(case) == {"before"}, boundary
        else:
            assert recovery["completed"] == ["killed"], boundary
            assert _values(case) == {"after"}, boundary
        assert not tuple((case / "artifacts").glob("*.prepared")), boundary


def test_recovery_is_idempotent_and_never_rewrites_an_external_change(
    tmp_path: Path,
) -> None:
    _seed(tmp_path)

    def crash_after_first_target(boundary: str) -> None:
        if boundary == "target:0:published":
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        JsonWal(tmp_path / "wal", tmp_path).commit(
            _artifacts(tmp_path, "after"),
            transaction_id="interrupted",
            fault_injector=crash_after_first_target,
        )
    changed = tmp_path / "artifacts" / "receipt.json"
    changed.write_text('{"value":"external"}\n', encoding="utf-8")

    with pytest.raises(WalIntegrityError, match="changed outside transaction"):
        JsonWal(tmp_path / "wal", tmp_path).recover()
    assert json.loads(changed.read_text(encoding="utf-8")) == {"value": "external"}


def test_roll_forward_recovery_is_idempotent(tmp_path: Path) -> None:
    _seed(tmp_path)

    def crash(boundary: str) -> None:
        if boundary == "target:1:published":
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        JsonWal(tmp_path / "wal", tmp_path).commit(
            _artifacts(tmp_path, "after"),
            transaction_id="recover-twice",
            fault_injector=crash,
        )
    first = JsonWal(tmp_path / "wal", tmp_path).recover()
    second = JsonWal(tmp_path / "wal", tmp_path).recover()

    assert first["completed"] == ["recover-twice"]
    assert second["completed"] == []
    assert _values(tmp_path) == {"after"}


def test_inspect_reports_pending_recovery_without_any_filesystem_change(
    tmp_path: Path,
) -> None:
    _seed(tmp_path)

    def interrupt(boundary: str) -> None:
        if boundary == "target:0:published":
            raise RuntimeError("interrupted")

    wal = JsonWal(tmp_path / "wal", tmp_path)
    with pytest.raises(RuntimeError, match="interrupted"):
        wal.commit(
            _artifacts(tmp_path, "after"),
            transaction_id="inspect-only",
            fault_injector=interrupt,
        )
    before = _tree_fingerprint(tmp_path)
    report = wal.inspect()
    after = _tree_fingerprint(tmp_path)

    assert report["mode"] == "inspect"
    assert report["requires_recovery"] is True
    assert report["would_complete"] == ["inspect-only"]
    assert report["would_roll_back"] == []
    assert report["transactions"][0]["targets_after"] == 1
    assert before == after
    assert _values(tmp_path) == {"before", "after"}


def test_inspect_of_absent_wal_does_not_create_it(tmp_path: Path) -> None:
    wal_root = tmp_path / "absent-wal"
    report = JsonWal(wal_root, tmp_path).inspect()
    assert report["requires_recovery"] is False
    assert report["inspection_sha256"] == "absent"
    assert not wal_root.exists()


def test_committed_manifest_target_drift_blocks_recovery(tmp_path: Path) -> None:
    _seed(tmp_path)

    def interrupt(boundary: str) -> None:
        if boundary == "manifest:committed:published":
            raise RuntimeError("interrupted after committed manifest")

    wal = JsonWal(tmp_path / "wal", tmp_path)
    with pytest.raises(RuntimeError, match="committed manifest"):
        wal.commit(
            _artifacts(tmp_path, "after"),
            transaction_id="committed-drift",
            fault_injector=interrupt,
        )
    changed = tmp_path / "artifacts" / "receipt.json"
    changed.write_text('{"value":"external"}\n', encoding="utf-8")

    with pytest.raises(WalIntegrityError, match="committed target drift"):
        wal.inspect()
    with pytest.raises(WalIntegrityError, match="committed target drift"):
        wal.recover()
    assert (tmp_path / "wal" / "transactions" / "committed-drift").is_dir()
    assert json.loads(changed.read_text(encoding="utf-8")) == {"value": "external"}


def test_later_transaction_can_supersede_prior_committed_values(tmp_path: Path) -> None:
    _seed(tmp_path)
    wal = JsonWal(tmp_path / "wal", tmp_path)
    wal.commit(_artifacts(tmp_path, "one"), transaction_id="generation-one")
    wal.commit(_artifacts(tmp_path, "two"), transaction_id="generation-two")

    assert _values(tmp_path) == {"two"}
    assert wal.recover()["completed"] == []
    assert _values(tmp_path) == {"two"}


def test_corrupt_manifest_fails_closed_without_touching_targets(tmp_path: Path) -> None:
    _seed(tmp_path)
    transaction = tmp_path / "wal" / "transactions" / "corrupt"
    transaction.mkdir(parents=True)
    (transaction / "manifest.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(WalIntegrityError, match="manifest digest mismatch"):
        JsonWal(tmp_path / "wal", tmp_path).recover()
    assert _values(tmp_path) == {"before"}


def test_paths_roles_duplicates_and_non_json_are_rejected(tmp_path: Path) -> None:
    wal = JsonWal(tmp_path / "wal", tmp_path)
    with pytest.raises(ValueError, match="unsupported JSON artifact role"):
        wal.commit([JsonArtifact("secret", tmp_path / "x.json", {})])
    with pytest.raises(ValueError, match="duplicate transaction target"):
        wal.commit(
            [
                JsonArtifact("state", tmp_path / "x.json", {}),
                JsonArtifact("event", tmp_path / "x.json", {}),
            ]
        )
    with pytest.raises(ValueError, match="escapes allowed root"):
        wal.commit([JsonArtifact("state", tmp_path.parent / "escape.json", {})])
    with pytest.raises(ValueError, match="strict JSON"):
        wal.commit([JsonArtifact("state", tmp_path / "x.json", {"nan": float("nan")})])
