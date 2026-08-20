---
name: architecture-deepening-audit
description: Find shallow abstractions, leakage, duplication, and misplaced seams, then rank deepening opportunities.
---

# Architecture Deepening Audit

Use project maps, imports, call graphs, duplication, and change history. Identify clusters where callers repeatedly coordinate the same knowledge.

For each opportunity report:
- current interface burden and leaked knowledge;
- repeated behavior and affected callers;
- proposed seam and hidden complexity;
- deletion-test result;
- migration path and blast radius;
- proof strategy;
- confidence and contrary evidence.

Rank by leverage × locality gain × change frequency, discounted by migration risk. Do not recommend abstraction merely because code looks similar.
