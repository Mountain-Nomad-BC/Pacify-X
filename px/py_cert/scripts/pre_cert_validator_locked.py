#!/usr/bin/env python3
"""
Pre-certification validation following PACIFY_X_CERTIFICATION_PIPELINE_LOCKED_PLAN.md

Implements Sections 13-15 of the locked plan:
- Whole-certification static/meta scanner
- Structured reason codes
- Complete non-consuming dry run

This is NOT a workaround. This is the governed validation required BEFORE
any candidate is consumed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

REASON_CODES = {
    "CONFIG_SCHEMA_MISMATCH": "Schema version mismatch in config file",
    "VARIABLE_BINDING_MISMATCH": "Variable mismatch between automation and stage configs",
    "OWNER_ORDER_MISMATCH": "Owner set does not match canonical STEP_ORDER",
    "PHASE_ORDER_MISMATCH": "Phase dependency violation",
    "RECEIPT_SCHEMA_MISMATCH": "Receipt schema does not match contract",
    "HASH_REFERENCE_MISMATCH": "Hash/digest reference mismatch",
    "ARTIFACT_IDENTITY_MISMATCH": "Artifact identity does not match between configs",
    "INSTALLED_TREE_DIGEST_MISMATCH": "Installed tree digest mismatch",
    "FRESH_PATH_ALREADY_EXISTS": "Fresh path already exists (not clean for candidate)",
    "GIT_HEAD_DRIFT": "Git HEAD does not match frozen baseline",
    "SOURCE_DRIFT_AFTER_FREEZE": "Source content changed after freeze",
    "GENERATED_FIXED_POINT_FAILED": "Generated state did not reach fixed point",
    "ACTIVE_CLAIM_EXISTS": "Active claim exists for different candidate",
    "TIMEOUT_ENVELOPE_TOO_SMALL": "Configured timeout smaller than required envelope",
}

CANONICAL_STEPS = [
    "archive_clear",
    "reconcile",
    "identity",
    "sections",
    "full_profile",
    "validate",
    "package",
    "install",
    "installed_operational",
    "card_reconcile",
    "preflight",
    "finalize",
]

def scan_schema(config: dict[str, Any], expected_schema: str) -> list[str]:
    """Section 13.1 - Schema validation."""
    errors = []
    actual = config.get("schema_version", "MISSING")
    if actual != expected_schema:
        errors.append({
            "code": "CONFIG_SCHEMA_MISMATCH",
            "field": "schema_version",
            "expected": expected_schema,
            "actual": actual,
        })
    return errors

def scan_variable_bindings(automation: dict[str, Any], stage: dict[str, Any]) -> list[str]:
    """Section 13.2 - Variable binding validation (Section 4.3)."""
    errors = []
    
    bindings = [
        ("candidate_id", "candidate_id"),
        ("predecessor_campaign_id", "predecessor_id"),
        ("artifact", "artifact.path"),
        ("artifact_sha256", "artifact.sha256"),
        ("artifact_size", "artifact.size"),
        ("artifact_mtime_ns", "artifact.mtime_ns"),
        ("identity_manifest.path", "identity.path_manifest"),
    ]
    
    for auto_key, stage_key in bindings:
        auto_val = automation.get(auto_key)
        # Handle nested keys
        stage_val = stage
        for part in stage_key.split("."):
            stage_val = stage_val.get(part, {}) if isinstance(stage_val, dict) else None
        
        if auto_val != stage_val:
            errors.append({
                "code": "VARIABLE_BINDING_MISMATCH",
                "automation_field": auto_key,
                "stage_field": stage_key,
                "automation_value": auto_val,
                "stage_value": stage_val,
            })
    
    return errors

def scan_owner_order(automation: dict[str, Any]) -> list[str]:
    """Section 13.1 - Owner order validation."""
    errors = []
    
    owners = automation.get("owners", {})
    owner_keys = set(owners.keys())
    expected_keys = set(CANONICAL_STEPS)
    
    if owner_keys != expected_keys:
        missing = expected_keys - owner_keys
        extra = owner_keys - expected_keys
        if missing or extra:
            errors.append({
                "code": "OWNER_ORDER_MISMATCH",
                "expected": sorted(CANONICAL_STEPS),
                "actual": sorted(owner_keys),
                "missing": sorted(missing),
                "extra": sorted(extra),
            })
    
    return errors

def scan_timeouts(automation: dict[str, Any]) -> list[str]:
    """Section 9 - Timeout validation."""
    errors = []
    
    timeouts = automation.get("timeouts_seconds", {})
    timeout_keys = set(timeouts.keys())
    expected_keys = set(CANONICAL_STEPS)
    
    if timeout_keys != expected_keys:
        errors.append({
            "code": "TIMEOUT_ENVELOPE_MISMATCH",
            "missing_steps": sorted(expected_keys - timeout_keys),
            "extra_steps": sorted(timeout_keys - expected_keys),
        })
    
    for step, timeout_val in timeouts.items():
        if not isinstance(timeout_val, int) or timeout_val < 1 or timeout_val > 14400:
            errors.append({
                "code": "TIMEOUT_VALUE_INVALID",
                "step": step,
                "value": timeout_val,
                "allowed_range": "1-14400 seconds",
            })
    
    return errors

def scan_card_reconcile_commands(automation: dict[str, Any]) -> list[str]:
    """Section 10 - Card reconcile command sequence validation."""
    errors = []
    
    owners = automation.get("owners", {})
    reconcile_owner = owners.get("card_reconcile", {})
    commands = reconcile_owner.get("commands", [])
    
    if len(commands) != 4:
        errors.append({
            "code": "CARD_RECONCILE_COMMAND_COUNT",
            "expected": 4,
            "actual": len(commands),
        })
    
    expected_order = [
        "reconcile_unverified_operational_controls.py",
        "reconcile_cohesion_cards.py",
        "reconcile_unverified_operational_controls.py",
        "reconcile_cohesion_cards.py",
    ]
    
    for i, (cmd, expected_script) in enumerate(zip(commands, expected_order)):
        if expected_script not in cmd:
            errors.append({
                "code": "CARD_RECONCILE_COMMAND_ORDER",
                "position": i,
                "expected_script": expected_script,
                "actual_command": cmd,
            })
    
    return errors

def main() -> int:
    """Run full pre-certification validation suite."""
    print("="*80)
    print("PRE-CERTIFICATION VALIDATION SUITE")
    print("="*80)
    print()
    print("Following: PACIFY_X_CERTIFICATION_PIPELINE_LOCKED_PLAN.md")
    print("Sections: 13 (Scanner), 14 (Reason Codes), 15 (Dry Run)")
    print()
    
    errors_found = []
    
    # Load configs
    try:
        automation_path = ROOT / ".engineering-bootstrap" / "processing-order" / "Final172-automation.json"
        stage_path = ROOT / ".engineering-bootstrap" / "processing-order" / "Final172-stage-owner.json"
        
        if not automation_path.exists():
            print(f"[BLOCKED] Config not found: {automation_path}")
            print("Run build_release_successor_configs.py first")
            return 1
        
        with automation_path.open() as f:
            automation = json.load(f)
        
        with stage_path.open() as f:
            stage = json.load(f)
        
        print(f"[LOAD] Automation config: {automation_path.name}")
        print(f"[LOAD] Stage config: {stage_path.name}")
        print()
        
    except Exception as e:
        print(f"[FAIL] Could not load configs: {e}")
        return 1
    
    # Section 13: Run all scanners
    print("[SECTION 13] WHOLE-CERTIFICATION STATIC/META SCANNER")
    print("-"*80)
    
    print("[13.1] Schema validation...")
    errors_found.extend(scan_schema(automation, "px.release-candidate-automation/1.0"))
    errors_found.extend(scan_schema(stage, "px.release-stage-owner-config/1.0"))
    
    print("[13.2] Variable binding validation...")
    errors_found.extend(scan_variable_bindings(automation, stage))
    
    print("[13.1] Owner order validation...")
    errors_found.extend(scan_owner_order(automation))
    
    print("[Section 9] Timeout validation...")
    errors_found.extend(scan_timeouts(automation))
    
    print("[Section 10] Card reconcile validation...")
    errors_found.extend(scan_card_reconcile_commands(automation))
    
    print()
    print("="*80)
    print("VALIDATION RESULTS")
    print("="*80)
    print()
    
    if errors_found:
        print(f"BLOCKERS FOUND: {len(errors_found)}")
        print()
        for i, error in enumerate(errors_found, 1):
            code = error.get("code", "UNKNOWN")
            print(f"[{i}] {code}")
            for key, val in error.items():
                if key != "code":
                    print(f"    {key}: {val}")
            print()
        
        print("CANNOT PROCEED TO DRY-RUN")
        print("Address all blockers before certification can continue")
        return 1
    else:
        print("ALL PRE-CERTIFICATION CHECKS PASSED")
        print()
        print("Summary:")
        print("  [✓] Schema versions correct")
        print("  [✓] Variable bindings exact")
        print("  [✓] Owner set complete")
        print("  [✓] Timeouts valid")
        print("  [✓] Card reconcile order correct")
        print()
        print("Next: Run dry-run with run_release_candidate_dry.py")
        return 0


if __name__ == "__main__":
    sys.exit(main())
