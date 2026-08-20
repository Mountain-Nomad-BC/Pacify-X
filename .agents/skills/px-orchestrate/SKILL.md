---
name: px-orchestrate
description: Query PX for bounded orchestration, agent routing, scheduling, handoff, claims, recovery, and distributed-work capabilities. Use when work spans multiple dependent operations or actors.
---

# Route orchestration work

Run `python -m runtime.cli --root . skill-query --goal "orchestrate schedule route claims handoff recovery <task>"`. Compare at most three admitted metadata candidates, hydrate exactly one, and retain its effect and dependency gates.

Do not start a second executor or agent authority merely because a capability is visible.
