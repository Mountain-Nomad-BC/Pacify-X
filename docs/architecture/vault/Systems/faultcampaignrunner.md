---
canonical_id: "faultcampaignrunner"
kind: system
layer: execution
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Declared release fault lane runner

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Validates declared dimension union then runs Python/Node lanes and writes summary.

## Historical source state

Lane exit evidence and post-run selected test hashes.

## Limits and unknowns

Unsupervised captured subprocesses; timeout loses partial summary; declared dimensions do not prove test coverage.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3996]] — same-file-bytes
- [[Evidence/S3995]] — same-file-bytes

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
