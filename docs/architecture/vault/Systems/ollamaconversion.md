---
canonical_id: "ollamaconversion"
kind: system
layer: reasoning
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Local provider message and token conversion

[[Layers/reasoning]] · [[Views/Full_Architecture]]

## Purpose

Maps assistant/user text, request options and character-based token estimate.

## Historical source state

Lossy text-only request and heuristic token count.

## Limits and unknowns

Every non-assistant role becomes user; option limits are not complete numeric validation.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1157]] — same-file-bytes
- [[Evidence/S1165]] — same-file-bytes
- [[Evidence/S1158]] — same-file-bytes

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
