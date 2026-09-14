---
canonical_id: "agencyreviewers"
kind: system
layer: reasoning
currentness: changed-file
runtime_observed: false
certified: false
---
# Specialist reviewer panel selection

[[Layers/reasoning]] · [[Views/Full_Architecture]]

## Purpose

Scores explicit handoffs, reviewer roles, capability overlap and high-risk governance.

## Historical source state

Primary plus distinct division/role reviewers and risk metadata.

## Limits and unknowns

Review requirement is output metadata; zero requested maximum can still choose one.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1550]] — changed-file
- [[Evidence/S1557]] — changed-file

## Directed relationships

- [[Systems/agencyprompt]] — provides explicit selected route (`E937`)
- [[Systems/agencyrequestcompile]] — offers route for Agency adapter (`E942`)
