---
canonical_id: "hostsigning"
kind: system
layer: governance
currentness: changed-file
runtime_observed: false
certified: false
---
# Host approval signing and consumption

[[Layers/governance]] · [[Views/Full_Architecture]]

## Purpose

Keeps host signing keys in VS Code SecretStorage, signs exact operation payloads and passes single-use capabilities to Python Studio consumption.

## Historical source state

Host key identity, signed payload, operation binding and consumed approval.

## Limits and unknowns

Read-only source inspection does not expose keys. MCP launch claims and per-operation Studio approvals have different lifetimes and reuse rules.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1265]] — same-file-bytes
- [[Evidence/S1204]] — same-file-bytes
- [[Evidence/S3094]] — changed-file
- [[Evidence/S3108]] — same-file-bytes
- [[Evidence/S2174]] — same-file-bytes
- [[Evidence/S1265]] — same-file-bytes

## Directed relationships

- [[Systems/studioauth]] — consumes single-use payload approval (`E179`)
- [[Systems/mcp]] — signs project-bound launch authority (`E180`)
