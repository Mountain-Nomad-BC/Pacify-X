---
name: validate-knowledge-relationships
description: Validate documents, entities, aliases, versions, provenance, units, rules, catalogs, and cross-source relationships using deterministic graph constraints and visible coverage. Use when a knowledge corpus may contain orphans, duplicates, conflicting revisions, invalid references, prohibited cycles, or scope leakage.
---

# Validate Knowledge Relationships

1. Inventory every source with canonical owner, version, hash, and provenance.
2. Normalize identities while retaining source IDs and aliases.
3. Define explicit relationship, cardinality, revision, cycle, and isolation invariants.
4. Project read-only source evidence into an evaluation graph; do not create a competing business source of truth.
5. Run deterministic constraints and topology checks.
6. Record every orphan, duplicate, conflict, invalid reference, stale revision, and unavailable source.
7. Produce per-family and per-relation scorecards with visible numerators and denominators.
8. Require reviewed domain evidence before modifying canonical relationships.

Semantic similarity may propose an edge but may not certify it.
