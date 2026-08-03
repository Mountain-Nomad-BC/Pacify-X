---
name: run-resilience-drills
description: Plan and execute approval-gated fault, restart, dependency-loss, latency, load, and recovery experiments with before/during/after probes and recovery-time evidence. Use for chaos testing, resilience certification, soak recovery, restore drills, or validating degraded-mode and failover claims.
---

# Run Resilience Drills

1. Declare services, assets, dependencies, fault scenarios, resource/load ceilings, recovery objectives, and forbidden targets.
2. Require a disposable or explicitly authorized environment and specific approval for each fault effect.
3. Capture pre-state health, data invariants, resource baseline, and recovery material.
4. Apply one bounded fault with an automatic timeout and independent stop control.
5. Measure during-fault behavior, error truthfulness, isolation, backpressure, latency, and resource use.
6. Remove the fault and verify service, data, queue, and dependency recovery against objectives.
7. Preserve before/during/after evidence and distinguish executed, simulated, blocked, and described-only scenarios.
8. Stop immediately on scope escape, data-risk escalation, control loss, or exhausted recovery budget.

Never run a fault because a report template lists it. Execution authority and evidence are separate contracts.
