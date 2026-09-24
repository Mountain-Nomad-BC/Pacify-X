from dataclasses import replace
import pytest

from runtime.semantic_memory_aliases import MemoryAliasRegistry
from runtime.semantic_memory_repair import apply_legacy_reference_repair, plan_legacy_reference_repair


def aliases():
    registry = MemoryAliasRegistry()
    registry.add("architecture/core", "p", "m1")
    return registry


def test_exact_legacy_rewrite_and_fuzzy_suggestion_only():
    contents = {"note": "see mem:architecture/core and mem:architecture/cor"}
    plan = plan_legacy_reference_repair(contents, aliases())
    assert len(plan.rewrites) == 1 and len(plan.unresolved) == 1
    assert plan.unresolved[0][2] == ("architecture/core",)
    preview = apply_legacy_reference_repair(contents, plan)
    assert "pxmem://p/m1" in preview["note"]
    assert "mem:architecture/cor" in preview["note"]


def test_exact_rewrite_does_not_replace_longer_alias_prefix():
    contents = {"note": "mem:architecture/core mem:architecture/core2"}
    plan = plan_legacy_reference_repair(contents, aliases())
    preview = apply_legacy_reference_repair(contents, plan)
    assert preview["note"] == "pxmem://p/m1 mem:architecture/core2"


def test_repair_plan_is_bound_to_exact_source_content():
    contents = {"note": "mem:architecture/core"}
    plan = plan_legacy_reference_repair(contents, aliases())
    with pytest.raises(RuntimeError, match="changed since planning"):
        apply_legacy_reference_repair({"note": "prefix mem:architecture/core"}, plan)


def test_repair_plan_digest_and_write_authority_fail_closed():
    contents = {"note": "mem:architecture/core"}
    plan = plan_legacy_reference_repair(contents, aliases())
    tampered = replace(plan, plan_sha256="0" * 64)
    with pytest.raises(RuntimeError, match="digest"):
        apply_legacy_reference_repair(contents, tampered)
    with pytest.raises(PermissionError, match="canonical owner"):
        apply_legacy_reference_repair(contents, plan, write=True)
