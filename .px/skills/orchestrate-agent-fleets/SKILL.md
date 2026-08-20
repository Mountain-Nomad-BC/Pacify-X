---
name: orchestrate-agent-fleets
description: Evaluate and coordinate a bounded project-scoped agent fleet with stable identity, explicit permissions and ownership, heartbeat freshness, cost caps, an isolated bounded inbox, and fail-closed cross-project checks. Use before activating or continuing multi-agent work.
---

# Orchestrate Agent Fleets

1. Require a stable agent identity, accountable owner, exact project identity, declared permissions, fresh heartbeat, and reserved cost for every participant.
2. Reject duplicate identities, stale heartbeats, missing owners or permissions, and any cross-project participant.
3. Sum reserved cost before activation and reject the whole fleet when the cap is exceeded.
4. Admit inbox messages only from allowed senders into the exact project namespace.
5. Bound inbox record count and encoded bytes; reject duplicate message identities and overflow.
6. Route and hydrate specialist bodies only after readiness passes. Readiness itself never grants tool, write, network, or process authority.
7. Recheck readiness after a heartbeat, ownership, permission, membership, or budget change.

Use `runtime.agent_fleet_controls.evaluate_fleet_readiness` and `admit_inbox_message`. Require positive, stale-heartbeat, cost-overflow, duplicate-identity, and cross-project tests.
