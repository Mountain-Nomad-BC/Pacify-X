---
canonical_id: "remediationorder"
kind: system
layer: reasoning
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Memory defect priority and dependency order

[[Layers/reasoning]] · [[Views/Full_Architecture]]

## Purpose

Computes topological node order and separately ranks defects by class under a spend cap.

## Historical source state

Inert apply-labelled steps, planned spend and dependency order.

## Limits and unknowns

Repair steps follow class/ID priority rather than dependency order; blocked descendants are labelled cycles.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2381]] — same-file-bytes

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
