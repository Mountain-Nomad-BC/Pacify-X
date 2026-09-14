"""Startup metadata and discovery inputs are bounded before effects or coercion."""

import json
from pathlib import Path

import pytest

from runtime import startup, tooling
from runtime.registry import load_skill_catalog

ROOT = Path(__file__).resolve().parents[1]


def _startup_root(tmp_path):
    (tmp_path / "bootstrap").mkdir()
    (tmp_path / "bootstrap/startup.toml").write_bytes(
        (ROOT / "bootstrap/startup.toml").read_bytes()
    )
    (tmp_path / "registry").mkdir()
    (tmp_path / "registry/capability_map.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "active_capabilities": [],
                "rule": "Owned fixture",
            }
        )
    )
    return tmp_path


def _aliases(tmp_path, rows):
    folder = tmp_path / "registry"
    folder.mkdir(exist_ok=True)
    (folder / "source_tool_aliases.json").write_text(
        json.dumps(
            {"schema_version": "1.0", "loading_rule": "Owned fixture", "aliases": rows}
        )
    )


@pytest.mark.parametrize("value", [True, 1.5, "four"])
def test_probe_worker_count_requires_bounded_integer(tmp_path, value):
    root = _startup_root(tmp_path)
    with pytest.raises(ValueError):
        startup.bounded_startup(root, root, tool_names=(), max_probe_workers=value)


@pytest.mark.parametrize("names", ["git", [None], [True], [1], ["../outside"]])
def test_explicit_tool_names_are_validated_before_resolver(tmp_path, names):
    root = _startup_root(tmp_path)

    def forbidden(name):
        pytest.fail("resolver called before complete name admission")

    with pytest.raises(ValueError):
        startup.bounded_startup(root, root, tool_names=names, tool_resolver=forbidden)


def test_explicit_tool_override_cannot_bypass_eight_probe_limit(tmp_path):
    root = _startup_root(tmp_path)
    with pytest.raises(ValueError):
        startup.bounded_startup(
            root,
            root,
            tool_names=[f"tool-{index}" for index in range(9)],
            tool_resolver=lambda name: pytest.fail("oversized override probed"),
        )


def test_duplicate_heavy_name_iterator_has_raw_intake_bound(tmp_path):
    root = _startup_root(tmp_path)

    def names():
        for index in range(66):
            if index == 65:
                pytest.fail("duplicate-heavy names bypassed raw intake budget")
            yield "git"

    with pytest.raises(ValueError):
        startup.bounded_startup(
            root, root, tool_names=names(), tool_resolver=lambda name: None
        )


@pytest.mark.parametrize(
    "row",
    [
        False,
        {"tool_id": "search", "candidates": "rg", "startup_default": True},
        {"tool_id": "search", "candidates": [None], "startup_default": True},
        {"tool_id": "search", "candidates": ["rg"], "startup_default": "true"},
    ],
)
def test_alias_rows_are_rejected_instead_of_dropped_or_coerced(tmp_path, row):
    _aliases(tmp_path, [row])
    with pytest.raises(ValueError):
        tooling.startup_candidates(tmp_path)


@pytest.mark.parametrize("maximum", [True, 1.5, 100, "8"])
def test_family_maximum_has_same_typed_bound_as_startup(tmp_path, maximum):
    _aliases(
        tmp_path, [{"tool_id": "search", "candidates": ["rg"], "startup_default": True}]
    )
    with pytest.raises(ValueError):
        tooling.probe_tool_family(
            tmp_path, "search", maximum=maximum, resolver=lambda name: None
        )


@pytest.mark.parametrize("location", [False, 5, {}, "x" * 4097])
def test_discovery_location_is_typed_bounded_metadata(tmp_path, location):
    _aliases(
        tmp_path, [{"tool_id": "search", "candidates": ["rg"], "startup_default": True}]
    )
    with pytest.raises(ValueError):
        tooling.probe_tool_family(tmp_path, "search", resolver=lambda name: location)


@pytest.mark.parametrize(
    "document", [{"models": None}, {"models": {}}, {"models": [False]}]
)
def test_startup_model_array_is_typed_before_snapshot(tmp_path, document):
    root = _startup_root(tmp_path)
    (root / "registry/models.json").write_text(json.dumps(document))
    with pytest.raises(ValueError):
        startup.bounded_startup(root, root, tool_names=())


def test_registry_catalog_loader_rejects_duplicate_identity(tmp_path):
    (tmp_path / "registry").mkdir()
    header = 'schema_version="1.0"\nloading_rule="metadata_only_at_startup_body_after_selection"\ndefault_active_limit=3\nhard_active_limit=8\n'
    row = '[[skills]]\nid="duplicate"\nversion="1.0"\nstatus="active"\nbody="body.md"\ncontract="registry/skill_packages/duplicate.json"\nadmission_record="duplicate"\ntags=[]\n'
    (tmp_path / "registry/skill_catalog.toml").write_text(header + row + row)
    with pytest.raises(ValueError):
        load_skill_catalog(tmp_path)


