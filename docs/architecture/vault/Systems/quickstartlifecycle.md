---
canonical_id: "quickstartlifecycle"
kind: system
layer: execution
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Quickstart commissioning demonstration

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Runs eight sequential CLI invocations for order status, preview, commissioning, classification, selection, hydration, dry preview and integrity.

## Historical source state

New demo project and captured step results.

## Limits and unknowns

Each subprocess has60 seconds but the whole demo has no aggregate bound; its test gives the entire process90 seconds. Failure leaves partial output without the final receipt.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S294]] — same-file-bytes
- [[Evidence/S4327]] — same-file-bytes

## Directed relationships

- [[Systems/cli]] — invokes eight sequential commands (`E1401`)
- [[Systems/commission]] — creates demo project via commission apply (`E1402`)
- [[Systems/quickstartreceipt]] — publishes after all steps return (`E1403`)
