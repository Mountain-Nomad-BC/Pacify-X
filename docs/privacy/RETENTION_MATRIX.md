# Retention Matrix

Table form of [DATA_RETENTION_AND_DELETION.md](../../DATA_RETENTION_AND_DELETION.md).

| Data | Storage | Default retention | Deletion behaviour | Append-only? |
|---|---|---|---|---|
| Turn scratch state | memory | end of turn | discarded automatically | no |
| Session state | session store | session lifetime | cleared on reset | no |
| Project memory | local custody | until deleted | must clear vector/lexical/graph/index projections | no |
| User preferences | local custody | until changed | removed on delete | no |
| Candidate learned memory | local custody | until reviewed | discarded or promoted | no |
| Canonical knowledge | local custody | until superseded | supersede, then remove | supersedes recorded |
| Operational logs | local | rotation policy | rotate/delete locally | no |
| Certification evidence | local evidence tree | **indefinite** | preserved by design | **yes** |
| Release campaign / identity history | local | **indefinite** | preserved by design | **yes** |
| Security receipts | local | **indefinite** | preserved by design | **yes** |
| Provenance for promoted knowledge | local | **indefinite** | preserved by design | **yes** |
| Model files | local custody | until deleted | removed on delete | no |
| Credentials | OS credential store | until removed | removed via OS | no |
| Telemetry | — | **none exists** | n/a | n/a |
| Hosted/account data | — | **does not exist** | n/a | n/a |

## The distinction that keeps the append-only rows honest

> Retaining a record that **a change occurred** is not the same as retaining the **content** that
> changed.

Where a deletion removes content, the audit record may retain *that the deletion happened* and by
what authority, without retaining the deleted content.

## Hosted-only rows (recorded, not implemented)

| Data | Trigger | Status |
|---|---|---|
| Hosted memory | hosted service | NOT_APPLICABLE |
| Account records | accounts | NOT_APPLICABLE |
| Billing records | paid service | NOT_APPLICABLE |
| Hosted logs | hosted service | NOT_APPLICABLE |
| Backup snapshots | hosted service | NOT_APPLICABLE |
| Support uploads | support intake | NOT_APPLICABLE |

Each requires a retention schedule **before** the corresponding service ships. Creating them now
would describe a service that does not exist.

## Deletion completeness — the property that matters
A delete is only correct if the item is gone from **every** projection that could surface it:
primary record, vector index, lexical index, graph, and any derived cache. A delete that leaves a
searchable ghost is a **defect**, and should be reported as one.

Verify your own: delete an item through the supported path, then re-run a retrieval query that
previously surfaced it. If it still appears, that is a defect.