@pytest.mark.parametrize("policies", [None, {}, [False], ["policy"]])
def test_policy_metadata_rejects_malformed_rows_before_probing(tmp_path, policies):
    root = _startup_root(tmp_path)
    (root / "policies").mkdir()
    (root / "policies/policy_index.json").write_text(json.dumps({"policies": policies}))
    with pytest.raises(ValueError):
        startup.bounded_startup(
            root,
            root,
            tool_names=["git"],
            tool_resolver=lambda name: pytest.fail("malformed policy reached probe"),
        )


def test_catalog_is_admitted_before_any_tool_callback(tmp_path):
    root = _startup_root(tmp_path)
    (root / "registry/skill_catalog.toml").write_text("skills = [false]")
    with pytest.raises(ValueError):
        startup.bounded_startup(
            root,
            root,
            tool_names=["git"],
            tool_resolver=lambda name: pytest.fail("invalid catalog reached probe"),
        )


def _forbid_open(monkeypatch, paths):
    original = Path.open

    def guarded(path, *args, **kwargs):
        if path in paths:
            pytest.fail("unadmitted metadata file opened")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded)


def test_capability_count_is_checked_before_contract_acquisition(tmp_path, monkeypatch):
    from runtime.registry import navigation_index

    root = _startup_root(tmp_path)
    contract = root / "contract.json"
    contract.write_text(json.dumps({"id": "same", "status": "active"}))
    rows = [{"id": str(i), "contract": "contract.json"} for i in range(10001)]
    (root / "registry/capability_map.json").write_text(
        json.dumps({"active_capabilities": rows})
    )
    _forbid_open(monkeypatch, {contract})
    with pytest.raises(ValueError):
        navigation_index(root)


def test_capability_identity_duplicates_reject_before_contract_read(
    tmp_path, monkeypatch
):
    from runtime.registry import navigation_index

    root = _startup_root(tmp_path)
    contract = root / "contract.json"
    contract.write_text("{}")
    (root / "registry/capability_map.json").write_text(
        json.dumps(
            {"active_capabilities": [{"id": "same", "contract": "contract.json"}] * 2}
        )
    )
    _forbid_open(monkeypatch, {contract})
    with pytest.raises(ValueError):
        navigation_index(root)


def test_contract_size_preflight_precedes_open(tmp_path, monkeypatch):
    from runtime.registry import navigation_index

    root = _startup_root(tmp_path)
    contract = root / "contract.json"
    with contract.open("wb") as stream:
        stream.truncate(1024 * 1024 + 1)
    (root / "registry/capability_map.json").write_text(
        json.dumps(
            {"active_capabilities": [{"id": "same", "contract": "contract.json"}]}
        )
    )
    _forbid_open(monkeypatch, {contract})
    with pytest.raises(ValueError):
        navigation_index(root)


def test_contract_escape_rejects_before_external_read(tmp_path, monkeypatch):
    from runtime.registry import navigation_index

    root = _startup_root(tmp_path)
    contract = tmp_path.parent / (tmp_path.name + "-outside-contract.json")
    # No external file is created; read interception proves no external acquisition.
    (root / "registry/capability_map.json").write_text(
        json.dumps(
            {"active_capabilities": [{"id": "same", "contract": "../" + contract.name}]}
        )
    )
    _forbid_open(monkeypatch, {root / ".." / contract.name})
    with pytest.raises(ValueError):
        navigation_index(root)


@pytest.mark.parametrize(
    "field,value",
    [
        ("provides", "abc"),
        ("effects", [False]),
        ("cost", []),
        ("evidence", "current"),
        ("id", False),
    ],
)
def test_navigation_contract_consumed_fields_are_typed(tmp_path, field, value):
    from runtime.registry import navigation_index

    root = _startup_root(tmp_path)
    contract = {
        "id": "same",
        "status": "active",
        "provides": [],
        "effects": [],
        "cost": {},
        "evidence": {},
    }
    contract[field] = value
    (root / "contract.json").write_text(json.dumps(contract))
    (root / "registry/capability_map.json").write_text(
        json.dumps(
            {"active_capabilities": [{"id": "same", "contract": "contract.json"}]}
        )
    )
    with pytest.raises(ValueError):
        navigation_index(root)


