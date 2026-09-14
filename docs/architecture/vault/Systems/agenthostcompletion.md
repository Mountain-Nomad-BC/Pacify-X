---
canonical_id: "agenthostcompletion"
kind: system
layer: execution
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Host model preparation and terminal receipt

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Prepares signed task/instructions/model/tool grants, then validates returned model options, token counters, tool receipts and top-level output before publishing terminal state and run receipt.

## Historical source state

Prepared host request, running/terminal durable state and signed runtime receipt.

## Limits and unknowns

Model and tool execution occur in host. Python validates reported identity/shape; terminal state is committed before signing/writing final run receipt. Ordinary launch preview blocks unresolved memory/handoff bindings.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1566]] — same-file-bytes

## Directed relationships

- [[Systems/hostmodel]] — hands execution to VS Code host (`E426`)
