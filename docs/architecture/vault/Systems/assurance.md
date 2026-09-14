---
canonical_id: "assurance"
kind: system
layer: evidence
currentness: changed-file
runtime_observed: false
certified: false
---
# Behavioral assurance and fault attribution

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Runs bounded probes, attributes failures, compares shadows/behavioral deltas and requires explicit lineage and benchmark controls.

## Historical source state

Probe outcomes, failure signals, comparison evidence and assurance reports.

## Limits and unknowns

A matched comparison still applies only to its frozen treatment, environment and tested denominator.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1628]] — changed-file
- [[Evidence/S1634]] — same-file-bytes
- [[Evidence/S1643]] — same-file-bytes

## Directed relationships

- [[Systems/improvement]] — can inform improvement priorities (`E087`)
- [[Systems/evidence]] — produces typed behavioral proof (`E098`)
- [[Systems/behavioralprobe]] — exposes a separate assurance or classification primitive (`E732`)
- [[Systems/failureattribution]] — exposes a separate assurance or classification primitive (`E733`)
- [[Systems/evaluationlineage]] — exposes a separate assurance or classification primitive (`E734`)
- [[Systems/assuranceaxes]] — exposes a separate assurance or classification primitive (`E735`)
- [[Systems/behavioraldelta]] — exposes a separate assurance or classification primitive (`E736`)
- [[Systems/shadowcomparison]] — exposes a separate assurance or classification primitive (`E737`)
- [[Systems/foundationshapes]] — exposes a separate assurance or classification primitive (`E738`)
- [[Systems/datasetmetadata]] — exposes a separate assurance or classification primitive (`E739`)
- [[Systems/foundationshift]] — exposes a separate assurance or classification primitive (`E740`)
- [[Systems/changeproofclass]] — exposes a separate assurance or classification primitive (`E741`)
