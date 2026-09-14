---
canonical_id: "installedsmokechild"
kind: system
layer: execution
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Installed VSIX child install and host test

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Checks package bytes before/after CLI installation and runs the installed harness in an owned cached host.

## Historical source state

Child result and host test receipt.

## Limits and unknowns

Proxy environment is not a network sandbox; parent trusts child hash result; Windows install uses shell=true.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S589]] — same-file-bytes

## Directed relationships

- [[Systems/hostcachecustody]] — resolves retained cached executable (`E1456`)
- [[Systems/installedhostsmoke]] — runs installed host test suite (`E1458`)