def test_complete_contract_byte_budget_precedes_any_contract_read(
    tmp_path, monkeypatch
):
    from runtime import registry

    root = _startup_root(tmp_path)
    rows = []
    paths = set()
    for identity in ("one", "two"):
        path = root / f"{identity}.json"
        path.write_text(json.dumps({"id": identity, "status": "active"}))
        paths.add(path)
        rows.append({"id": identity, "contract": path.name})
    (root / "registry/capability_map.json").write_text(
        json.dumps({"active_capabilities": rows})
    )
    monkeypatch.setattr(registry, "MAX_NAVIGATION_TOTAL_BYTES", 60)
    _forbid_open(monkeypatch, paths)
    with pytest.raises(ValueError, match="byte budget"):
        registry.navigation_index(root)


def test_catalog_metadata_does_not_require_package_or_body_acquisition(tmp_path):
    (tmp_path / "registry").mkdir()
    (tmp_path / "registry/skill_catalog.toml").write_bytes(
        (ROOT / "registry/skill_catalog.toml").read_bytes()
    )
    result = load_skill_catalog(tmp_path)
    assert len(result["skills"]) == len(load_skill_catalog(ROOT)["skills"])
    assert not (tmp_path / ".px").exists()
    assert not (tmp_path / "registry/skill_packages").exists()


def test_tool_alias_size_limit_precedes_open(tmp_path, monkeypatch):
    _aliases(tmp_path, [])
    path = tmp_path / "registry/source_tool_aliases.json"
    with path.open("wb") as stream:
        stream.truncate(1024 * 1024 + 1)
    _forbid_open(monkeypatch, {path})
    with pytest.raises(ValueError):
        tooling.startup_candidates(tmp_path)


def test_model_count_precedes_per_model_validation(tmp_path, monkeypatch):
    root = _startup_root(tmp_path)
    (root / "registry/models.json").write_text(
        json.dumps({"models": [{"model_id": str(i)} for i in range(257)]})
    )
    monkeypatch.setattr(
        startup,
        "validate_model_capability",
        lambda value: pytest.fail("model validator ran before collection admission"),
    )
    with pytest.raises(ValueError):
        startup.bounded_startup(root, root, tool_names=())


def test_project_profile_size_precedes_open(tmp_path, monkeypatch):
    root = _startup_root(tmp_path)
    folder = root / ".engineering-bootstrap"
    folder.mkdir()
    path = folder / "project.toml"
    with path.open("wb") as stream:
        stream.truncate(65537)
    _forbid_open(monkeypatch, {path})
    with pytest.raises(ValueError):
        startup.bounded_startup(root, root, tool_names=())


def test_cooperative_callback_expiry_waits_for_callback_settlement(
    tmp_path, monkeypatch
):
    import threading

    root = _startup_root(tmp_path)
    now = [100.0]
    entered = []
    settled = []
    workers = []
    monkeypatch.setattr(startup.time, "monotonic", lambda: now[0])

    def resolver(name):
        workers.append(threading.current_thread())
        entered.append(name)
        try:
            now[0] += 2.0
            return "/tool"
        finally:
            settled.append(name)

    with pytest.raises(ValueError, match="cooperative duration"):
        startup.bounded_startup(
            root,
            root,
            tool_names=["git"],
            tool_resolver=resolver,
            max_startup_seconds=1.0,
        )
    assert entered == settled == ["git"]
    assert all(not worker.is_alive() for worker in workers)


def test_name_iterator_exhaustion_is_checked_against_deadline(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(startup.time, "monotonic", lambda: now[0])

    def names():
        yield "git"
        now[0] += 61.0

    with pytest.raises(ValueError, match="cooperative duration"):
        tooling.bounded_tool_names(names())


def test_discovery_preserves_spaces_plus_and_shared_family_aliases(tmp_path):
    _aliases(
        tmp_path,
        [
            {"tool_id": "compiler", "candidates": ["c++"], "startup_default": True},
            {
                "tool_id": "compiler",
                "candidates": ["my compiler"],
                "startup_default": False,
            },
            {"tool_id": "other", "candidates": ["c++"], "startup_default": False},
        ],
    )
    probes = tooling.probe_tool_family(
        tmp_path, "compiler", resolver=lambda name: "/" + name
    )
    assert [row.candidate for row in probes] == ["c++", "my compiler"]


@pytest.mark.parametrize(
    "relative",
    [
        "registry/models.json",
        "registry/skill_catalog.toml",
        "policies/policy_index.json",
    ],
)
def test_present_metadata_directory_is_not_reported_as_missing(tmp_path, relative):
    root = _startup_root(tmp_path)
    (root / relative).mkdir(parents=True)
    with pytest.raises(ValueError):
        startup.bounded_startup(root, root, tool_names=())


@pytest.mark.parametrize(
    "seconds", [True, 0, -1, 301, float("nan"), float("inf"), "60"]
)
def test_startup_duration_is_typed_finite_and_bounded(tmp_path, seconds):
    root = _startup_root(tmp_path)
    with pytest.raises(ValueError):
        startup.bounded_startup(root, root, tool_names=(), max_startup_seconds=seconds)
