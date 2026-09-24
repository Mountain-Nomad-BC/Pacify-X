# DSAR Process (Data Subject Access Requests)

**Current status: NOT CURRENTLY APPLICABLE.**

A DSAR process is a procedure for a service operator to answer requests from data subjects about
personal data it holds. Pacify-X operates no service and holds no user data, so there is nothing
to request and no queue to run.

---

## Why not simply skip it

Because "we have no DSAR process" and "we have no data" are different claims, and only the second
one is true. This document records *why* it does not apply, so a future reviewer does not have to
guess whether it was overlooked or deliberately deferred.

## What is true today

| Item | Value |
|---|---|
| Personal data held by Pacify-X | none |
| Accounts | none |
| Hosted storage | none |
| Request intake service | none |
| Data subject on a Pacify-X system | none — there is no Pacify-X system holding user data |

If a user wants to exercise a data-protection right over data **PACIFY-X produced on their own
machine** (memory, knowledge, logs, evidence), that data is under their direct control. The
process is local:

| Right | Local operation |
|---|---|
| Access | inspect the custody store |
| Rectification | edit or supersede the record |
| Erasure | delete the item or the project store; deletion must clear all projections |
| Portability | export memory and knowledge |
| Restriction / objection | disable the feature |

See [DATA_RETENTION_AND_DELETION.md](../../DATA_RETENTION_AND_DELETION.md) and
[MEMORY_PRIVACY_MODEL.md](../../MEMORY_PRIVACY_MODEL.md).

## What a future DSAR process would require

If a hosted service processing personal data is introduced, this document is replaced with a real
process covering:

1. **Intake** — a published, monitored address or form.
2. **Verification** — establishing the requester is the data subject.
3. **Scope** — locating all data across stores, logs, backups, and derived indexes.
4. **Fulfilment** — access, rectification, erasure, portability, or restriction.
5. **Timeline** — a stated response deadline consistent with the applicable regime.
6. **Evidence** — a record of each request and how it was answered.
7. **Exceptions** — legal-hold and retention obligations, with the basis recorded.
8. **Sub-processor propagation** — a request that must reach a subprocessor.

None of these can be implemented honestly until the service exists.

## Trigger

Introducing a hosted service that processes personal data. Recorded as a reclassification trigger
in `policies/release-invariants.json` and as a hosted-only row in the
[applicability matrix](../compliance/REGULATORY_APPLICABILITY_MATRIX.md) §E.