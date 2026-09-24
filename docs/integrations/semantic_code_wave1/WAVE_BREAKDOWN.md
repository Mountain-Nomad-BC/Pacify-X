# Semantic-Code Integration Position

This document describes the semantic-code track inside the larger PX implementation plan. Global wave numbering is owned by the pre-implementation placement package; this payload is **Global Wave 01**.

## Global Wave 01 — deterministic semantic substrate

This package establishes the PX-native evidence layer before any local model, external language server, or orchestration layer is allowed to depend on semantic code operations.

Included domains: immutable source snapshots, stable symbol/reference/diagnostic records, backend abstraction, canonical project isolation, bounded indexing, graph projection, query APIs, revision-bound edit plans, side-effect-free preview, explicitly enabled single-file mutation, lifecycle management, deterministic receipts, and focused tests.

## Later semantic track — richer language services

A later implementation wave may add external LSP/process-backed evidence behind the existing `SemanticBackend` boundary. Expected concerns include subprocess ownership, request correlation, cancellation, shutdown/recovery, document synchronization, language-server discovery, type-aware definitions/references/renames, unhealthy-server quarantine, and comparison against the structural fallback supplied here.

## Later operator/orchestration track

Separate later waves must wire the resident tiny CPU model and larger local models into PX's existing authority owners. For the intended architecture:

- Qwen3.5-0.8B is the primary tiny internal-operator candidate;
- Qwen3-30B-A3B is the preferred initial deep sparse candidate;
- the tiny model acts as librarian, concierge, and bounded worker: it queries knowledge/skills, assembles context, invokes admitted tools, updates derived working maps/graphs through explicit contracts, and can request learning workflows when deterministic trigger conditions admit them;
- learning promotion, authoritative graph changes, knowledge admission, memory transitions, write effects, model escalation, and tool execution remain contract/effect governed;
- every operation must be queueable, bounded, cancellable where applicable, attributable, and receipted.

Wave 1 deliberately does **not** implement those authority-bearing model contracts. It gives them a reliable semantic-code tool surface to call later.

## Why the order matters

If model orchestration is allowed to directly inspect or mutate repository state before source evidence, revisions, effects and receipts are stable, the model becomes an accidental authority boundary. PX should instead make the deterministic substrate boring first, then let the model operate through it.
