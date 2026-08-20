# PX Runtime Efficiency Operationalization

## Source and decision record

- Source: externally supplied `PX_RUNTIME_EFFICIENCY_AND_BOUNDED_WORK_ARCHITECTURE.md` (host path intentionally omitted)
- Source SHA-256: `A10387FF1540117AF78FD7D742D33F3052CAA21E79C5989E8D65F68E493C7580`
- Intake date: 2026-08-11
- Disposition: adopted selectively through measured, reversible tracer bullets. The supplied document is research input, not authority. Pacify-X invariants, current contracts, and test evidence remain authoritative.

## Operationalization canvas

| Source mechanism | Current target | Implemented tracer | Promotion gate | Rollback/fallback |
|---|---|---|---|---|
| Single-flight execution | Extension dashboard/catalog/graph bridge | Equivalent requests share one promise keyed by canonical inputs | Ten equivalent requests execute once and report nine joins | Disable governor use; retain existing direct bridge call |
| Bounded concurrency and backpressure | Extension interactive/background/validation pools | Per-pool concurrency and queue limits with explicit rejection | Queue never exceeds configured limit under hostile burst | Direct serial execution with visible degraded state |
| Cancellation and supersession | Rapid graph and snapshot refreshes | Abort obsolete queued/running work through owned process-tree termination | Superseded work exits and leaves no child process | Allow current request to finish; discard obsolete result |
| Circuit breaker | Python dashboard dependency | Three correlated failures open a 30-second quiet circuit; half-open probe closes on success | Failure storm produces bounded probes and visible circuit state | Manual refresh after cooldown; disconnected projection |
| Source-aware L1 cache | Canonical dashboard snapshot | Explicit bounded source set, nanosecond metadata revisions, content hashes for small control files | Watched changes invalidate; unrelated changes do not | Cold snapshot from canonical Python authority |
| Verified persistent metadata cache | Restart-safe informational dashboard state | Host-owned global-state record with schema, producer, source fingerprint, dependency revisions, freshness class, validation time, and corruption rejection | Matching restart restores without Python execution; mismatch/corruption produces a miss | Cold snapshot from canonical Python authority |
| Stale-while-revalidate | Informational dashboard/sidebar data only | Expired unchanged snapshots render immediately while one refresh runs | UI stays responsive and refresh is single-flight | Blocking refresh when no safe cached projection exists |
| Fresh authority for effects | Validation, mutation, cleanup, certification | Cache is not used as proof for state-changing or certification actions | Every effect path performs fresh pre-action checks | Fail closed; no mutation |
| Visibility-aware work | Dashboard and sidebar | Event/revision updates are primary; a five-minute fallback runs only while a surface is visible and hidden webviews are not retained | Hidden/idle runtime produces no refresh storm | Explicit manual refresh |
| Worker-owned filesystem projection | Environment and Team Fabric inventory | Bounded worker threads own recursive discovery and package hashing; cleanup traversal is cancellable async I/O | Main event loop remains responsive and all workers terminate on completion, abort, or deadline | Bounded serial scan with fail-closed timeout |
| Shared diagnostics | Extension observability command and snapshot | Cache age/status, invalidation reason, pool depth, joins, rejections, cancellations, circuits | Diagnostics explain why work ran or was skipped | Listener health and disconnected reason remain available |
| Hardware-aware bounded routing | Python runtime hardware router | Optional accelerator probes are time-bounded and remain subordinate to CPU-authoritative safety | Provider/device/VRAM/correctness/fallback evidence passes | Deterministic CPU route with explicit reason |

## Freshness classes

| Class | Examples | Reuse policy |
|---|---|---|
| Immutable/content-addressed | Frozen artifacts and exact VSIX hashes | Reuse by verified digest |
| Stable | Registry projections and capability catalogs | Reuse until source revision changes |
| Dynamic | Coordination, provider ledger, active execution | Short TTL plus event-triggered invalidation |
| Sensor | CPU/GPU temperatures, utilization, process state | Sample on demand or through one shared bounded sampler |
| Critical/authoritative | Cleanup target, approval, certification, destructive eligibility | Never authorize from stale cache; revalidate immediately |

## Evidence and experiment matrix

| Experiment | Required observation | Status |
|---|---|---|
| Duplicate refresh coalescing | 1 execution, 9 joins | Automated extension test passing |
| Targeted invalidation | Unwatched file leaves fingerprint stable; watched control file changes it | Automated extension test passing |
| Queue boundedness | Excess work rejects without queue growth | Automated extension test passing |
| Supersession | Obsolete work aborts and increments supersession telemetry | Automated extension test passing |
| Circuit behavior | Open, quiet cooldown, half-open success, close | Automated extension test passing |
| Source cache/SWR | Hit, stale informational response, one refresh, source-change miss | Automated extension test passing |
| Hidden-panel efficiency | No periodic refresh when dashboard is hidden | Source/load tests passing; long-idle installed measurement remains part of R08 |
| Persistent restart and corruption | Exact fingerprint restores; mismatch/corruption cold-misses | Automated extension tests passing |
| Work deadlines and resources | Deadline abort plus queue/operation latency, RSS, heap, event-loop utilization, active-resource telemetry | Automated extension tests passing |
| Process lifecycle cleanup | No listener/test-host orphan or duplicate host | Exact installed `0.5.4` host passed with verified process-tree closure and zero residual owned PIDs |
| GPU/CPU route truth | Selected backend equals executable provider/device evidence | CPU/no-provider path and simulated eligible-device gates pass; real CUDA promotion remains open because this host exposes no ready executor |
| Full runtime and exact artifact certification | Mandated tests, clean-profile installed VSIX, hashes, audit bundle | Exact VSIX lane passed; repository-wide Python gate and cross-platform/perceptual release lanes remain separate |

## Remaining certification mechanisms

- Persistent metadata is implemented only for informational dashboard projections. It is not authority for validation, mutation, cleanup, approval, or certification.
- Broad recursive watchers remain intentionally absent. Exact revision sources and existing canonical event coverage are used with a five-minute visible-only fallback.
- Installed-host hidden-idle, restart, and load measurements remain required before release certification.
- GPU acceleration is never applied to filesystem, database, serialization, cleanup-safety, or destructive decisions.

## Acceptance boundary

This architecture is complete only when duplicate work is coalesced, queues and processes are bounded, hidden surfaces become quiet, event-triggered changes refresh the correct projections, authoritative actions revalidate fresh state, diagnostics expose cache/governor/device decisions, and the exact packaged artifact passes lifecycle, restart, corruption, load, UI, and accessibility audits.
