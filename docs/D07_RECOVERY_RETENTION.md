# D07 Recovery and retention

PACIFY-X recovery is fail-closed and reconstructable. `choose_recovery` accepts a
normalized failure class, the retained failure-signature trace, retry budget,
named fallbacks, idempotency, and rollback facts. It can select `retry`,
`alternate`, `rollback`, `escalate`, or `stop`. Policy and permission denials are
never retried, unknown failures do not receive a generic retry, and repeated
signatures open the circuit.

`RecoveryCoordinator` reconciles only explicitly configured authorities. A pass
recovers named JSON WALs, reports or applies explicit durable-state migrations,
validates coordination invariants, replays configured event/session
reconcilers, and delegates registered-resource reconciliation to
`ResourceManager`. Its machine result includes `human_summary` and one of
`healthy`, `degraded`, or `blocked`; exception text is not copied into the
report, so retained forensic state remains the source of detail.

Retention has five explicit classes: `protected`, `evidence`, `operational`,
`transient`, and `unknown`. Protected, evidence, and unknown data are retained.
Operational JSON history may be bounded only after its hash ancestry validates;
pruning atomically retains a suffix, an ancestry anchor, and a receipt. Transient
cleanup never owns deletion itself: it delegates only registered
PACIFY-X-owned ephemeral resources to the existing `ResourceManager` safe gate.

Inspect configured recovery state with:

```powershell
python -m runtime.cli recovery doctor --project .
```

Add `--state`, `--wal`, or `--ledger` only for authorities that are actually
configured. The command is a dry run unless `--apply` is supplied. WAL recovery
always completes already-started atomic transactions; `--apply` controls state
migration and eligible resource reclamation.
