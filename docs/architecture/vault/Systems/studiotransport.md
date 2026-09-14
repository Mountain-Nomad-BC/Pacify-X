---
canonical_id: "studiotransport"
kind: system
layer: host
currentness: changed-file
runtime_observed: false
certified: false
---
# Studio base64 and stdin transport

[[Layers/host]] · [[Views/Full_Architecture]]

## Purpose

Decodes bounded JSON object and dispatches requested kind/operation.

## Historical source state

Operation result or version-conflict error.

## Limits and unknowns

Different envelope limits; base64 allocation precedes bound; other exceptions are not structured here.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3098]] — changed-file
- [[Evidence/S3100]] — changed-file
- [[Evidence/S3106]] — changed-file

## Directed relationships

- [[Systems/studioapprovaldispatch]] — dispatches authenticated mutation route (`E870`)
- [[Systems/studioreadconstruction]] — dispatches preview dry-run and run reads (`E873`)
