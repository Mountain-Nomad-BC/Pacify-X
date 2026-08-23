"""Reviewed release-test skip policy without finalizer coupling."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET


ALLOWED_RELEASE_TEST_SKIPS = {
    (
        "tests.test_build_installed_host_control_evidence",
        "test_current_host_receipt_remains_bound_when_retained_vsix_is_available",
    ): "retained installed VSIX is external host custody",
    (
        "tests.test_clean_source_export",
        "test_posix_unzip_restores_and_directly_executes_script",
    ): "ordinary POSIX unzip execution is verified on a host with unzip",
    (
        "tests.test_native_skills.NativeSkillTests",
        "test_live_workspace_original_backup_restores_exactly",
    ): "native migration has not run",
    (
        "tests.test_skill_studio",
        "test_skill_source_rejects_duplicate_canonical_directory_aliases",
    ): "host filesystem does not permit distinct case aliases",
}


def junit_skip_policy_gate(path: Path) -> dict[str, Any]:
    """Allow only reviewed host-conditional skips; reject every unknown skip."""
    root = ET.parse(path).getroot()
    allowed: list[str] = []
    unexpected: list[str] = []
    for case in root.iter("testcase"):
        skipped = case.find("skipped")
        if skipped is None:
            continue
        identity = (
            str(case.attrib.get("classname", "")),
            str(case.attrib.get("name", "")),
        )
        expected_reason = ALLOWED_RELEASE_TEST_SKIPS.get(identity)
        observed_reason = " ".join(
            filter(None, (str(skipped.attrib.get("message", "")), skipped.text or ""))
        )
        label = f"{identity[0]}::{identity[1]}"
        if expected_reason and expected_reason in observed_reason:
            allowed.append(label)
        else:
            unexpected.append(label)
    return {
        "valid": not unexpected,
        "allowed_count": len(allowed),
        "allowed": sorted(allowed),
        "unexpected_count": len(unexpected),
        "unexpected": sorted(unexpected),
    }
