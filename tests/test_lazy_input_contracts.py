"""Selected skill hydration must bound intake and acquisition before commit."""

import json
from pathlib import Path

import pytest

from runtime.lazy_loader import LazySkillLoader, SkillDescriptor


@pytest.mark.parametrize(
    "limits",
    [
        {"max_active": True},
        {"max_active": 1.5},
        {"max_active": 9},
        {"max_bytes": True},
        {"max_bytes": float("nan")},
        {"max_depth": True},
        {"max_depth": 100000},
    ],
)
def test_loader_requires_typed_bounded_limits(tmp_path, limits):
    with pytest.raises(ValueError):
        LazySkillLoader(tmp_path, (), **limits)


def test_descriptor_intake_is_bounded_before_materialization(tmp_path):
    consumed = []

    def records():
        for index in range(10002):
            if index == 10001:
                raise AssertionError("descriptor intake exceeded its bound")
            consumed.append(index)
            yield SkillDescriptor("skill-" + str(index), "body.md")

    with pytest.raises(ValueError):
        LazySkillLoader(tmp_path, records())
    assert len(consumed) == 10001


@pytest.mark.parametrize(
    "descriptor",
    [
        SkillDescriptor(True, "body.md"),
        SkillDescriptor("skill", "../outside.md"),
        SkillDescriptor("skill", "body.md", dependencies="base"),
        SkillDescriptor("skill", "body.md", references="reference.md"),
        SkillDescriptor("skill", "body.md", status=False),
    ],
)
def test_descriptor_contract_is_validated_before_indexing(tmp_path, descriptor):
    with pytest.raises(ValueError):
        LazySkillLoader(tmp_path, [descriptor])


def _forbid_reads(monkeypatch, paths):
    original = Path.open
    targets = {path.resolve() for path in paths}

    def guarded(path, *args, **kwargs):
        if path.resolve() in targets:
            raise AssertionError("body acquisition preceded complete closure checks")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded)


def test_selected_active_count_is_checked_before_body_acquisition(
    tmp_path, monkeypatch
):
    body = tmp_path / "body.md"
    body.write_text("body")
    loader = LazySkillLoader(
        tmp_path,
        [
            SkillDescriptor("base", "body.md"),
            SkillDescriptor("root", "body.md", dependencies=("base",)),
        ],
        max_active=1,
    )
    _forbid_reads(monkeypatch, {body})
    with pytest.raises(ValueError, match="active skill budget"):
        loader.hydrate("root")
    assert loader.active_ids == ()


def test_all_dependency_permissions_precede_any_body_reads(tmp_path, monkeypatch):
    body = tmp_path / "body.md"
    body.write_text("body")
    descriptors = [
        SkillDescriptor("base", "body.md"),
        SkillDescriptor("denied", "body.md", status="mapped_deferred"),
        SkillDescriptor("root", "body.md", dependencies=("base", "denied")),
    ]
    loader = LazySkillLoader(tmp_path, descriptors)
    _forbid_reads(monkeypatch, {body})
    with pytest.raises(PermissionError):
        loader.hydrate("root")
    assert loader.active_ids == ()


def test_selected_body_size_is_checked_before_open(tmp_path, monkeypatch):
    body = tmp_path / "body.md"
    body.write_text("x" * 200)
    loader = LazySkillLoader(
        tmp_path, [SkillDescriptor("root", "body.md")], max_bytes=100
    )
    _forbid_reads(monkeypatch, {body})
    with pytest.raises(ValueError, match="byte budget"):
        loader.hydrate("root")
    assert loader.footprint_bytes == 0


def test_complete_reference_byte_budget_precedes_body_reads(tmp_path, monkeypatch):
    body = tmp_path / "body.md"
    body.write_text("body")
    reference = tmp_path / "reference.md"
    reference.write_text("x" * 100)
    loader = LazySkillLoader(
        tmp_path,
        [SkillDescriptor("root", "body.md", references=("reference.md",))],
        max_bytes=100,
    )
    _forbid_reads(monkeypatch, {body, reference})
    with pytest.raises(ValueError, match="byte budget"):
        loader.hydrate("root", include_references=True)
    assert loader.active_ids == ()


def test_reference_request_flag_is_boolean_even_for_cached_skill(tmp_path):
    (tmp_path / "body.md").write_text("body")
    loader = LazySkillLoader(tmp_path, [SkillDescriptor("root", "body.md")])
    loader.hydrate("root")
    with pytest.raises(ValueError):
        loader.hydrate("root", include_references="false")


