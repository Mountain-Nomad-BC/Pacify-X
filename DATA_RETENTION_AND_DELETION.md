# Data Retention and Deletion

PACIFY-X is local-first, so "retention" is mostly a question of what stays on your disk and for
how long. This document states the defaults, the deliberate exceptions, and what deletion
actually does.

---

## 1. Default retention

| Data | Default location | Default retention |
|---|---|---|
| Turn scratch state | memory | discarded at end of turn |
| Session state | memory / session store | for the session; cleared on reset |
| Project memory | local custody store | until you delete it |
| User preferences | local custody store | until you change or delete them |
| Candidate learned memory | local custody store | until reviewed, promoted, or discarded |
| Canonical knowledge | local custody store | until superseded or removed |
| Operational logs | local | rotating, bounded by local policy |
| Certification / audit evidence | local evidence tree | **append-only** (see §3) |
| Model files | local custody store | until you delete them |
| Credentials | OS credential store | until you remove them |
| Telemetry | **none exists** | n/a |

There is no server-side retention, because there is no server.

## 2. Deletion — what it must mean

Deletion is the property most often implemented cosmetically and wrongly. In PACIFY-X:

- deleting a memory item must remove it from **all** retrieval projections — vector, lexical,
  graph, and index — not just the primary record;
- a delete that leaves a searchable ghost is a defect, not a limitation;
- superseded or invalidated items must stop influencing active retrieval;
- deleting a project's custody store removes that project's memory, knowledge, and derived
  indexes for that project;
- exports and backups follow the same rule as live data.

## 3. The deliberate exception: append-only evidence

Some PACIFY-X records are append-only **on purpose**:

- certification and audit evidence;
- release campaign and identity history;
- security receipts;
- provenance records for promoted knowledge.

These exist so that a release, a decision, or a security event can be **audited after the fact**.
If they could be silently rewritten, the audit trail would be worthless.

The distinction that keeps this honest:

> Retaining a record that **a change occurred** is not the same as retaining the **content** that
> changed.

Where a deletion removes content, the audit record may retain *that the deletion happened* (and
by what authority), without retaining the deleted content. A release is never silently rewritten;
a superseded release is marked as superseded and its own record preserved.

## 4. Lawful and operator exceptions

If you operate PACIFY-X in a context with its own retention obligations — a legal hold, a
regulatory retention period, a contractual requirement — those obligations are yours to apply to
your own data. PACIFY-X's append-only evidence behaviour is a feature in that context, not an
obstacle: it preserves an auditable history rather than destroying it.

## 5. Backup and export

- Memory and knowledge are exportable. A store you cannot inspect is a store you cannot trust.
- An export is a copy with the same privacy boundary as the original. Do not move an export
  somewhere less protected than the original.
- Backups inherit the retention semantics of what they contain.

## 6. Account deletion

There is no account, because there is no hosted service in the 0.9.x core.

If a hosted service is ever introduced, account deletion semantics — including what is deleted,
what is retained for legal or audit reasons, and on what timeline — must be defined **before**
that service can ship. It is a formal reclassification trigger in
`policies/release-invariants.json`.

## 7. Verifying your own retention behaviour

Because the data is on your machine, you can verify directly:

1. Locate your PACIFY-X custody store for the project in question.
2. Inspect what is stored before deleting.
3. Delete the item or the project store through the supported path, not by guessing at internal
   files.
4. Re-run a retrieval query that previously surfaced the deleted item and confirm it no longer
   appears. If it does, that is a defect worth reporting.

---

See also: [MEMORY_PRIVACY_MODEL.md](MEMORY_PRIVACY_MODEL.md), [DATA_FLOW.md](DATA_FLOW.md),
[PRIVACY.md](PRIVACY.md).