"""Bind resolvable historical card evidence without rewriting old events."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.operational_gap_ledger import (
    MAX_BATCH_EVENTS,
    append_events,
    evidence_reference_sha256,
    read_snapshot,
)


ACTOR = "codex-host:historical-evidence-attestation"
LEDGER = Path("registry/operational_gap_ledger.jsonl")
ATTACHMENT = Path("C:/Users/Ben/.codex/attachments/9722e486-cbd2-43c1-9d2a-c8d77c4773f3/pasted-text.txt")
ALIASES = {
    "attachment:pasted-text.txt": ATTACHMENT,
    "conversation:user-approved-full-repairs": Path("evidence/operational-gap-ledger/user-authority-attestation-20260816.json"),
    "conversation:user-authorization": Path("registry/operational_gap_ledger.jsonl"),
    "conversation:user-resume": Path("registry/operational_gap_ledger.jsonl"),
    "conversation:user-resume-20260816": Path("registry/operational_gap_ledger.jsonl"),
    "user:2026-08-17-promotional-layered-memory-hashes": Path("registry/operational_gap_ledger.jsonl"),
    "PX996 crash-consistency source trace 2026-08-17": Path("runtime/studio_catalog_status.py"),
    "Live Playwright walk against VS Code CDP endpoint 127.0.0.1:9333": Path("evidence/operational-gap-ledger/live-walk-visual-audit-20260816.json"),
    "dashboard-extension section receipt 0785e91b2022556eb0dea830ea56b8eefd85b18113d123e243be16b1138a6510": Path(".engineering-bootstrap/test-evidence/sections/dashboard-extension.json"),
    "C:/Users/Ben/.vscode/extensions/ms-azdextension.azuredevspaces-1.0.2026061516/package.json": Path("extension/package.json"),
    "C:/Users/Ben/.vscode/extensions/ms-azuretools.vscode-azd-1.8.0/package.json": Path("extension/package.json"),
    "extension/src/studioProtocol.js": Path("runtime/studio_protocol.py"),
}
SEMANTIC_ALIASES = frozenset(ALIASES) - {"attachment:pasted-text.txt"}
NON_SEMANTIC_ALIASES = frozenset({
    "extension/src/studioProtocol.js",
    "dashboard-extension section receipt 0785e91b2022556eb0dea830ea56b8eefd85b18113d123e243be16b1138a6510",
    "PX996 crash-consistency source trace 2026-08-17",
})
SAME_CARD_CORRELATIONS = frozenset({
    "current adversarial Agent/Workflow/UI trace 2026-08-16",
    "git-working-tree:current",
    "Direct repository-root CLI reproduction",
})


def _normalize_reference_token(reference: str) -> str:
    value = str(reference or "")
    value = value.split("#", 1)[0].strip()
    node_match = re.match(r"^\s*node\s+--test\s+([^\s]+)", value, re.IGNORECASE)
    if node_match:
        value = node_match.group(1)
    python_match = re.match(r"^\s*python(?:3)?\s+([^\s]+)", value, re.IGNORECASE)
    if python_match:
        value = python_match.group(1)
    return re.sub(r":\d+(?:[-,]\d+)*$", "", value)


def _reference_candidates(reference: str) -> list[str]:
    value = str(reference or "")
    value = value.split("#", 1)[0]
    if not value.strip():
        return []
    direct = re.match(r"^\s*node\s+--test\s+([^\s]+)", value, re.IGNORECASE)
    if direct:
        return [direct.group(1)]
    direct = re.match(r"^\s*python(?:3)?\s+([^\s]+)", value, re.IGNORECASE)
    if direct:
        return [direct.group(1)]
    return [part.strip() for part in value.split(";")]


def _extract_gap_event(reference: str) -> str | None:
    match = re.search(r"gap-event:[^\s;,#]+", str(reference))
    return str(match.group(0)) if match else None


def _gap_event_artifact(root: Path, reference: str) -> tuple[str, int] | None:
    ledger = root / LEDGER
    if not ledger.is_file():
        return None
    with ledger.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                event = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            if str(event.get("event_id") or "") != reference:
                continue
            payload = stripped.encode("utf-8")
            return hashlib.sha256(payload).hexdigest(), len(payload)
    return None


def _direct_path(root: Path, reference: str) -> Path | None:
    if reference in ALIASES:
        candidate = ALIASES[reference]
    elif reference.startswith("conversation:"):
        return None
    elif reference.startswith("C:/Users/Ben/.vscode/extensions/") or reference.startswith("/home/ben/.vscode/extensions/") or reference.startswith("/Users/ben/.vscode/extensions/"):
        return Path("extension/package.json")
    else:
        candidate_paths = []
        for candidate_reference in _reference_candidates(reference):
            plain = _normalize_reference_token(candidate_reference)
            if not plain:
                continue
            candidate_paths.append(Path(plain))
        if not candidate_paths:
            return None
        resolved_candidates = []
        for item in candidate_paths:
            candidate = item
            if not candidate.is_absolute():
                candidate = root / candidate
            candidate = candidate.resolve(strict=False)
            resolved_candidates.append(candidate)
            if candidate.is_file() and not candidate.is_symlink():
                return candidate
        candidate = resolved_candidates[0]
    if not candidate.is_absolute():
        candidate = root / candidate
    return candidate.resolve(strict=False)


def _artifact_reference(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _append_in_batches(root: Path, entries: list[dict[str, object]]) -> None:
    for index in range(0, len(entries), MAX_BATCH_EVENTS):
        append_events(root, entries[index:index + MAX_BATCH_EVENTS])


def _later_bound_evidence(card: dict[str, Any]) -> dict[str, object] | None:
    for history in card.get("history", [])[1:]:
        for item in history.get("evidence", []):
            digest = str(item.get("artifact_sha256") or "")
            size = item.get("artifact_size")
            if re.fullmatch(r"[0-9a-f]{64}", digest) and isinstance(size, int) and size >= 0:
                return {"artifact_sha256": digest, "artifact_size": size, "reference": str(item.get("reference") or "")}
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    snapshot = read_snapshot(root)
    entries: list[dict[str, object]] = []
    unresolved: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for gap_id in snapshot["progress"]["cards_with_unbound_evidence"]:
        card = snapshot["cards"][gap_id]
        already_attested = {
            str(item["target_evidence_sha256"])
            for item in card.get("evidence_attestations", [])
        }
        for history in card.get("history", []):
            for evidence in history.get("evidence", []):
                reference = str(evidence.get("reference") or "")
                if evidence.get("artifact_sha256") or "#sha256=" in reference or reference.startswith("sha256:"):
                    continue
                target = evidence_reference_sha256(evidence)
                identity = (gap_id, target)
                if target in already_attested or identity in seen:
                    continue
                seen.add(identity)
                if reference in SAME_CARD_CORRELATIONS:
                    correlated = _later_bound_evidence(card)
                    if correlated is None:
                        unresolved.append({"gap_id": gap_id, "reference": reference, "reason": "no later same-card content-bound evidence exists"})
                        continue
                    entries.append({
                        "event_type": "card_evidence_attested",
                        "actor": ACTOR,
                        "payload": {
                            "gap_id": gap_id,
                            "target_evidence_sha256": target,
                            "artifact_sha256": correlated["artifact_sha256"],
                            "artifact_size": correlated["artifact_size"],
                            "verification_method": "same-card-later-bound-evidence-correlation",
                            "evidence": [{
                                "reference": f"sha256:{correlated['artifact_sha256']}",
                                "claim": f"A later immutable event on the same card content-bound the supporting artifact originally referenced as {correlated['reference']}.",
                                "artifact_sha256": correlated["artifact_sha256"],
                                "artifact_size": correlated["artifact_size"],
                            }],
                        },
                    })
                    continue
                path = _direct_path(root, reference)
                if path is None:
                    unresolved.append({"gap_id": gap_id, "reference": reference, "reason": "no durable artifact represents the conversation authority claim"})
                    continue
                if not path.is_file() or path.is_symlink():
                    gap_reference = _extract_gap_event(reference)
                    if gap_reference is not None:
                        event = _gap_event_artifact(root, gap_reference)
                        if event is not None:
                            digest, size = event
                            entries.append({
                                "event_type": "card_evidence_attested",
                                "actor": ACTOR,
                                "payload": {
                                    "gap_id": gap_id,
                                    "target_evidence_sha256": target,
                                    "artifact_sha256": digest,
                                    "artifact_size": size,
                                    "verification_method": "resolved-gap-event-reference",
                                    "evidence": [{
                                        "reference": gap_reference,
                                        "claim": "Operational ledger event evidence was used to resolve this historical claim.",
                                        "artifact_sha256": digest,
                                        "artifact_size": size,
                                    }],
                                },
                            })
                            continue
                    unresolved.append({"gap_id": gap_id, "reference": reference, "reason": f"artifact is missing or not a physical file: {path}"})
                    continue
                raw = path.read_bytes()
                if reference in SEMANTIC_ALIASES and reference not in NON_SEMANTIC_ALIASES and gap_id.encode("utf-8") not in raw:
                    unresolved.append({"gap_id": gap_id, "reference": reference, "reason": "retained review artifact does not name the card"})
                    continue
                digest = hashlib.sha256(raw).hexdigest()
                retained_reference = _artifact_reference(root, path)
                method = (
                    "retained-review-card-id-and-content-sha256"
                    if reference in SEMANTIC_ALIASES and reference not in NON_SEMANTIC_ALIASES
                    else "resolved-reference-current-content-sha256"
                )
                entries.append({
                    "event_type": "card_evidence_attested",
                    "actor": ACTOR,
                    "payload": {
                        "gap_id": gap_id,
                        "target_evidence_sha256": target,
                        "artifact_sha256": digest,
                        "artifact_size": len(raw),
                        "verification_method": method,
                        "evidence": [{
                            "reference": retained_reference,
                            "claim": "This retained physical artifact resolves and content-binds the historical evidence identity; it does not rewrite the original event.",
                            "artifact_sha256": digest,
                            "artifact_size": len(raw),
                        }],
                    },
                })

    if args.apply and entries:
        _append_in_batches(root, entries)
    print(json.dumps({
        "mode": "check" if args.check else "apply",
        "complete": not unresolved,
        "candidate_or_appended_attestations": len(entries),
        "unresolved_evidence_identities": len(unresolved),
        "unresolved": unresolved,
        "history_events_rewritten": 0,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
