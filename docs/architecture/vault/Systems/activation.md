---
canonical_id: "activation"
kind: system
layer: host
currentness: changed-file
runtime_observed: false
certified: false
---
# Host activation resource transaction

[[Layers/host]] · [[Views/Full_Architecture]]

## Purpose

Registers owned disposables during extension activation; commits on success or disposes pending resources in reverse order on rollback.

## Historical source state

Pending disposables, committed/rolled-back state and context subscriptions.

## Limits and unknowns

Activation cleanup is host resource ownership, distinct from Python process/WAL lifecycle.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S860]] — same-file-bytes
- [[Evidence/S1064]] — changed-file

## Directed relationships

- [[Systems/extensionactivationown]] — wraps activation registrations (`E979`)
- [[Systems/extensionworkspacechoose]] — resolves configured canonical path (`E980`)
- [[Systems/extensionhandoff]] — checks Git and repository claim for host (`E987`)
- [[Systems/sidebarhost]] — registers active controlCenter webview owner (`E1006`)
- [[Systems/startersequence]] — routes explicit Studio setup request (`E1019`)
- [[Systems/physicalextensioninventory]] — constructs physical inventory for host (`E1046`)
- [[Systems/listenerregistration]] — registers hooks and owns singleton gate (`E1057`)
- [[Systems/ollamacatalog]] — registers optional pacify-local provider (`E1074`)
