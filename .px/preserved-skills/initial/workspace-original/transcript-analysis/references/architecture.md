# Transcript evidence architecture

The governed sequence is:

`raw transcript -> immutable source hash -> lifecycle separation -> initial mapping -> queue terminology normalization -> semantic replay -> evidence/action/outcome extraction -> canonical records -> validation -> bounded export`

Reusable layers own provenance, lifecycle state, evidence state, action/outcome separation, source spans, schemas, and validation. Queue adapters own product aliases, component ontologies, alert registries, diagnostic thresholds, flow policies, and any root-cause or completed-resolution inference.

An adapter is never allowed to transfer queue-owned rules merely because terms look similar. Record an explicit reviewed transfer with source queue, term, reviewer, and evidence first.
