# Pacify-X cohesion-closure punch cards

This directory is the durable 43-card implementation contract for the source-bound cohesion denominator. `dag.json` is the canonical dependency graph, and `SHA256SUMS` binds the current card projection.

Current progress: six audit cards are closed; 37 of 37 source/proof cards are downstream-green and 0 are closed. 0 source/proof cards remain before release admission.

Lifecycle: `planned -> admitted -> in_progress -> focused_green -> downstream_green -> closed`. A source/proof card can become closed only after the exact final100 installed-operational denominator passes without retry.

Every completion reference is content-hash-bound. Reconciliation is check-only unless `scripts/reconcile_cohesion_cards.py --apply` is invoked explicitly.
