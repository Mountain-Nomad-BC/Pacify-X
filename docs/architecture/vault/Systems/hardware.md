---
canonical_id: "hardware"
kind: system
layer: execution
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Hardware routing and placement

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Keeps CPU-authoritative operations on CPU and evaluates optional acceleration using workload, capacity, correctness and performance evidence.

## Historical source state

Hardware fingerprint, benchmark evidence, placement/capacity decision and fallback.

## Limits and unknowns

Automatic CUDA selection requires current benchmark evidence; explicit CUDA requests follow a different branch.

## Historical suggested evolution

New measured evidence can change future routing decisions; production promotion has additional gates.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2235]] — same-file-bytes
- [[Evidence/S2145]] — same-file-bytes

## Directed relationships

- [[Systems/agent]] — selects compatible execution placement (`E041`)
- [[Systems/capacityleases]] — provides logical placement capacity decision (`E506`)
- [[Systems/placementtiers]] — exposes alternative placement scoring and promotion (`E507`)
- [[Systems/attachmentidentity]] — validates model before capacity routing (`E513`)
- [[Systems/hardwareprobe]] — provides live hardware report entry point (`E514`)
- [[Systems/benchmarkroute]] — delegates workload device recommendation (`E515`)