def test_cached_skill_can_fulfil_a_later_reference_request(tmp_path):
    (tmp_path / "body.md").write_text("body")
    (tmp_path / "reference.md").write_text("reference")
    loader = LazySkillLoader(
        tmp_path, [SkillDescriptor("root", "body.md", references=("reference.md",))]
    )
    first = loader.hydrate("root")
    second = loader.hydrate("root", include_references=True)
    assert first.references == ()
    assert second.references == (("reference.md", "reference"),)
    assert second.bytes_loaded == 13
    assert loader.hydrate("root", include_references=True) is second


def test_failed_cached_reference_upgrade_preserves_existing_record(tmp_path):
    (tmp_path / "body.md").write_text("body")
    (tmp_path / "reference.md").write_text("x" * 100)
    loader = LazySkillLoader(
        tmp_path,
        [SkillDescriptor("root", "body.md", references=("reference.md",))],
        max_bytes=100,
    )
    first = loader.hydrate("root")
    with pytest.raises(ValueError, match="byte budget"):
        loader.hydrate("root", include_references=True)
    assert loader.hydrate("root") is first
    assert loader.footprint_bytes == 4


def test_catalog_package_escape_is_refused_before_metadata_read(tmp_path, monkeypatch):
    root = tmp_path / "project"
    (root / "registry").mkdir(parents=True)
    outside = tmp_path / "outside/skill_packages/escaped.json"
    outside.parent.mkdir(parents=True)
    outside.write_text(json.dumps({"references": []}))
    (root / "registry/skill_catalog.toml").write_text(
        'schema_version="1.0"\nloading_rule="metadata_only_at_startup_body_after_selection"\ndefault_active_limit=3\nhard_active_limit=8\n[[skills]]\nid="skill"\nversion="1.0"\nstatus="active"\nbody="body.md"\ncontract="../outside/skill_packages/escaped.json"\nadmission_record="skill"\ntags=[]\n'
    )
    _forbid_reads(monkeypatch, {outside})
    with pytest.raises(ValueError):
        LazySkillLoader.from_catalog(root)


def test_body_and_repeated_source_reference_use_one_bounded_image(
    tmp_path, monkeypatch
):
    body = tmp_path / "body.md"
    body.write_bytes(b"alpha\r\nbeta\r")
    loader = LazySkillLoader(
        tmp_path,
        [SkillDescriptor("root", "body.md", references=("body.md",))],
        max_bytes=32,
    )
    original = Path.open
    opened = []
    sizes = []

    class CheckedStream:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.stream.close()

        def fileno(self):
            return self.stream.fileno()

        def read(self, size=-1):
            assert 0 < size <= 65536
            sizes.append(size)
            return self.stream.read(size)

    def counted(path, *args, **kwargs):
        stream = original(path, *args, **kwargs)
        if path == body:
            opened.append(path)
            return CheckedStream(stream)
        return stream

    monkeypatch.setattr(Path, "open", counted)
    result = loader.hydrate("root", include_references=True)
    assert result.body == "alpha\nbeta\n"
    assert result.references == (("body.md", result.body),)
    assert result.bytes_loaded == 22 and loader.footprint_bytes == 22
    assert len(opened) == 1 and sizes


def test_actual_quarantine_component_is_refused_but_authored_skill_name_is_valid(
    tmp_path,
):
    with pytest.raises(ValueError, match="excluded"):
        LazySkillLoader(tmp_path, [SkillDescriptor("root", "quarantine/body.md")])
    path = tmp_path / ".px/skills/quarantine-external-tools/SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text("owned skill documentation")
    loader = LazySkillLoader(
        tmp_path, [SkillDescriptor("root", path.relative_to(tmp_path).as_posix())]
    )
    assert loader.hydrate("root").body == "owned skill documentation"


