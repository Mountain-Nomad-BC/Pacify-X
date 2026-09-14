---
canonical_id: "bridge"
kind: system
layer: host
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Python bridge and bounded host work

[[Layers/host]] · [[Views/Full_Architecture]]

## Purpose

Translates UI queries and Studio commands into bounded Python calls with revision-aware caches and host approval bindings.

## Historical source state

Cache keys, revision fingerprints, in-flight requests and approval identity.

## Limits and unknowns

A cached dashboard snapshot is a projection, not a new authoritative outcome.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1178]] — same-file-bytes
- [[Evidence/S1200]] — same-file-bytes
- [[Evidence/S1207]] — same-file-bytes
- [[Evidence/S1172]] — same-file-bytes

## Directed relationships

- [[Systems/cli]] — invokes the selected Python owner (`E003`)
- [[Systems/scheduler]] — coalesces and bounds host requests (`E043`)
- [[Systems/hostsigning]] — signs exact Studio operation payload (`E178`)
- [[Systems/catalogproof]] — requests authority-verified lifecycle projection (`E274`)
- [[Systems/hostcache]] — constructs and invalidates cache authorities (`E284`)
- [[Systems/hostgovernor]] — schedules selected adapter operations (`E376`)
- [[Systems/hostcapture]] — directly captures broker and workspace commands (`E378`)
- [[Systems/hostfingerprint]] — checks source identity before snapshot and cached page requests (`E379`)
- [[Systems/catalogproof]] — queries authenticated lifecycle projection before physical catalog merge (`E386`)
- [[Systems/studioverifierlocator]] — describes verifier while preparing approval (`E867`)
