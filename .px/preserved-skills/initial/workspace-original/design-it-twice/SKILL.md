---
name: design-it-twice
description: Generate and compare genuinely different interface designs before locking an important seam.
---

# Design It Twice

Use for expensive or high-fanout interfaces.

1. State the invariant behavior and constraints without prescribing the interface.
2. Produce at least three independent designs with different organizing ideas—not renamed versions of one design.
3. For each, show caller examples, error model, state ownership, extension path, test seam, and migration cost.
4. Score depth, locality, cognitive load, invalid-state prevention, observability, and reversibility.
5. Attempt a hostile use case against each design.
6. Select or synthesize only after comparison; record rejected alternatives and why.

Do not parallelize designs that share a hidden template. Diversity is the point.