def test_catalog_hard_active_limit_is_checked_before_package_reads(
    tmp_path, monkeypatch
):
    (tmp_path / "registry/skill_packages").mkdir(parents=True)
    package = tmp_path / "registry/skill_packages/skill.json"
    package.write_text('{"references":[]}')
    (tmp_path / "registry/skill_catalog.toml").write_text(
        'schema_version="1.0"\nloading_rule="metadata_only_at_startup_body_after_selection"\ndefault_active_limit=1\nhard_active_limit=1\n[[skills]]\nid="skill"\nversion="1.0"\nstatus="active"\nbody="body.md"\ncontract="registry/skill_packages/skill.json"\nadmission_record="skill"\ntags=[]\n'
    )
    _forbid_reads(monkeypatch, {package})
    with pytest.raises(ValueError, match="active limits"):
        LazySkillLoader.from_catalog(tmp_path, max_active=2)


def test_mutated_source_during_acquisition_leaves_active_state_unchanged(
    tmp_path, monkeypatch
):
    body = tmp_path / "body.md"
    body.write_bytes(b"abc")
    loader = LazySkillLoader(tmp_path, [SkillDescriptor("root", "body.md")])
    original = Path.open

    class GrowingStream:
        def __init__(self, stream):
            self.stream = stream
            self.grown = False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.stream.close()

        def fileno(self):
            return self.stream.fileno()

        def read(self, size):
            if not self.grown:
                self.grown = True
                with original(body, "ab") as writer:
                    writer.write(b"extra")
            return self.stream.read(size)

    def opened(path, *args, **kwargs):
        stream = original(path, *args, **kwargs)
        return GrowingStream(stream) if path == body else stream

    monkeypatch.setattr(Path, "open", opened)
    with pytest.raises(ValueError, match="changed"):
        loader.hydrate("root")
    assert loader.active_ids == () and loader.footprint_bytes == 0


def test_dependency_cycle_is_rejected_before_body_reads(tmp_path, monkeypatch):
    path = tmp_path / "body.md"
    path.write_text("body")
    loader = LazySkillLoader(
        tmp_path,
        [
            SkillDescriptor("a", "body.md", dependencies=("b",)),
            SkillDescriptor("b", "body.md", dependencies=("a",)),
        ],
    )
    _forbid_reads(monkeypatch, {path})
    with pytest.raises(ValueError, match="cycle"):
        loader.hydrate("a")
    assert loader.active_ids == ()


def test_descriptor_exhaustion_cannot_return_after_deadline(tmp_path, monkeypatch):
    import runtime.lazy_loader as module

    now = [0.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: now[0])

    def records():
        yield SkillDescriptor("root", "body.md")
        now[0] = 11.0

    with pytest.raises(ValueError, match="duration budget"):
        LazySkillLoader(tmp_path, records(), max_seconds=10)


@pytest.mark.parametrize("seconds", [True, 0, -1, float("nan"), float("inf"), 301])
def test_duration_limit_requires_finite_bounded_number(tmp_path, seconds):
    with pytest.raises(ValueError):
        LazySkillLoader(tmp_path, (), max_seconds=seconds)


def test_catalog_size_limit_precedes_open(tmp_path, monkeypatch):
    import runtime.lazy_loader as module

    path = tmp_path / "registry/skill_catalog.toml"
    path.parent.mkdir()
    with path.open("wb") as stream:
        stream.truncate(module.MAX_CATALOG_BYTES + 1)
    _forbid_reads(monkeypatch, {path})
    with pytest.raises(ValueError, match="oversized"):
        LazySkillLoader.from_catalog(tmp_path)


def test_package_aggregate_is_preflighted_before_first_package_read(
    tmp_path, monkeypatch
):
    import runtime.lazy_loader as module

    monkeypatch.setattr(module, "MAX_PACKAGE_TOTAL_BYTES", 20)
    folder = tmp_path / "registry/skill_packages"
    folder.mkdir(parents=True)
    paths = [folder / (name + ".json") for name in ("a", "b")]
    for path in paths:
        path.write_text('{"references": []}')
    header = 'schema_version="1.0"\nloading_rule="metadata_only_at_startup_body_after_selection"\ndefault_active_limit=3\nhard_active_limit=8\n'
    rows = "".join(
        f'[[skills]]\nid="{name}"\nversion="1.0"\nstatus="active"\nbody="body.md"\ncontract="registry/skill_packages/{name}.json"\nadmission_record="{name}"\ntags=[]\n'
        for name in ("a", "b")
    )
    (tmp_path / "registry/skill_catalog.toml").write_text(header + rows)
    _forbid_reads(monkeypatch, set(paths))
    with pytest.raises(ValueError, match="aggregate metadata"):
        LazySkillLoader.from_catalog(tmp_path)
