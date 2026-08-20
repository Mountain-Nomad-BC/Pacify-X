---
name: query-project-map
description: Search a PACIFY-X project intelligence map, produce a minimal source hydration plan, and calculate bounded upstream/downstream symbol impact. Use before exploring an unfamiliar project, locating implementation ownership, tracing behavior, planning or editing symbols, debugging, replacing GitNexus-style blast-radius checks, or answering architecture questions.
---

# Query Project Map

1. Confirm a valid project map exists; build or refresh it if absent or stale.
2. Run `scripts/query_project_map.py <project-root> "<question>"`.
3. Read ranked metadata results first.
4. Load only the returned file ranges, in priority order.
5. Expand one relation depth at a time only when evidence remains insufficient.
6. Never treat a lexical match as proof of runtime behavior; follow dependency, call, contract, and traceability edges.
7. Report unknowns and unresolved relationships explicitly.

## Impact before edits

1. Run `python -m runtime.cli project-map impact --project <project-root> --target "<path::qualname>" --direction upstream` before changing a function, class, method, or file.
2. Stop and warn the user when risk is high or critical.
3. Treat truncation or stale-map output as blocking, not as a low-risk result.
4. Review affected routes, contracts, tests, services, files, and symbols before editing.
5. Refresh and diff the map after accepted changes; retain both impact and diff receipts.
