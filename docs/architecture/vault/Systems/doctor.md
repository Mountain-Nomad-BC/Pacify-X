---
canonical_id: "doctor"
kind: system
layer: evidence
currentness: changed-file
runtime_observed: false
certified: false
---
# Composed PX Doctor diagnostics

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Collects eight bounded diagnostic sections, combines blocked/degraded/healthy precedence and optionally retains a hash-bound report through the JSON WAL.

## Historical source state

Coverage, integrity, transactions, provider budgets, Git, environment, runtime and extension sections; report and optional receipt.

## Limits and unknowns

valid=True means a well-formed composed report. A blocked report can still be valid; certification_ready is a diagnostic flag, not the release certificate.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2774]] — changed-file
- [[Evidence/S2772]] — changed-file
- [[Evidence/S2773]] — changed-file

## Directed relationships

- [[Systems/recoverypass]] — inspects known WAL roots without applying repair (`E263`)
- [[Systems/observers]] — reconciles coverage with supplied health evidence (`E267`)
- [[Systems/routeclass]] — checks registered route tiers and blind spots (`E268`)
- [[Systems/wal]] — retains optional report receipt transactionally (`E270`)
- [[Systems/healthclaimderive]] — assesses supplied extension claim (`E973`)
- [[Systems/doctorintegrity]] — collects integrity before dependent runtime section (`E1149`)
- [[Systems/doctorgit]] — collects repository metadata (`E1150`)
- [[Systems/doctorhandofffreshness]] — collects environment and handoff evidence (`E1151`)
- [[Systems/doctorproviderreadiness]] — collects provider policy state (`E1152`)
- [[Systems/doctorwal]] — inspects configured recovery roots (`E1153`)
- [[Systems/livecoverageproof]] — reconciles declared operational route coverage (`E1155`)
- [[Systems/healthreportverify]] — assesses first extension activity claim (`E1156`)
- [[Systems/doctorcompose]] — combines eight collected section states (`E1157`)
