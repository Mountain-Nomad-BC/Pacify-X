---
canonical_id: "exacttoolrunner"
kind: system
layer: execution
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Exact helper subprocess and local effect observations

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Runs helper with cwd fixture, timeout and bytecode/user-site flags, then compares local files.

## Historical source state

Exit/parse/output/digest/effect record.

## Limits and unknowns

Ambient environment retained; deletion/outside effects and timeout effects are not captured.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2107]] — same-file-bytes
- [[Evidence/S2110]] — same-file-bytes

## Directed relationships

- [[Systems/exacttoolrepeat]] — supplies normalized stdout and file digests (`E1129`)
