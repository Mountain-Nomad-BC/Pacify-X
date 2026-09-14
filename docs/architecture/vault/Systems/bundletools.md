---
canonical_id: "bundletools"
kind: system
layer: governance
currentness: changed-file
runtime_observed: false
certified: false
---
# SDK tool input result and error boundary

[[Layers/governance]] · [[Views/Full_Architecture]]

## Purpose

Validates registered input, runs executor, optionally validates output and projects tool errors.

## Historical source state

Typed input and content/isError result.

## Limits and unknowns

PX defines no outputSchema; unavailable/failure payload returned normally may still look successful to instrumentation.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S807]] — changed-file

## Directed relationships

- [[Systems/bundlezod]] — validates registered Standard Schema input (`E1620`)
- [[Systems/bundlepxcontext]] — invokes registered executor with context (`E1621`)
- [[Systems/bundlestdio]] — returns tool result through codec and channel (`E1625`)
