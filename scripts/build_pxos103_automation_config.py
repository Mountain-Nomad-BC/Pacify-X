"""Build the pxos103 release-candidate automation config for Pacify-X 0.9.0."""
import json
from pathlib import Path

PY = "C:/Python314/python.exe"
ART = "extension/dist/pacify-x-vscode-0.9.0.vsix"
SHA = "97f491042d7de73397bd6e597f546d70b310303f31870babf752e19a3e402859"
SIZE = 4362109
MTIME = 1790557945653874800
CAND = "pacify-x-certification-20260928-r103-0.9.0"
ROOT_DOC = "C:/Users/Ben/Documents/bootstrap_project/Pacify-X"


def owner(*a):
    return [PY, "-B", *a]


def stage(step):
    return owner(
        "scripts/run_release_stage_owner.py",
        "--config",
        ".engineering-bootstrap/processing-order/r102-successor-stage.json",
        "--step",
        step,
        "--execute",
    )


installed_cmd = owner(
    "scripts/run_installed_operational_owner.py",
    "--root", ".",
    "--candidate-id", CAND,
    "--artifact", ART,
    "--artifact-sha256", SHA,
    "--artifact-size", str(SIZE),
    "--artifact-mtime-ns", str(MTIME),
    "--smoke-timeout-seconds", "600",
    "--exhaustive-timeout-seconds", "4200",
    "--summary-output", "evidence/release/pxos103-installed-operational-summary.json",
    "--package-receipt", "evidence/release/r102-stage-receipts/%s-package.json" % CAND,
    "--install-receipt", "evidence/release/r102-stage-receipts/%s-install.json" % CAND,
    "--windows-argv-json", json.dumps([
        "node", "extension/scripts/run-installed-vsix-smoke.js",
        "--engine-root", ".", "--vsix", ART,
        "--expected-sha256", SHA,
        "--receipt", "evidence/release/pxos103-installed/windows-smoke.json",
        "--lifecycle-receipt", "evidence/release/pxos103-installed/windows-lifecycle.json",
    ]),
    "--windows-log", "evidence/release/pxos103-installed/windows.log",
    "--windows-receipt", "evidence/release/pxos103-installed/windows-smoke.json",
    "--windows-lifecycle-receipt", "evidence/release/pxos103-installed/windows-lifecycle.json",
    "--ubuntu-argv-json", json.dumps([
        "wsl.exe", "-d", "Ubuntu", "--", "bash", "-lc",
        "cd /mnt/c/Users/Ben/Documents/bootstrap_project/Pacify-X"
        " && TMPDIR=/home/ben node extension/scripts/run-installed-vsix-smoke.js"
        " --engine-root /mnt/c/Users/Ben/Documents/bootstrap_project/Pacify-X"
        " --vsix /mnt/c/Users/Ben/Documents/bootstrap_project/Pacify-X/" + ART +
        " --expected-sha256 " + SHA +
        " --receipt /mnt/c/Users/Ben/Documents/bootstrap_project/Pacify-X/evidence/release/pxos103-installed/ubuntu-smoke.json"
        " --lifecycle-receipt /mnt/c/Users/Ben/Documents/bootstrap_project/Pacify-X/evidence/release/pxos103-installed/ubuntu-lifecycle.json"
    ]),
    "--ubuntu-log", "evidence/release/pxos103-installed/ubuntu.log",
    "--ubuntu-receipt", "evidence/release/pxos103-installed/ubuntu-smoke.json",
    "--ubuntu-lifecycle-receipt", "evidence/release/pxos103-installed/ubuntu-lifecycle.json",
    "--exhaustive-argv-json", json.dumps([
        "node", "extension/scripts/run-isolated-current-source-walk.js",
        "--post-audit-long-running", "--vsix", ART,
        "--output", "evidence/release/pxos103-installed/exhaustive-output",
        "--report", "evidence/release/pxos103-installed/exhaustive-report.json",
    ]),
    "--exhaustive-log", "evidence/release/pxos103-installed/exhaustive.log",
    "--exhaustive-report", "evidence/release/pxos103-installed/exhaustive-report.json",
    "--exhaustive-receipt", "evidence/release/pxos103-installed/exhaustive-output/receipt.json",
    "--execute",
)

