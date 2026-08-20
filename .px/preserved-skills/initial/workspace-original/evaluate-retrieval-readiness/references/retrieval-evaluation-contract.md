# Retrieval evaluation contract

Version the corpus snapshot, parser, chunker, embedding model, index, ranking policy, filters, fixture set, and thresholds. Preserve hashes and source IDs rather than copying source bodies into evidence.

Each case needs a stable ID, at least one relevant source ID, optional forbidden source IDs, and an explanation of why the judgment applies. Include exact lookup, broad discovery, ambiguous language, stale content, unauthorized content, empty results, and adversarial filtering cases.

Activation requires complete case coverage, declared recall and reciprocal-rank thresholds, zero forbidden exposure, current source lineage, and a rebuild/rollback procedure. Latency is reported independently; speed cannot compensate for unsafe or irrelevant results.
