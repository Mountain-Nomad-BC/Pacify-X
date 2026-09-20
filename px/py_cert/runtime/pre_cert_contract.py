"""Canonical constants for PACIFY-X pre-cert repository convergence.

This module governs only the repository-convergence phase.  It must never start
or claim a certification campaign stage.
"""
from __future__ import annotations

SCHEMA_VERSION = "px.pre-cert-repository-convergence/1.0"
HASH_MANIFEST_SCHEMA = "px.pre-cert-repository-hash-manifest/1.0"
GENERATED_RECONCILE_SCHEMA = "px.pre-cert-generated-reconcile/1.0"
GIT_CONVERGENCE_SCHEMA = "px.pre-cert-git-convergence/1.0"
READY_SEAL_SCHEMA = "px.pre-cert-ready/1.0"

CERTIFICATION_STEP_ORDER = (
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
)

# Files delivered by the execution-side rebuild.  Pre-cert convergence verifies
# that these are all present before it creates the source/hash baseline.
EXECUTION_PATCH_FILES = (
    "runtime/certification_contract.py",
    "runtime/release_campaign.py",
    "scripts/build_release_successor_configs.py",
    "scripts/reconcile_cohesion_cards.py",
    "scripts/reconcile_unverified_operational_controls.py",
    "scripts/run_installed_operational_owner.py",
    "scripts/run_release_candidate.py",
    "scripts/run_release_candidate_dry.py",
    "scripts/run_release_stage_owner.py",
    "scripts/validate_certification_pipeline.py",
)

# Minimum production dependencies required by the rebuilt execution surface.
# This list is intentionally broader than the patch itself: disappearing
# transitive infrastructure must block the freeze rather than fail mid-cert.
REQUIRED_CERT_ROOT_DEPENDENCIES = (
    *EXECUTION_PATCH_FILES,
    "runtime/release_identity.py",
    "runtime/cli.py",
    "runtime/test_profiles.py",
    "runtime/generated_artifacts.py",
    "runtime/resource_lifecycle.py",
    "runtime/release_artifacts.py",
    "runtime/archive_io.py",
    "runtime/operational_gap_ledger.py",
    "runtime/input_files.py",
    "runtime/json_io.py",
    "runtime/resource_storage.py",
    "runtime/wal_transaction.py",
    "scripts/clean_source_export.py",
    "scripts/pre_candidate_hygiene.py",
)

REQUIRED_REPO_ROOT_DEPENDENCIES = (
    "extension/scripts/run-installed-vsix-smoke.js",
    "extension/scripts/run-isolated-current-source-walk.js",
)

FORBIDDEN_ACTIVE_PROCESS_MARKERS = (
    "run_release_candidate.py",
    "run_release_stage_owner.py",
    "run_installed_operational_owner.py",
)

GIT_TRANSIENT_SENTINELS = (
    "MERGE_HEAD",
    "CHERRY_PICK_HEAD",
    "REVERT_HEAD",
    "REBASE_HEAD",
)
