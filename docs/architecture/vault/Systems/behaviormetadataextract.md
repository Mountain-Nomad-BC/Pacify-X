---
canonical_id: "behaviormetadataextract"
kind: system
layer: discovery
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# External behavior metadata extraction

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Hashes files and extracts lexical tags, symbols, headings and simple skill metadata.

## Historical source state

Content-addressed metadata index, counts, candidates and duplicates.

## Limits and unknowns

No source import; limited name substitution is not general secret or path redaction.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3771]] — same-file-bytes

## Directed relationships

- [[Systems/behaviormetadataplan]] — supplies index summary and skill candidates (`E1356`)
- [[Systems/externalrequirementowners]] — supplies staged alias records (`E1357`)
