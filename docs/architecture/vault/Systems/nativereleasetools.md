---
canonical_id: "nativereleasetools"
kind: system
layer: release
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Native release comparison helpers

[[Layers/release]] · [[Views/Full_Architecture]]

## Purpose

Checks ZIP CRC/name properties, hashes a selected tree, compares skill IDs/token overlap, proposes merges, computes dependency closure and aggregates supplied status labels.

## Historical source state

Hash manifests, duplicate candidates, proposed checks/suites and label-based PASS/FAIL.

## Limits and unknowns

These helpers neither enforce the registered release campaign nor issue the product release certificate. Permission changes request suites but alone leave invalidate_prior_evidence false in the impact helper.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S178]] — same-file-bytes
- [[Evidence/S183]] — same-file-bytes
- [[Evidence/S182]] — same-file-bytes
- [[Evidence/S180]] — same-file-bytes
- [[Evidence/S184]] — same-file-bytes
- [[Evidence/S179]] — same-file-bytes
- [[Evidence/S181]] — same-file-bytes

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
