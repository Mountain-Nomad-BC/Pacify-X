---
canonical_id: "workspace"
kind: system
layer: scope
currentness: changed-file
runtime_observed: false
certified: false
---
# Workspace and project lifecycle

[[Layers/scope]] · [[Views/Full_Architecture]]

## Purpose

Initializes and discovers projects, commissions them, activates project-scoped sessions and dispatches workflow requests.

## Historical source state

Workspace registry, project records, active-session leases and project-management bindings.

## Limits and unknowns

Activation checks processing-order state; a missing or malformed managed-project campaign blocks it.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3329]] — changed-file
- [[Evidence/S3340]] — changed-file

## Directed relationships

- [[Systems/streams]] — executes registered project workflow (`E013`)
- [[Systems/repair]] — requires valid processing-order state (`E014`)
- [[Systems/capture]] — binds capture to active project (`E015`)
- [[Systems/scheduler]] — uses bounded work-plane execution (`E044`)
- [[Systems/vault]] — selects canonical project memory root (`E056`)
- [[Systems/commission]] — requires managed-project scaffold checks (`E165`)
- [[Systems/lifecyclestatus]] — exposes commissioned project lifecycle metadata (`E253`)
- [[Systems/projecttemplates]] — commissions management artifacts (`E563`)
- [[Systems/streamdispatch]] — supplies active lease and materialized payload (`E564`)
- [[Systems/intakeinventory]] — inventories new dropped projects (`E588`)
- [[Systems/commissioning]] — commissions dropped project (`E592`)
