---
canonical_id: "streamdispatch"
kind: system
layer: execution
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Composite stream handler and completion reducer

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Selects a registered workflow and calls one handler after metadata gates.

## Historical source state

Named output mapping and stream status.

## Limits and unknowns

Synchronous handler, post-return timeout and output-key completeness; nested decision can reject while stream completes.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2688]] — same-file-bytes

## Directed relationships

- [[Systems/transferbinding]] — calls cross-project copy handler (`E567`)
- [[Systems/streamcheckpoint]] — writes preflight and terminal records (`E568`)
- [[Systems/controlcopies]] — calls change or promotion handler (`E569`)
- [[Systems/quarantinetxn]] — calls safe cleanup wrapper (`E570`)
- [[Systems/recoverytxn]] — calls incident replacement wrapper (`E571`)
- [[Systems/controlscore]] — evaluates health resilience or work assignment (`E572`)
- [[Systems/vaultpublish]] — appends candidate memory through vault (`E573`)
- [[Systems/improvement]] — compiles candidates and backlog (`E574`)
- [[Systems/schedulerfacts]] — constructs fresh scheduler for one dispatch (`E613`)
