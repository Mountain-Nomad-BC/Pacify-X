# External memory provider certification

An external memory provider is disabled by default and is never canonical. Certification requires a distinct absolute root, database namespace, index namespace, and process namespace for each project; shared private-memory processes are forbidden.

Run negative tests proving project A cannot read, write, retrieve, log, prompt, or expose project B. Explicitly test any provider feature described as a global slot or cross-agent share. Verify actor attribution survives every write/action path. Backend failures must propagate as errors rather than empty results.

Bound graph extraction, summarization, search, and index maintenance with item/byte/token limits, deadlines, checkpoints, circuit breakers, and bulkheads. Session-end compilation must be distinct from per-turn checkpoints.

Correction certification must rebuild or invalidate embeddings, graph edges, caches, summaries, and transfers, then demonstrate the superseded claim cannot influence retrieval.

