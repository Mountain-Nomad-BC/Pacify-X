---
name: query-project-map
description: Search a PACIFY-X project intelligence map and produce a minimal source hydration plan. Use before exploring an unfamiliar project, locating implementation ownership, tracing behavior, planning changes, debugging, or answering architecture questions.
---

# Query Project Map

1. Confirm a valid project map exists; build or refresh it if absent or stale.
2. Run `scripts/query_project_map.py <project-root> "<question>"`.
3. Read ranked metadata results first.
4. Load only the returned file ranges, in priority order.
5. Expand one relation depth at a time only when evidence remains insufficient.
6. Never treat a lexical match as proof of runtime behavior; follow dependency, call, contract, and traceability edges.
7. Report unknowns and unresolved relationships explicitly.