card_reconcile = [
    owner(
        "scripts/reconcile_unverified_operational_controls.py",
        "--root", ".", "--check",
        "--walk-receipt", "evidence/release/pxos103-installed/exhaustive-output/receipt.json",
        "--reconcile-cards",
    ),
    owner(
        "scripts/reconcile_cohesion_cards.py",
        "--root", ".", "--target", "closed",
        "--installed-proof", "evidence/release/pxos103-installed-operational-summary.json",
        "--automation-state", "evidence/release/pxos103-automation-state.json",
    ),
    owner(
        "scripts/reconcile_unverified_operational_controls.py",
        "--root", ".",
        "--walk-receipt", "evidence/release/pxos103-installed/exhaustive-output/receipt.json",
        "--reconcile-cards",
    ),
    owner(
        "scripts/reconcile_cohesion_cards.py",
        "--root", ".", "--target", "closed",
        "--installed-proof", "evidence/release/pxos103-installed-operational-summary.json",
        "--automation-state", "evidence/release/pxos103-automation-state.json",
        "--apply",
    ),
]

config = {
    "schema_version": "px.release-candidate-automation/1.0",
    "root": "../..",
    "candidate_id": CAND,
    "candidate_date": "20260928",
    "predecessor_campaign_id": "pacify-x-certification-20260928-r102-0.9.0",
    "repair_campaign_id": "pacify-x-architecture-remediation-20260909",
    "evidence_prefix": "pxos103",
    "artifact": ART,
    "artifact_sha256": SHA,
    "artifact_size": SIZE,
    "artifact_mtime_ns": MTIME,
    "automation_state": "evidence/release/pxos103-automation-state.json",
    "log_root": "evidence/release/pxos103-driver-logs",
    "installed_summary": "evidence/release/pxos103-installed-operational-summary.json",
    "installed_exhaustive_receipt": "evidence/release/pxos103-installed/exhaustive-output/receipt.json",
    "cohesion_dag": ".engineering-bootstrap/punch-cards/cohesion-closure-20260904/dag.json",
    "identity_manifest": {
        "path": ".engineering-bootstrap/processing-order/pxos103-source-manifest.json"
    },
    "timeouts_seconds": {
        "archive_clear": 120,
        "reconcile": 900,
        "identity": 300,
        "sections": 14400,
        "full_profile": 14190,
        "validate": 1800,
        "package": 600,
        "install": 900,
        "installed_operational": 7200,
        "card_reconcile": 1800,
        "preflight": 3600,
        "finalize": 3600,
    },
    "fresh_paths": [
        "evidence/release/pxos103-automation-state.json",
        "evidence/release/pxos103-driver-logs",
        "evidence/release/pxos103-installed",
        "evidence/release/pxos103-installed-operational-summary.json",
        "evidence/release/r102-stage-owner-logs",
        "evidence/release/r102-stage-receipts",
        ".engineering-bootstrap/processing-order/pxos103-source-manifest.json",
    ],
    "owners": {
        "archive_clear": {"commands": [stage("archive_clear")]},
        "reconcile": {"commands": [stage("reconcile")]},
        "identity": {"commands": [stage("identity")]},
        "sections": {"commands": [stage("sections")]},
        "full_profile": {"commands": [stage("full_profile")]},
        "validate": {"commands": [stage("validate")]},
        "package": {"commands": [stage("package")]},
        "install": {"commands": [stage("install")]},
        "installed_operational": {"commands": [installed_cmd]},
        "card_reconcile": {"commands": card_reconcile},
        "preflight": {"commands": [
            owner("-m", "runtime.cli", "--root", ".", "release", "preflight",
                  "--release", "0.9.0", "--artifact", ART, "--deep")
        ]},
        "finalize": {"commands": [
            owner("-m", "runtime.cli", "--root", ".", "release", "finalize",
                  "--release", "0.9.0",
                  "--wheelhouse", "C:/Users/Ben/AppData/Local/Temp/pacify-x-release-wheelhouse-0.9.0-pxos103",
                  "--artifact-dir", "C:/Users/Ben/AppData/Local/Temp/pacify-x-release-artifacts-0.9.0-pxos103",
                  "--signing-key", ".git/pacify-x-release-key-2026")
        ]},
    },
}

out = Path(".engineering-bootstrap/processing-order/pxos103-successor-automation.json")
with out.open("x", encoding="utf-8", newline="\n") as f:
    json.dump(config, f, indent=2)
    f.write("\n")
print("wrote", out)

