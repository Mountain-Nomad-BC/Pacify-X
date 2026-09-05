# Risks

Track exposure, mitigation, owner, evidence, and residual risk.

## Register

| ID | Risk | Severity | Mitigation | Evidence | Status |
|---|---|---|---|---|---|
| R-001 | Historical passing evidence is mistaken for current-source acceptance. | critical | Require typed claim class plus source/dependency revision binding. | `confirmed-denominator.json`, `PX-ASSURE-001` | repair verification in progress |
| R-002 | Separate runtime owners drift semantically. | critical | Shared conformance vectors and stable violation IDs. | `PX-ASSURE-002`, `PX-PROVIDER-001` | open |
| R-003 | A repair leaves transitive consumers or projections stale. | critical | Universal invalidation plus affected-proof planning. | `PX-CORE-004`, `PX-EFF-003` | open |
| R-004 | Large ledger state exhausts time, memory, or disk. | critical | Live benchmark, explicit budgets, custody-preserving migration. | `PX-LEDGER-001`, `PX-LEDGER-002` | open |
| R-005 | Premature broad certification repeats final60-final85 churn. | critical | No broad stage before downstream-green repair freeze; one successor campaign only. | DAG repair rules | mitigated |
| R-006 | macOS support is claimed from declarations rather than execution. | high | Require external macOS host receipt for successor bytes. | `PX-COMM-004` | external dependency |

## Escalation

Critical risks stop closed. Destructive, privileged, credential-bearing, billable-provider, or out-of-scope external effects require separate explicit authority. Publication is deferred to the one successor campaign.
