---
canonical_id: "studioauthority"
kind: system
layer: governance
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Canonical Studio authority records

[[Layers/governance]] · [[Views/Full_Architecture]]

## Purpose

Authenticates local capability/grant/binding/executor records with an external-project HMAC key and resolves current grant closure.

## Historical source state

Signed canonical envelopes, content hashes and compensating transaction history.

## Limits and unknowns

HMAC proves local key possession; authority scopes/evidence are caller declarations here. Transaction readers lack writer lock, and multi-record rollback is not crash atomic.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3117]] — same-file-bytes

## Directed relationships

- [[Systems/durablepublisher]] — signs run events heads and recovery receipts (`E437`)
