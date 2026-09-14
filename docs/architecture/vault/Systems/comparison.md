---
canonical_id: "comparison"
kind: system
layer: reasoning
currentness: changed-file
runtime_observed: false
certified: false
---
# A-B comparison and confidence gates

[[Layers/reasoning]] · [[Views/Full_Architecture]]

## Purpose

Compares frozen incumbent/challenger revisions using hash-bound trials, a Wilson lower confidence bound and minimum evidence.

## Historical source state

Trial evidence, wins/losses/ties, comparison receipt and retained loser revision.

## Limits and unknowns

The controller records/evaluates supplied trials; it is not itself a general experiment runner.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2327]] — changed-file
- [[Evidence/S2328]] — changed-file
- [[Evidence/S2296]] — changed-file

## Directed relationships

- [[Systems/learninggate]] — supplies statistical comparison gate (`E077`)
