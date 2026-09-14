---
canonical_id: "catalogmerge"
kind: system
layer: discovery
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Studio physical catalog and lifecycle merge

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Reads bounded physical revisions, validates artifact relationships, and attaches path-keyed Python lifecycle status before filtering and paging.

## Historical source state

Candidate/authenticated lifecycle rows, refused count, revision hashes and local graph/layout artifacts.

## Limits and unknowns

Python verifies receipt identity at projection time, but returned status rows omit the bound revision digest. JS later accepts authenticated/status by path without rebinding to its newly read bytes.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1275]] — same-file-bytes
- [[Evidence/S1191]] — same-file-bytes
- [[Evidence/S3121]] — same-file-bytes

## Directed relationships

- [[Systems/revisionguard]] — hashes physical tree for each accepted revision (`E388`)
- [[Systems/agenteditgraph]] — offers content-bound graph for editor reopening (`E1043`)
- [[Systems/workfloweditnormalize]] — offers persisted layout and authority declarations (`E1044`)
