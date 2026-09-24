# Memory Privacy Model

Persistent memory is the PACIFY-X feature most likely to accumulate information about **you**
rather than about your code. This document defines its boundaries so that accumulation is
deliberate rather than incidental.

---

## 1. What memory is, and what it is not

PACIFY-X memory is a **local, scoped, inspectable store** of operational facts, preferences, and
project context, used to make the assistant useful across sessions.

It is **not**:

- hidden reasoning capture (PACIFY-X does not capture chain-of-thought);
- a transcript archive;
- a shared public corpus;
- a substitute for canonical knowledge, which has its own admission process.

## 2. Scopes — never merged

| # | Scope | Lifetime | Purpose |
|---|---|---|---|
| 1 | Turn scratch | one turn | disposable working state |
| 2 | Session | one conversation/task | current context |
| 3 | Project | durable, project-bound | project-scoped operational facts and progress |
| 4 | User preference | durable, separately governed | explicit stable preferences |
| 5 | Candidate learned | until reviewed | observations awaiting promotion |
| 6 | Canonical knowledge | durable, admitted | validated reusable knowledge (not personal memory) |
| 7 | Evidence / archive | append-only by policy | immutable source and receipt history |

A failed model answer must never become canonical knowledge merely because it appeared in a
session transcript. A session summary preserves pointers and unresolved uncertainty rather than
compressing them into unsupported certainty.

## 3. The private/public boundary

- Memory is **local** by default and remains on your machine.
- Promoting memory into anything shareable is an explicit, policy-gated action, never a
  side effect of use.
- One project's memory does **not** leak into another project. Project scoping is a hard
  boundary, not a convention.
- Knowledge derived from a private source does not become public knowledge without passing a
  declassification gate.

## 4. Provenance

Memory records carry provenance: what produced them, when, and from which scope. Promotion
records why it happened. This is what makes a memory auditable rather than merely present.

## 5. Deletion and correctness semantics

The property that matters most: **deletion must be complete, not cosmetic.**

- Deleting a memory item must not leave retrievable remnants in vector, lexical, graph, or index
  projections. A delete that leaves a searchable ghost is a defect, not a limitation.
- Superseded or invalidated memory must stop influencing active retrieval.
- An append-only provenance/audit record may be retained by policy even after the content is
  removed; its retention semantics are stated in
  [DATA_RETENTION_AND_DELETION.md](DATA_RETENTION_AND_DELETION.md). Retaining a *record that a
  change occurred* is not the same as retaining the *content*, and the system must distinguish
  them.
- Backups and exports follow the same rule.

## 6. Export

Memory is exportable and inspectable. You can see what is stored and take it with you. A store
you cannot inspect is a store you cannot trust.

## 7. Access by models, plugins, and tools

- A model may **propose** a memory; it does not write canonical memory directly.
- Memory access is capability-bound: a component can reach only the scope it is granted.
- A plugin does not inherit all PACIFY-X authority merely because it is installed.
- Crossing a scope boundary is a governed action with a policy decision and a record.

## 8. Encryption

Memory at rest is protected by your operating system's disk protection. PACIFY-X does not claim
application-level encryption of the memory store, and does not represent the store as encrypted
in a compliance sense.

## 9. Hosted memory

There is no hosted memory in the 0.9.x core. Introducing one is a formal reclassification trigger
requiring a privacy/data-flow/compliance review before release, because it moves memory across
the boundary defined in [DATA_FLOW.md](DATA_FLOW.md).

## 10. What you should decide before enabling memory

1. Is this machine shared?
2. Does this project contain personal data?
3. How long should memory be retained?
4. Who else can read this machine's disk?
5. Do you want memory on for this project at all?

PACIFY-X's defaults are conservative. These are still your decisions, and this document exists so
they are informed ones.

---

See also: [PRIVACY.md](PRIVACY.md), [DATA_RETENTION_AND_DELETION.md](DATA_RETENTION_AND_DELETION.md),
[DATA_FLOW.md](DATA_FLOW.md).