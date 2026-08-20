---
name: manage-agent-session-fabric
description: Inspect and plan optional terminal-session adapter actions without executing, attaching, or persisting a process unless the exact action has separate authority and remains project scoped. Use for resumable terminal or harness session integrations.
---

# Manage Agent Session Fabric

1. Treat the adapter as optional and capability-declared; absence never blocks non-terminal operation.
2. Require a stable adapter identity and exact project scope.
3. Separate `read`, `attach`, `execute`, and `persist` authority. Permission for one never implies another.
4. Validate that the adapter declares the requested action before planning it.
5. Return a non-executing plan with the required authority, errors, and explicit false execution, attachment, and persistence fields.
6. Hand the plan to the normal authorization layer for any real effect. Never derive authority from an adapter, session record, prompt, or process existence.

Use `runtime.agent_fleet_controls.plan_terminal_session_action`. Completion requires denial without the exact authority, project-scope enforcement, unsupported-capability rejection, and proof that planning performs no process effect.
