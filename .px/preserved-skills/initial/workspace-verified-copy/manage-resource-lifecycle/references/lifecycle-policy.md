# Resource lifecycle policy

## Classifications

- `protected`: user, source, project, database, configuration, credential,
  canonical knowledge, model/runtime, or external data. Never auto-reclaim.
- `evidence`: required audit, certification, custody, report, or validation output.
  Retain under an explicit policy; preserve hashes and provenance.
- `quarantine`: unresolved or untrusted material with owner, reason, source,
  timestamp, size, review state, retention class, and disposition. Reclaim only
  after explicit review approval.
- `ephemeral`: PACIFY-X-owned scratch, test, build, conversion, package-smoke,
  transient database, temporary clone, or cache state. Reclaim after obligations.
- `unknown`: unproven ownership or purpose. Retain and classify.

## Safe reclamation gate

Require every condition:

1. PACIFY-X ownership is registered, not guessed.
2. Classification is ephemeral or reviewed quarantine has explicit approval.
3. The run is conclusively ended and does not need recovery.
4. No active owned process or resource reference requires the target.
5. Required outputs and evidence exist, are readable, and live outside the target.
6. The target resolves below a registered cleanup root and is not that root.
7. The target and descendants contain no ambiguous symlink, junction, mount, or
   reparse traversal.
8. Cleanup is bounded, verifiable, and receipt-producing.

Treat a failed or unknown condition as retain. Age, size, location, and filename
patterns may support investigation but never prove ownership or eligibility.

## Run closure

Require zero active owned child processes, zero unexplained owned ephemerals,
validated evidence, persisted outputs, accounted quarantine, dispositioned cleanup
failures, zero orphan resources, and a reconciled ledger. Functional validation
cannot override a failed resource reconciliation.

## Recovery and pressure

Load unfinished ledger records on restart. Preserve recoverable resources and only
reclaim ended resources that pass the same gate. Use free-space reserve and relative
usage for `normal`, `warning`, `high`, and `critical` pressure. At elevated pressure,
reclaim only already-eligible owned ephemerals and pause new temp-heavy work when
safe. Never delete protected or unknown data to satisfy a budget.
