# Deferred findings

No unrelated implementation defect was discovered that needed to be smuggled into this repair.

Two external completion events remain intentionally deferred:

1. The public CI matrix must execute after the repair is pushed to `main`.
2. The new bytes and durable evidence-custody assets require a future authorized signed release. The immutable v0.6.3 tag and its historical certificate are not rewritten.
