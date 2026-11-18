from __future__ import annotations

import ast
import json
from pathlib import Path
import shutil
import tempfile

from runtime.effect_surface import (
    _pure_string_replace_resolver,
    discover_effect_surfaces,
    validate_effect_surfaces,
)


ROOT = Path(__file__).parents[1]

def test_link_publication_is_discovered_as_filesystem_mutation(tmp_path: Path) -> None:
    (tmp_path / "publisher.py").write_text(
        "import os\nfrom pathlib import Path\n"
        "os.link('prepared', 'receipt')\nos.symlink('source', 'alias')\n"
        "Path('receipt').hardlink_to('prepared')\nPath('alias').symlink_to('source')\n",
        encoding="utf-8",
    )
    records = discover_effect_surfaces(tmp_path)
    assert {record["call"] for record in records} == {
        "os.link", "os.symlink", "hardlink_to", "symlink_to"
    }
    assert all(record["effect"] == "filesystem_mutation" for record in records)
    assert all(not record["destructive"] for record in records)

def _copy_effect_fixture(destination: Path) -> Path:
    root = destination / "framework"
    root.mkdir()
    (root / "runtime").mkdir()
    (root / "runtime/base_effect.py").write_text(
        "from pathlib import Path\n\n"
        "def write_bounded():\n"
        "    Path('bounded.txt').write_text('bounded', encoding='utf-8')\n",
        encoding="utf-8",
    )
    (root / "registry").mkdir()
    shutil.copytree(ROOT / "policies", root / "policies")
    records = discover_effect_surfaces(root)
    (root / "registry/effect_surface_ownership.json").write_text(
        json.dumps(
            {"schema_version": "1.0", "record_count": len(records), "records": records},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return root


def test_every_executable_effect_surface_is_owned_and_bounded() -> None:
    result = validate_effect_surfaces(ROOT)
    assert result["valid"], result["errors"]
    assert result["counts"]["process"] >= 6
    assert result["counts"]["filesystem_mutation"] > 0


def test_release_effects_have_explicit_bounded_or_recovery_ownership() -> None:
    records = discover_effect_surfaces(ROOT)
    affected = {
        record["path"]: []
        for record in records
        if record["path"]
        in {
            "runtime/evidence_custody.py",
            "scripts/run_installed_operational_owner.py",
            "scripts/run_release_stage_owner.py",
            "scripts/verify_release_publication.py",
        }
    }
    for record in records:
        if record["path"] in affected:
            affected[record["path"]].append(record)

    assert set(affected) == {
        "runtime/evidence_custody.py",
        "scripts/run_installed_operational_owner.py",
        "scripts/run_release_stage_owner.py",
        "scripts/verify_release_publication.py",
    }
    for records_for_owner in affected.values():
        for record in records_for_owner:
            if record["destructive"]:
                assert record["policy"] == "policies/operational-evidence-retention.json"
            if record["effect"] == "process":
                assert record["timeout"] is not None


def test_explicit_specialized_effect_owners_retain_their_real_bounds() -> None:
    records = discover_effect_surfaces(ROOT)
    obsidian_processes = [
        record
        for record in records
        if record["path"] == "docs/architecture/tools/verify_obsidian_native.py"
        and record["effect"] == "process"
    ]
    gate_deletions = [
        record
        for record in records
        if record["path"] == "runtime/gate_runner.py" and record["destructive"]
    ]

    assert len(obsidian_processes) == 3
    assert all(record["timeout"] is not None for record in obsidian_processes)
    popen_records = [
        record for record in obsidian_processes if record["call"] == "subprocess.Popen"
    ]
    assert len(popen_records) == 1
    assert (
        popen_records[0]["timeout"]
        == "bounded_finally_termination_and_wait_with_platform_tree_kill"
    )
    assert all(
        record["policy"] == "policies/contained-execution.json"
        for record in obsidian_processes
    )
    assert len(gate_deletions) == 1
    assert gate_deletions[0]["call"] == "temporary.unlink"
    assert (
        gate_deletions[0]["policy"]
        == "policies/operational-evidence-retention.json"
    )


def test_discovery_prunes_external_custody_before_parsing() -> None:
    root = _copy_effect_fixture(Path(tempfile.mkdtemp()))
    hostile = (
        root
        / ".agentic_engineering_os_px/test-evidence/adversarial-repair-gates"
        / "unparseable.py"
    )
    hostile.parent.mkdir(parents=True)
    hostile.write_text("this is not valid Python =", encoding="utf-8")
    generated = root / "extension/dist/generated.py"
    generated.parent.mkdir(parents=True)
    generated.write_text("this is also not valid Python =", encoding="utf-8")
    build_output = root / "extension/build/generated.py"
    build_output.parent.mkdir(parents=True)
    build_output.write_text("this is still not valid Python =", encoding="utf-8")
    retained_evidence = root / "extension/evidence/generated.py"
    retained_evidence.parent.mkdir(parents=True)
    retained_evidence.write_text("this remains not valid Python =", encoding="utf-8")

    records = discover_effect_surfaces(root)

    assert records
    assert all("adversarial-repair-gates" not in record["path"] for record in records)
    assert all("extension/dist" not in record["path"] for record in records)
    assert all("extension/build" not in record["path"] for record in records)
    assert all("extension/evidence" not in record["path"] for record in records)


def test_new_shell_execution_fails_closed() -> None:
    root = _copy_effect_fixture(Path(tempfile.mkdtemp()))
    target = root / "runtime/unsafe_effect.py"
    target.write_text(
        "import subprocess\nsubprocess.run('echo unsafe', shell=True, timeout=1)\n",
        encoding="utf-8",
    )
    result = validate_effect_surfaces(root)
    assert not result["valid"]
    assert any("unsafe shell" in item for item in result["errors"])


def test_registry_cannot_claim_removed_effect_surface() -> None:
    root = _copy_effect_fixture(Path(tempfile.mkdtemp()))
    path = root / "registry/effect_surface_ownership.json"
    registry = json.loads(path.read_text(encoding="utf-8"))
    registry["records"] = registry["records"][1:]
    path.write_text(json.dumps(registry), encoding="utf-8")
    assert not validate_effect_surfaces(root)["valid"]


def test_unadmitted_hard_delete_surface_fails_closed() -> None:
    root = _copy_effect_fixture(Path(tempfile.mkdtemp()))
    target = root / "runtime/unsafe_delete.py"
    target.write_text(
        "from pathlib import Path\nPath('unowned').unlink()\n", encoding="utf-8"
    )
    result = validate_effect_surfaces(root)
    assert not result["valid"]
    assert any("hard-delete surface is prohibited" in item for item in result["errors"])


def test_popen_without_bounded_communication_fails_closed() -> None:
    root = _copy_effect_fixture(Path(tempfile.mkdtemp()))
    target = root / "runtime/unbounded_process.py"
    target.write_text(
        "import subprocess\nprocess = subprocess.Popen(['tool'])\nprocess.communicate()\n",
        encoding="utf-8",
    )
    result = validate_effect_surfaces(root)
    assert not result["valid"]
    assert any("process call lacks timeout" in item for item in result["errors"])


def test_effect_identity_is_a_source_locator_not_an_ast_dump() -> None:
    semantic = "runtime/example.py:3:4:subprocess.run"
    assert __import__("hashlib").sha256(semantic.encode()).hexdigest()[:20] == "c40e855839d0987c2742"
def test_secure_publish_owned_prepared_cleanup_is_recoverable_reclamation() -> None:
    """The atomic publisher may only remove the unpublished image it created.

    `atomic_write_bytes`/`atomic_write_stream` stage one random
    `.<name>.<uuid>.prepared` file and publish it by `os.replace`.  The `finally`
    unlink reclaims only that staging image after a failed replace.  It is a
    destructive surface, but a recoverable-reclamation one: the destination image
    is preserved and only the caller's own unpublished staging path is removed.
    """
    import runtime.effect_surface as owner

    assert (
        owner.RECOVERABLE_RECLAMATION_OWNERS["runtime/secure_publish.py"]
        == "policies/artifact-preservation.json"
    )
    deletions = [
        record
        for record in discover_effect_surfaces(ROOT)
        if record["path"] == "runtime/secure_publish.py" and record["destructive"]
    ]
    assert len(deletions) == 1
    assert deletions[0]["call"] == "os.unlink"
    assert deletions[0]["policy"] == "policies/artifact-preservation.json"
def _replace_sites(source: str) -> list:
    """Inventory a synthetic module and return its discovered call sites."""
    root = Path(tempfile.mkdtemp()) / "framework"
    (root / "runtime").mkdir(parents=True)
    (root / "registry").mkdir()
    (root / "runtime/sample.py").write_text(source, encoding="utf-8")
    return [r for r in discover_effect_surfaces(root) if r["path"] == "runtime/sample.py"]


def test_str_receiver_proofs_are_sound_and_narrow() -> None:
    """Only provable string receivers leave the census; anything unknown stays in."""
    proven = _replace_sites(
        "def literal_name(value, text):\n"
        "    cleaned = 'probe'\n"
        "    one = str(value).replace('a', 'b')\n"
        "    two = cleaned.replace('a', 'b')\n"
        "    three = str(value).strip().replace('a', 'b')\n"
        "    return one, two, three\n"
    )
    assert proven == []

    # An unknown receiver, a datetime receiver, and an unknown decoder stay in.
    unproven = _replace_sites(
        "from datetime import datetime\n"
        "def unknown(value):\n"
        "    return value.replace('a', 'b')\n"
        "def stamped(value: datetime):\n"
        "    return value.replace(tzinfo=None)\n"
    )
    assert len(unproven) == 2
    assert {site["effect"] for site in unproven} == {"filesystem_mutation"}


def test_loop_bound_str_proof_requires_a_provable_generator() -> None:
    """A generator whose every yield is a str parameter proves the loop name str.

    A generator yielding an unknown call's result must not, and neither must a name
    that is rebound inside the loop.
    """
    proven = _replace_sites(
        "def chunks(text: str):\n"
        "    for index in range(0, len(text), 8):\n"
        "        yield text[index:index + 8]\n"
        "def normalise(text: str):\n"
        "    for piece in chunks(text):\n"
        "        yield piece.replace('\\r\\n', '\\n')\n"
    )
    assert proven == []

    unknown_decoder = _replace_sites(
        "def pieces(blob):\n"
        "    for item in blob:\n"
        "        yield decoder.decode(item)\n"
        "def normalise(blob):\n"
        "    for piece in pieces(blob):\n"
        "        yield piece.replace('a', 'b')\n"
    )
    assert len(unknown_decoder) == 1

    rebound = _replace_sites(
        "def chunks(text: str):\n"
        "    yield text[:1]\n"
        "def normalise(text: str):\n"
        "    for piece in chunks(text):\n"
        "        piece = transform(piece)\n"
        "        yield piece.replace('a', 'b')\n"
    )
    assert len(rebound) == 1


def test_chained_calls_on_one_line_receive_distinct_identities() -> None:
    """`a.replace(x).replace(y)` shares line and column; the ids must still differ.

    Identity is a source locator, and two distinct calls on the same line previously
    produced one id, so two ownership records collided in the registry.
    """
    root = _copy_effect_fixture(Path(tempfile.mkdtemp()))
    (root / "runtime/chained.py").write_text(
        "def normalise(value: str):\n"
        "    return value.replace('a', 'b').replace('c', 'd')\n",
        encoding="utf-8",
    )
    records = [r for r in discover_effect_surfaces(root) if r["path"] == "runtime/chained.py"]
    ids = [r["id"] for r in records]
    assert len(ids) == len(set(ids)), f"colliding identities: {ids}"
    # The locator itself is unchanged for the first occurrence.
    assert all(r["line"] == 2 for r in records)


def test_effect_identity_is_deterministic_across_runs() -> None:
    first = [r["id"] for r in discover_effect_surfaces(ROOT)]
    second = [r["id"] for r in discover_effect_surfaces(ROOT)]
    assert first == second
    assert len(first) == len(set(first)), "duplicate record ids in current discovery"


def test_duplicate_published_ids_are_reported() -> None:
    """The validator must see collisions in the published image, not only in discovery."""
    root = _copy_effect_fixture(Path(tempfile.mkdtemp()))
    path = root / "registry/effect_surface_ownership.json"
    registry = json.loads(path.read_text(encoding="utf-8"))
    if len(registry["records"]) < 2:
        registry["records"] = registry["records"] * 2
        registry["record_count"] = len(registry["records"])
    else:
        registry["records"][1]["id"] = registry["records"][0]["id"]
    path.write_text(json.dumps(registry), encoding="utf-8")
    result = validate_effect_surfaces(root)
    assert not result["valid"]
    assert any("duplicate ids" in item for item in result["errors"])


# --- bound-open receiver provenance ---------------------------------------------------
# `ledger = root / LEDGER` then `ledger.open("r")` was reported as an unresolved receiver,
# so a pure read made its producer look like a mutator. These pin both directions: a proven
# path local reads cleanly, and an ambiguous receiver still fails closed as a mutation.


def _socket(root: Path, name: str, source: str) -> Path:
    target = root / name
    target.write_text(source, encoding="utf-8")
    return target


def _effects_for(root: Path, name: str) -> list[dict]:
    return [record for record in discover_effect_surfaces(root)
            if record["path"] == name]


def test_read_open_on_a_path_bound_local_is_not_a_mutation(tmp_path: Path) -> None:
    _socket(tmp_path, "reader.py", (
        "from pathlib import Path\n"
        "LEDGER = 'ledger.jsonl'\n"
        "def read(root: Path) -> str:\n"
        "    ledger = root / LEDGER\n"
        "    with ledger.open('r', encoding='utf-8') as handle:\n"
        "        return handle.read()\n"
    ))
    assert _effects_for(tmp_path, "reader.py") == []


def test_write_open_on_a_path_bound_local_is_still_a_mutation(tmp_path: Path) -> None:
    """The provenance rule must never turn a write into a read."""
    _socket(tmp_path, "writer.py", (
        "from pathlib import Path\n"
        "def write(root: Path) -> None:\n"
        "    target = root / 'out.json'\n"
        "    target.open('w', encoding='utf-8').write('x')\n"
    ))
    records = _effects_for(tmp_path, "writer.py")
    assert records, "a proven path write was dropped from the census"
    assert all(record["effect"] == "filesystem_mutation" for record in records)


def test_read_open_on_an_ambiguous_receiver_stays_unresolved(tmp_path: Path) -> None:
    """A parameter of unknown type is not a proven path, so the read is not silently dropped."""
    _socket(tmp_path, "ambiguous.py", (
        "def read(config) -> str:\n"
        "    return config.open('r').read()\n"
    ))
    records = _effects_for(tmp_path, "ambiguous.py")
    assert records, "an unproven receiver must remain in the census as a mutation candidate"
    assert any("unresolved_open_receiver" in json.dumps(record) for record in records)


def test_reassigned_path_local_is_not_treated_as_proven(tmp_path: Path) -> None:
    _socket(tmp_path, "reassigned.py", (
        "from pathlib import Path\n"
        "def read(root: Path, other) -> str:\n"
        "    ledger = root / 'a.jsonl'\n"
        "    ledger = other\n"
        "    return ledger.open('r').read()\n"
    ))
    records = _effects_for(tmp_path, "reassigned.py")
    assert records, "a twice-bound receiver must not be proven read-only"


def test_str_annotated_parameter_is_not_a_path(tmp_path: Path) -> None:
    _socket(tmp_path, "textish.py", (
        "from pathlib import Path\n"
        "def read(root: str) -> str:\n"
        "    ledger = Path(root) / 'a.jsonl'\n"
        "    return ledger.open('r').read()\n"
    ))
    # `Path(root) / ...` is a path-shaped value even though `root` is a str, so it reads.
    assert _effects_for(tmp_path, "textish.py") == []
# --- isoformat chain: a str-returning method on any receiver -----------------------------
# `datetime.now().isoformat().replace("+00:00", "Z")` is a string operation. The resolver
# required a proven-str receiver, so this shape was counted as a filesystem mutation by method
# name alone. `isoformat()` returns `str` for every standard-library type that defines it.


def test_isoformat_chain_is_a_string_operation() -> None:
    source = (
        "from datetime import datetime, timezone\n"
        "def stamp() -> str:\n"
        "    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')\n"
    )
    tree = ast.parse(source)
    resolver = _pure_string_replace_resolver(tree)
    calls = [node for node in ast.walk(tree)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
             and node.func.attr == "replace"]
    assert calls and resolver(calls[0])


def test_isoformat_with_keywords_is_not_admitted() -> None:
    """A keyword argument could change the receiver, so it refutes the proof."""
    source = (
        "def stamp(value):\n"
        "    return value.isoformat(sep='T').replace('-', '_')\n"
    )
    tree = ast.parse(source)
    resolver = _pure_string_replace_resolver(tree)
    calls = [node for node in ast.walk(tree)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
             and node.func.attr == "replace"]
    assert calls and resolver(calls[0]) is False


def test_replace_on_an_unproven_parameter_is_still_a_candidate() -> None:
    """The fix must not turn an unknown receiver into a string operation."""
    source = (
        "def rewrite(value):\n"
        "    return value.replace('a', 'b')\n"
    )
    tree = ast.parse(source)
    resolver = _pure_string_replace_resolver(tree)
    calls = [node for node in ast.walk(tree)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
             and node.func.attr == "replace"]
    assert calls and resolver(calls[0]) is False


def test_loop_variable_replace_is_not_proven() -> None:
    source = (
        "def labels(items):\n"
        "    for item in items:\n"
        "        print(item.replace('-', ' '))\n"
    )
    tree = ast.parse(source)
    resolver = _pure_string_replace_resolver(tree)
    calls = [node for node in ast.walk(tree)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
             and node.func.attr == "replace"]
    assert calls and resolver(calls[0]) is False
def test_a_string_operation_is_never_recorded_as_a_repository_mutation() -> None:
    """No recorded mutation may come from a provable string method call.

    This is the invariant behind four separate corrections during the campaign: `str.replace`
    treated as `os.replace`, and `isoformat().replace(...)` treated as a write. It checks the
    live census rather than one fixture, so a future regression of either shape fails here.
    """
    records = discover_effect_surfaces(ROOT)
    suspicious = [
        record for record in records
        if "replace" in record["call"] and record["effect"] == "filesystem_mutation"
        and "replace" not in {"os.replace", "replace"}
        and not record["call"].startswith("os.")
    ]
    # A receiver-qualified `x.replace` is only acceptable when x is a path-like name; the
    # census cannot prove that here, so this asserts the *absence* of the string shapes that
    # were already shown to be false positives.
    string_shapes = {"text.replace", "value.replace", "name.replace", "key.replace",
                     "label.replace", "identifier.replace", "rel.replace"}
    offenders = [record for record in suspicious if record["call"] in string_shapes]
    assert offenders == [], f"string operations recorded as mutations: {offenders[:5]}"
