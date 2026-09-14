---
canonical_id: "foundrydraftobject"
kind: system
layer: acquisition
currentness: changed-file
runtime_observed: false
certified: false
---
# Studio intake draft object

[[Layers/acquisition]] · [[Views/Full_Architecture]]

## Purpose

Returns accepted/rejected manifest object after candidate validation and explicit decision/actor/reason.

## Historical source state

SkillStudioDraft dataclass, no canonical promotion authority.

## Limits and unknowns

No physical draft staging or persistence in intake method; no authored runtime caller of export/intake found beyond definitions.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2188]] — changed-file
- [[Evidence/S3040]] — same-file-bytes

## Directed relationships

- [[Systems/skillstudio]] — requires separate physical package conversion (`E692`)
