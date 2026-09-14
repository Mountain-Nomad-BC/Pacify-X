---
canonical_id: "providerprobe"
kind: system
layer: evidence
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Optional memory provider isolation harness

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Constructs local and foreign providers through a supplied factory, performs seven isolation/attribution/failure/correction probes, and optionally retains a certificate.

## Historical source state

Per-probe results, provider/config identity, certified_accelerator or disabled.

## Limits and unknowns

Unlike a pure policy check this harness calls put, correct, search and inject_failure. Success is scoped to the supplied factory, configuration and tested behaviors; it does not prove a universal external-provider deployment. A production caller was not established in the searched surfaces; this node is deliberately shown without a behavioral edge.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2714]] — same-file-bytes

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
