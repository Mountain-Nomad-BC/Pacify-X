---
canonical_id: "host"
kind: system
layer: host
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# AI host and human authority

[[Layers/host]] · [[Views/Full_Architecture]]

## Purpose

Supplies intent and approval; Codex-host, external agent and explicitly delegated PX execution remain distinct owners.

## Historical source state

Host session, approval identity and executor ownership.

## Limits and unknowns

PX policy does not transfer native host security authority.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2451]] — same-file-bytes
- [[Evidence/S2244]] — same-file-bytes

## Directed relationships

- [[Systems/ui]] — requests and approves operations (`E001`)
- [[Systems/effects]] — supplies independent approval identity (`E006`)
- [[Systems/procedures]] — interprets selected workflow instructions (`E208`)
- [[Systems/proposalbuilders]] — supplies bounded proposal inputs (`E315`)
- [[Systems/cijobs]] — triggers declared pull-request or main push pipeline (`E322`)
- [[Systems/nativekerneltools]] — invokes an explicit native helper CLI (`E341`)
- [[Systems/nativememorytools]] — invokes an explicit native helper CLI (`E343`)
- [[Systems/nativeevidencetools]] — invokes an explicit native helper CLI (`E345`)
- [[Systems/nativereleasetools]] — invokes an explicit native helper CLI (`E347`)
- [[Systems/nativeprotocoltools]] — invokes an explicit native helper CLI (`E349`)
- [[Systems/nativesecuritytools]] — invokes an explicit native helper CLI (`E351`)
- [[Systems/nativerepotools]] — invokes an explicit native helper CLI (`E353`)
- [[Systems/nativeverificationtools]] — invokes an explicit native helper CLI (`E355`)
