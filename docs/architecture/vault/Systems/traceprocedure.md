---
canonical_id: "traceprocedure"
kind: system
layer: execution
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Active trace-to-skill capture procedure

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Directs the host to normalize successful and failed trajectories into the engineering-process contract, invoke process compile, inspect invariants and prepare tests before separate admission.

## Historical source state

Host-prepared traces, normalized process record, declared tests and inert candidate output.

## Limits and unknowns

This active package supplies a documented producer procedure. It does not establish an automatic background trace collector or autonomously generated test suite.

## Historical suggested evolution

A host following this procedure can create a reviewed reusable candidate from prior work.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1500]] — same-file-bytes
- [[Evidence/S236]] — same-file-bytes

## Directed relationships

- [[Systems/process]] — prescribes normalization and CLI compilation (`E249`)
