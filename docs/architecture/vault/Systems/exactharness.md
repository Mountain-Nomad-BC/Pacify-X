---
canonical_id: "exactharness"
kind: system
layer: evidence
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Exact tool certification harness

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Loads admitted exact tools, runs bounded positive/negative/repeat fixtures and compares normalized outputs and output artifact digests.

## Historical source state

Per-tool direct-load, positive, negative, repeat and wrapper outcome evidence.

## Limits and unknowns

Read, not run. Some named negative outcomes reuse one denial result; wrapper outcome ownership and cached evidence have narrower denominators than all imaginable inputs.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2132]] — same-file-bytes

## Directed relationships

- [[Systems/pythonsurface]] — supplies per-tool execution evidence through CLI (`E309`)
- [[Systems/nativekerneltools]] — executes bounded helper fixtures (`E342`)
- [[Systems/nativememorytools]] — executes bounded helper fixtures (`E344`)
- [[Systems/nativeevidencetools]] — executes bounded helper fixtures (`E346`)
- [[Systems/nativereleasetools]] — executes bounded helper fixtures (`E348`)
- [[Systems/nativeprotocoltools]] — executes bounded helper fixtures (`E350`)
- [[Systems/nativesecuritytools]] — executes bounded helper fixtures (`E352`)
- [[Systems/nativerepotools]] — executes bounded helper fixtures (`E354`)
- [[Systems/nativeverificationtools]] — executes bounded helper fixtures (`E356`)
