# Memory record and repair contract

Canonical memory is concise, project-scoped, human-readable, and reconstructable without an index. Each record identifies its owner, actor session and lease, source artifact and hash, evidence locator, epistemic status, confidence and method, classification and ACL, effective/expiry times, relationships, supersession links, and revision.

Ingestion asks whether the item changes knowledge, duplicates an existing record, and can be compressed without losing evidence. Duplicate knowledge becomes a delta or correction—not another full copy.

Locality signatures generate bounded near-duplicate candidates. Semantic scoring reranks candidates. Graph links answer explicit dependency and relationship questions. A separate cryptographic hash proves integrity.

Repairs never invent facts or hard-delete. Duplicate merge, stale marking, link repair, index rebuild, or orphan reconciliation must produce a dry-run plan, preserve provenance, quarantine unsafe derived state, and await approval.

The runtime resolves each vault exclusively from the central workspace binding: `projects_tracking/projects/<project-id>/memory/`. Callers cannot supply an arbitrary vault root. Every ingest, correction, lifecycle change, maintenance run, reconciliation, and search requires the same project, agent, and session to hold the active unexpired lease.

A correction is appended as a candidate with an explicit `supersedes` link. Candidate and validated corrections remain non-retrievable and cannot hide the currently certified record. Supersession becomes authoritative only when the correction reaches `certified` or `trusted`; derived indexes are then rebuilt from canonical records.

The memory lock at `.memory-control/vault.lock` serializes append, lifecycle transition, and index publication across processes. It is preserved as control metadata rather than deleted after release.
