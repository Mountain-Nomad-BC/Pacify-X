---
name: synchronize-derived-architecture
description: Keep routes, service ownership, contracts, generated code, diagrams, and documentation synchronized from declared canonical sources. Use when changing architecture maps, generated clients, route registries, documentation graphs, or when duplicate/stale derived artifacts may drift from their owner.
---

# Synchronize Derived Architecture

1. Identify and record the canonical owner before editing any projection.
2. Inventory derived artifacts, consumers, generators, and exact-hash duplicate groups.
3. Change the canonical source and run its deterministic generator.
4. Compare generated outputs byte-for-byte or structurally, as their contract requires.
5. Reject routes or services without an owner and reject undocumented manual edits to generated files.
6. For document consolidation, create a promotion packet naming the canonical copy, duplicate hashes, inbound links, and replacement targets.
7. Preview any relocation. Use recoverable external quarantine with a restore manifest; never hard-delete duplicates.
8. Rebuild cross-asset graphs and prove that every consumer resolves to the canonical owner.

If no canonical owner can be established, stop with an explicit conflict rather than choosing the newest-looking file.
