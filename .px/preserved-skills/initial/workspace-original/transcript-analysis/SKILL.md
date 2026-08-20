---
name: transcript-analysis
description: Ingest, validate, and export source-traceable transcript evidence through queue-scoped adapters. Use for support-call or conversation analysis involving issues, components, actions, outcomes, serials, measurements, lifecycle states, or concise canonical CSV/JSON results.
---

# Transcript Analysis

1. Load an explicit profile or the active project’s `.engineering-bootstrap/transcript-analysis.json`; otherwise use the dependency-free canonical-import profile.
2. Confirm the queue identity and load only that queue’s reviewed ontology.
3. Dry-run immutable ingest, then create a new named run. Never edit source transcripts or publish an ad hoc run as `latest`.
4. Preserve conversation ID, source file/date/hash, and exact source line spans.
5. Separate `PRE_CALL`, `ACTIVE_CALL`, `WRAP_UP`, and `POST_CALL` before semantic extraction.
6. Normalize terminology only through the current queue’s ontology and mutation evidence. Cross-queue transfer requires explicit review.
7. Keep asserted, negated, hypothetical, historical, and uncertain evidence distinct.
8. Keep recommendations, requests, instructions, commitments, reported completion, verified completion, proposed resolutions, and verified outcomes distinct.
9. Validate canonical call, issue, component, action, outcome, serial, and measurement records before export.
10. Export canonical CSV/JSON only unless the user explicitly requests another presentation.

Read [architecture](references/architecture.md) when adding a queue adapter or ontology. Read [runtime](references/runtime.md) before ingest, record import, validation, or export.
