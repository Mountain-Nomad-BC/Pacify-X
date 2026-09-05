# Execution Plan

Execute the hash-bound cohesion-closure DAG in dependency order.

## Active wave

Wave 0 audit/adjudication is closed. Finish the fresh-map-expanded downstream cone for `PX-ASSURE-001`; `PX-ASSURE-002`, `PX-CORE-001`, `PX-CORE-002`, and the read/disposable portion of `PX-LEDGER-001` remain available only under the same admitted denominator and exact work guard.

## Later waves

Follow `.engineering-bootstrap/punch-cards/cohesion-closure-20260904/dag.json`. Dependency order is authoritative even when a prerequisite crosses a numbered wave. Implement one root at a time, reuse the registered canonical primitive, and update card status/evidence only from observable results.

For every change: classify it, compute direct/transitive consumers, invalidate stale projections/evidence, run focused and negative tests, run affected downstream tests, run affected governed sections once, inspect resources/disk, then advance to `focused_green` and `downstream_green` as earned.

## Resume contract

On resume, verify the denominator/card hashes, repository drift, active admission/checkpoint, processing order, resources, and current card evidence before continuing. Final85 is terminal and must never be resumed.
