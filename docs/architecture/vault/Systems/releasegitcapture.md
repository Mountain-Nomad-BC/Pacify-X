---
canonical_id: "releasegitcapture"
kind: system
layer: release
currentness: changed-file
runtime_observed: false
certified: false
---
# Git version tag and dirty-input capture

[[Layers/release]] · [[Views/Full_Architecture]]

## Purpose

Compares version surfaces and captures origin, annotated tag, HEAD/tree and classified dirty paths.

## Historical source state

Git/version release identity.

## Limits and unknowns

Sequential queries; origin text/annotated tag are not remote or signed-tag authentication.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2925]] — changed-file
- [[Evidence/S2926]] — changed-file

## Directed relationships

- [[Systems/releaseclassify]] — classifies dirty paths and invalid evidence (`E818`)
