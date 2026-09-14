---
canonical_id: "hostfingerprint"
kind: system
layer: host
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Host source fingerprint worker

[[Layers/host]] · [[Views/Full_Architecture]]

## Purpose

Scans selected root paths with metadata and bounded content hashes; guards cached complete fingerprints with watch stamps.

## Historical source state

Watch stamp, complete fingerprint, memo metrics and worker response.

## Limits and unknowns

Normal success waits worker exit. Watch and complete scans are sequential, not an atomic source snapshot. Directory content budgets are per watched tree; code reads child content despite a metadata-only comment.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1173]] — same-file-bytes
- [[Evidence/S1180]] — same-file-bytes
- [[Evidence/S1255]] — same-file-bytes

## Directed relationships

- [[Systems/hostcache]] — provides source predicate for retained metadata reuse (`E380`)
