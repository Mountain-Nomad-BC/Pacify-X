"""Reconcile the two independent live-walk audits into stable gap cards."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.operational_gap_ledger import CHAIN_STAGES, append_events, read_snapshot


ACTOR = "codex-primary:live-walk-report-reconciliation"
REPORTS = {
    "live-walk-visual-audit-20260816": Path("evidence/operational-gap-ledger/live-walk-visual-audit-20260816.json"),
    "live-walk-coverage-adversary-20260816": Path("evidence/operational-gap-ledger/live-walk-coverage-adversary-20260816.json"),
}


CARD_SPECS = {
    "visual-first-fold-blocker": {
        "surface": "dashboard", "severity": "high", "classification": "UI",
        "control": "global status and identity blocker layout",
        "expected": "A compact persistent blocker preserves the first fold for the active surface and exposes detail on demand.",
        "observed": "The repeated global status strip and identity panel consume most of the first fold across captured surfaces.",
    },
    "advanced-navigation-state": {
        "surface": "dashboard-control-plane", "severity": "medium", "classification": "UI",
        "control": "knowledgeCore/runtimeCore selected navigation state",
        "expected": "The active advanced surface has a visible and programmatically selected navigation control.",
        "observed": "Knowledge Core and Runtime Core loaded while navigation_active remained false.",
    },
    "walk-capture-completeness": {
        "surface": "dashboard-control-plane", "severity": "high", "classification": "integration",
        "control": "per-surface and builder screenshot capture",
        "expected": "Every declared capture produces a bounded artifact or an explicit terminal skip record without losing the rest of the walk.",
        "observed": "Only 8 of 17 declared captures succeeded; nine surface/builder/sidebar captures and the supplemental graph capture failed.",
    },
    "walk-depth-coverage": {
        "surface": "dashboard", "severity": "medium", "classification": "integration",
        "control": "full-surface scrolled-state visual capture",
        "expected": "The walk retains bounded first-fold and deep-panel views for each surface so off-screen controls are auditable.",
        "observed": "All retained images use one first-fold viewport and omit deeper panels enumerated by the DOM.",
    },
    "walker-control-chain-join": {
        "surface": "dashboard-control-plane", "severity": "critical", "classification": "integration",
        "control": "stable control_id to interaction-chain evidence join",
        "expected": "The walker loads the canonical 827-control denominator and emits one exact terminal record for every control and every chain stage.",
        "observed": "The walker records surface presence and two unsaved deltas, but no stable control IDs and zero complete per-control chains.",
    },
    "walker-missing-semantic-surfaces": {
        "surface": "studio-lifecycle", "severity": "high", "classification": "UI",
        "control": "skill-studio and studio-lifecycle operational walk",
        "expected": "Skill Studio and Studio lifecycle receive explicit bounded walk regions and control dispositions.",
        "observed": "Skill Studio and Studio lifecycle are absent from the retained live-walk receipt.",
    },
    "walker-skip-governance": {
        "surface": "studio-lifecycle", "severity": "critical", "classification": "integration",
        "control": "mutating-control skip disposition",
        "expected": "Every unexercised mutating control records authority, reason, expected effect, and return condition under its stable control ID.",
        "observed": "Mutating controls are globally avoided without per-control terminal dispositions.",
    },
    "walker-variant-identity": {
        "surface": "dashboard-control-plane", "severity": "high", "classification": "integration",
        "control": "duplicate action variant identity",
        "expected": "Repeated actions retain distinct stable identities for row, modal, surface, and lifecycle variants.",
        "observed": "The walker collapses visible actions to data-action literals, discarding variant identity.",
    },
    "walker-durable-recovery-pass": {
        "surface": "studio-lifecycle", "severity": "critical", "classification": "persistence",
        "control": "persistence reload/reopen failure and recovery pass",
        "expected": "The walk performs reversible save/reload and injected negative/recovery passes with before/after receipts.",
        "observed": "No persistence, reload/reopen, failure-handling, rollback, or recovery path is exercised.",
    },
}


VISUAL_MAP = {
    "PX-OS-001": ["PX-OS-085"],
    "LWVA-20260816-001": ["visual-first-fold-blocker"],
    "PX-OS-010": ["PX-OS-010"],
    "PX-OS-014": ["PX-OS-014"],
    "PX-OS-015": ["PX-OS-015"],
    "PX-OS-016": ["PX-OS-016"],
    "PX-OS-017": ["PX-OS-017"],
    "PX-OS-019": ["PX-OS-019"],
    "PX-OS-018": ["PX-OS-018"],
    "PX-OS-062": ["PX-OS-062"],
    "LWVA-20260816-002": ["advanced-navigation-state"],
    "LWVA-20260816-003": ["walk-capture-completeness", "PX-OS-135"],
    "LWVA-20260816-004": ["walk-depth-coverage"],
}


COVERAGE_MAP = {
    "PX-WALK-COV-001": ["walker-control-chain-join", "PX-OS-103"],
    "PX-WALK-COV-002": ["walker-control-chain-join"],
    "PX-WALK-COV-003": ["walker-missing-semantic-surfaces"],
    "PX-WALK-COV-004": ["walker-control-chain-join"],
    "PX-WALK-COV-005": ["walker-skip-governance"],
    "PX-WALK-COV-006": ["walker-variant-identity"],
    "PX-WALK-COV-007": ["walker-durable-recovery-pass"],
    "PX-WALK-COV-008": ["PX-OS-085"],
    "PX-WALK-COV-009": ["walk-capture-completeness", "PX-OS-135"],
    "PX-WALK-COV-010": ["walker-control-chain-join", "PX-OS-103"],
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _maximum(cards: dict[str, object]) -> int:
    values = [int(match.group(1)) for key in cards if (match := re.fullmatch(r"PX-(?:OS|GAP)-(\d+)", key))]
    return max(values, default=0)


def _chain(detail: str) -> dict[str, dict[str, object]]:
    return {stage: {"state": "unknown", "detail": detail, "evidence": []} for stage in CHAIN_STAGES}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    snapshot = read_snapshot(root)
    reports = {report_id: json.loads((root / relative).read_text(encoding="utf-8")) for report_id, relative in REPORTS.items()}
    existing_features = {card.get("feature"): gap_id for gap_id, card in snapshot["cards"].items()}
    next_id = _maximum(snapshot["cards"])
    feature_ids: dict[str, str] = {}
    entries: list[dict[str, object]] = []
    timestamp = _now()

    for feature, spec in CARD_SPECS.items():
        gap_id = existing_features.get(feature)
        if gap_id is None:
            next_id += 1
            gap_id = f"PX-OS-{next_id:03d}"
            report_ref = REPORTS["live-walk-coverage-adversary-20260816" if feature.startswith("walker-") else "live-walk-visual-audit-20260816"].as_posix()
            detail = "The complete interaction chain is not yet exercised; the independent walk audit is discovery evidence only."
            entries.append({
                "event_type": "card_discovered", "actor": ACTOR, "timestamp": timestamp,
                "payload": {
                    "gap_id": gap_id, "parent_surface": spec["surface"], "feature": feature,
                    "control_action": spec["control"], "discovery_source": report_ref,
                    "discovered_at": timestamp, "discovered_by": ACTOR,
                    "source_refs": [{"path": report_ref, "symbols": [feature]}, {"path": "extension/scripts/run-operational-ui-walk.js", "symbols": [spec["control"]]}],
                    "expected_behavior": spec["expected"], "observed_behavior": spec["observed"],
                    "interaction_chain": _chain(detail), "classification": spec["classification"],
                    "severity": spec["severity"], "operational_impact": spec["observed"],
                    "dependencies": ["PX-OS-085"] if feature != "visual-first-fold-blocker" else [],
                    "blockers": [], "assigned_owner": "unassigned",
                    "tests_required": ["Run the targeted current-source operational walk and bind exact before/action/effect/acknowledgement/reopen/recovery evidence."],
                    "completion_evidence": [], "next_action": spec["expected"],
                    "discovery_evidence": [{"reference": report_ref, "claim": spec["observed"]}],
                },
            })
        feature_ids[feature] = gap_id

    for report_id, report in reports.items():
        if report_id not in snapshot["reports"]:
            relative = REPORTS[report_id]
            raw = (root / relative).read_bytes()
            entries.append({
                "event_type": "report_registered", "actor": ACTOR, "timestamp": timestamp,
                "payload": {
                    "report_id": report_id, "source": relative.as_posix(),
                    "source_sha256": hashlib.sha256(raw).hexdigest(),
                    "finding_ids": [str(item["finding_id"]) for item in report["findings"]],
                },
            })
        reconciled = snapshot.get("reports", {}).get(report_id, {}).get("reconciliations", {})
        mapping = VISUAL_MAP if report_id.startswith("live-walk-visual") else COVERAGE_MAP
        for finding in report["findings"]:
            finding_id = str(finding["finding_id"])
            if finding_id in reconciled:
                continue
            gap_ids = [feature_ids.get(value, value) for value in mapping[finding_id]]
            entries.append({
                "event_type": "report_finding_reconciled", "actor": ACTOR, "timestamp": timestamp,
                "payload": {
                    "report_id": report_id, "finding_id": finding_id,
                    "disposition": "card", "gap_ids": gap_ids,
                    "evidence": [{
                        "reference": REPORTS[report_id].as_posix(),
                        "claim": f"Independent finding {finding_id} is retained and mapped to stable operational gap cards.",
                    }],
                },
            })

    if not args.check and entries:
        append_events(root, entries)
    print(json.dumps({"mode": "check" if args.check else "apply", "events": len(entries), "new_card_ids": feature_ids}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
