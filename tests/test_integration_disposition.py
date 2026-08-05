from __future__ import annotations

import json
from pathlib import Path
import tempfile

from runtime.integration_disposition import (
    build_canonical_owner_index,
    build_source_disposition,
    validate_source_disposition,
)


ROOT = Path(__file__).parents[1]


def test_canonical_owner_index_is_deterministic_and_typed():
    first = build_canonical_owner_index(ROOT)
    second = build_canonical_owner_index(ROOT)
    assert first == second
    assert first["record_count"] == sum(first["counts"].values())
    assert {"skill", "contract", "workflow", "script"} <= set(first["counts"])


def test_every_source_file_gets_one_hash_bound_disposition():
    with tempfile.TemporaryDirectory() as temporary:
        source = Path(temporary) / "source"
        (source / "pack" / "overlay" / "runtime").mkdir(parents=True)
        (source / "pack" / "overlay" / "runtime" / "new.py").write_text(
            "x = 1\n", encoding="utf-8"
        )
        (source / "pack" / "__pycache__").mkdir()
        (source / "pack" / "__pycache__" / "x.pyc").write_bytes(b"cache")
        report = build_source_disposition(ROOT, source, source_alias="fixture")
        assert report["file_count"] == 2
        assert report["unaccounted_count"] == 0
        assert validate_source_disposition(report)["valid"]
        assert {item["disposition"] for item in report["records"]} == {
            "admit",
            "derived-regenerate",
        }
        damaged = json.loads(json.dumps(report))
        damaged["records"][0]["canonical_owner"] = ""
        assert not validate_source_disposition(damaged)["valid"]


def test_direct_external_pack_uses_alias_to_defer_source_material():
    with tempfile.TemporaryDirectory() as temporary:
        source = Path(temporary) / "direct-pack"
        (source / "source_material" / "upstream").mkdir(parents=True)
        (source / "source_material" / "upstream" / "hook.js").write_text(
            "runImportedHook()\n", encoding="utf-8"
        )
        (source / "runtime").mkdir()
        (source / "runtime" / "catalog.py").write_text(
            "CATALOG = {}\n", encoding="utf-8"
        )
        report = build_source_disposition(
            ROOT,
            source,
            source_alias="external-capability-intake-pack",
        )
        records = {item["source_path"]: item for item in report["records"]}
        assert records["source_material/upstream/hook.js"]["disposition"] == "defer"
        assert (
            records["runtime/catalog.py"]["canonical_owner"]
            == "runtime/external_capability_provider.py"
        )


def test_wrapped_external_pack_defers_source_material_by_package_name():
    with tempfile.TemporaryDirectory() as temporary:
        source = Path(temporary) / "intake"
        target = source / "Pacify-X-External-Capability-Intake-Pack"
        (target / "source_material").mkdir(parents=True)
        (target / "source_material" / "hook.js").write_text(
            "runImportedHook()\n", encoding="utf-8"
        )
        report = build_source_disposition(ROOT, source, source_alias="open-intake")
        assert report["records"][0]["disposition"] == "defer"


def test_overlay_cache_never_becomes_an_admission_target():
    with tempfile.TemporaryDirectory() as temporary:
        source = Path(temporary) / "source"
        cache = source / "pack" / "overlay" / "runtime" / "__pycache__"
        cache.mkdir(parents=True)
        (cache / "module.pyc").write_bytes(b"generated")
        report = build_source_disposition(ROOT, source, source_alias="fixture")
        assert report["records"][0]["disposition"] == "derived-regenerate"
        assert report["records"][0]["target_path"] is None
