---
name: px-plan
description: Query PX for planning, decomposition, topology, decision, dependency, estimation, and long-horizon progress capabilities. Use when a task needs a durable or multi-stage plan.
---

# Route planning work

Run `python -m runtime.cli --root . skill-query --goal "plan decompose dependencies topology decisions progress <task>"`. Select one of at most three admitted candidates and hydrate exactly that body.

Planning does not grant write, network, deployment, or destructive authority.
