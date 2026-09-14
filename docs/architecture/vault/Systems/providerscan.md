---
canonical_id: "providerscan"
kind: system
layer: evidence
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Fixed-pattern Python provider-route index

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Scans runtime/scripts Python for selected SDK imports and call suffixes; excludes gateway and reuses content-matched scan records.

## Historical source state

Per-file content hashes, violations and current/stale index report.

## Limits and unknowns

Not a general call graph or all-language network interception. Reused violations are not bound to scanner algorithm revision; matching file bytes do not independently rederive stored findings.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2719]] — same-file-bytes
- [[Evidence/S4318]] — same-file-bytes

## Directed relationships

- [[Systems/provider]] — checks selected source bypass patterns (`E405`)
