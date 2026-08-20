---
name: long-horizon-progress-ledger
description: Manage long-running goals as project-scoped state machines with continuation budgets, isolated pause and resume, acceptance-backed completion, repeated-evidence blocked semantics, and durable evidence history. Use when work spans sessions, agents, or bounded continuation turns.
---

# Long-Horizon Progress Ledger

1. Bind the goal to one project and stable goal identity.
2. Start, continue, pause, resume, block, or complete only through an explicit transition.
3. Charge every continuation against the declared budget and stop before it becomes negative.
4. Keep paused state bound to its owning session unless a governed handoff transfers it.
5. Mark blocked only after the same blocker is observed three consecutive times.
6. Mark complete only when every acceptance criterion passes and current evidence identities are present.
7. Retain transition history and a deterministic state hash; do not infer progress from activity or file existence.

Use `runtime.durable_state.transition_durable_goal`. The runtime is side-effect-free and grants no authority; persistence requires the project control plane and a separate approved write.
