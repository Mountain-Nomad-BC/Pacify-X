---
name: px-debug-repair
description: Query PX for diagnosis, tracing, failure correlation, recovery, repair, retry, and stop-condition capabilities. Use for defects, incidents, slowdowns, conflicts, or broken environments.
---

# Route debugging and repair

Run `python -m runtime.cli --root . skill-query --goal "diagnose trace failure conflict slowdown repair recovery <task>"`. Inspect at most three admitted candidates, choose the narrowest owner, and hydrate exactly one.

Diagnose before mutating and keep rollback evidence for repairs.
