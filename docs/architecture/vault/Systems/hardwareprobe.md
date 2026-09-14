---
canonical_id: "hardwareprobe"
kind: system
layer: discovery
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Hardware library and sensor observation

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Runs parallel external/library child probes and parent sensors, chooses best-free GPU metadata and reports available backends.

## Historical source state

HardwareProfile, fingerprint, sensor availability and errors.

## Limits and unknowns

Report valid true means report produced. Optional accelerator find_spec can count backend readiness without actual executor check; parent probes not all deadline-bound.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2229]] — same-file-bytes
- [[Evidence/S2234]] — same-file-bytes

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
