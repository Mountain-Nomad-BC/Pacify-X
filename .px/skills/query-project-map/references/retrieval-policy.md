# Retrieval policy

Use metadata before source. Prefer exact title/path matches, then BM25 metadata matches, then bounded relation expansion. Limit initial hydration to eight files and merge overlapping line ranges. Source content is authoritative over map summaries when they disagree; disagreement makes the map stale or incorrect and must trigger refresh or repair.
