---
canonical_id: "cijobs"
kind: system
layer: release
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# CI job dependencies and retained artifacts

[[Layers/release]] · [[Views/Full_Architecture]]

## Purpose

Declares extension, platform, assurance and governed jobs with matrices, conditionals, explicit dependencies and retained artifacts.

## Historical source state

Per-job and per-matrix test/package/gate evidence declarations.

## Limits and unknowns

YAML describes intended hosted execution; no fresh CI run was observed. Parallel jobs and needs dependencies do not constitute the local release campaign state machine.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S001]] — same-file-bytes

## Directed relationships

- [[Systems/gatecache]] — runs separately receipted assurance gates (`E323`)
