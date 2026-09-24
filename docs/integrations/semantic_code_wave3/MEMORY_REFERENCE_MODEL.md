# Durable Memory Reference Model — Wave 4 Handoff

This document is a **design contract for Wave 4**, not a claim that memory relocation/reference code is installed in Wave 3.

## Identity

A durable reference should name memory identity rather than a storage path:

`pxmem://project-id/memory-id@record-revision`

The revision may be omitted only when the caller intentionally requests current identity.

## Location

Physical location remains separate metadata:

- memory ID
- project ID
- physical storage tier: hot / warm / cold / archive
- storage locator
- location revision
- record revision
- content/source SHA

Moving a memory must change only physical-location metadata. It must not silently rewrite semantic/governance layer, ACL, certification state, source SHA, memory type, or memory ID.

## Integrity behavior expected in Wave 4

- unresolved or stale identity is explicit
- project mismatch is explicit
- foreign-project references are rejected or surfaced according to authorization scope
- requested record revisions are verified
- exact legacy aliases may produce a deterministic rewrite plan
- fuzzy matches are suggestions only and are never auto-applied

Wave 3 keeps this model documented because its capability/mode contracts need a stable forward boundary, while the executable memory modules remain in the next wave.
