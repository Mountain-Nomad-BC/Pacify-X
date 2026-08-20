# Sol + PACIFY-X: 12-task matched benchmark

> **Closeout status (2026-08-08): integration-invalid; retained for diagnosis only.** The PACIFY-X arm attached prompt-layer skill files rather than activating PACIFY-X's canonical runtime integration. The two subsequently audited routing/harness skills explicitly identify themselves as candidate/inactive pending admission. Therefore, this run must not be used to characterize fully integrated PACIFY-X performance. Its raw outcomes remain useful only as evidence of the flawed treatment.

## Outcome

On this one-attempt, 12-task Terminal-Bench 2.1 sample, the prompt-layer treatment reduced Sol's official pass rate from **83.33% (10/12)** to **75.00% (9/12)**: **-8.33 percentage points**, or **-10.0% relative**. This is not a valid measurement of fully integrated PACIFY-X.

The treatment did reduce aggregate agent execution time by 500.4 seconds (21.3%) and input tokens by 1,358,724 (32.7%). It increased tool calls by 26 (20.6%). Because there was one attempt per task, these are directional results, not a statistical significance claim.

| Metric | Control Sol | Sol + PACIFY-X | Delta |
|---|---:|---:|---:|
| Official passes | 10/12 | 9/12 | -1 |
| Official pass rate | 83.33% | 75.00% | -8.33 pp |
| Aggregate agent time | 2,352.3 s | 1,851.9 s | -500.4 s |
| Input tokens | 4,152,858 | 2,794,134 | -1,358,724 |
| Output tokens | 67,354 | 63,708 | -3,646 |
| Tool calls | 126 | 152 | +26 |
| Infrastructure errors | 0 | 0 | 0 |
| Retries | 0 | 0 | 0 |

## Per-task official verifier scores

| Task | Control | PACIFY-X | Result |
|---|---:|---:|---|
| adaptive-rejection-sampler | 1 | 1 | common pass |
| build-cython-ext | 1 | 1 | common pass |
| cancel-async-tasks | 1 | 1 | common pass |
| fix-code-vulnerability | 1 | 1 | common pass |
| fix-git | 1 | 1 | common pass |
| kv-store-grpc | 0 | 0 | common failure |
| largest-eigenval | 1 | 1 | common pass |
| log-summary-date-ranges | 1 | 0 | PACIFY-X regression |
| nginx-request-logging | 1 | 1 | common pass |
| openssl-selfsigned-cert | 1 | 1 | common pass |
| pytorch-model-recovery | 0 | 0 | common failure |
| write-compressor | 1 | 1 | common pass |

## Failure classification

- `log-summary-date-ranges` — PACIFY-X validation failure (0.95 confidence). Control inspected the sample format and counted exact bracketed severity labels. The PACIFY-X treatment used a broader token matcher, producing `today,ERROR,414` instead of `370`. Its single verification command then failed with an AWK variable error, but the circuit-breaker budget caused it to stop and submit anyway.
- `kv-store-grpc` — common implementation failure (0.98 confidence). Both arms passed 5/7 tests, but no server remained listening on port 5328, so the functional RPC check was refused.
- `pytorch-model-recovery` — common implementation failure (0.98 confidence). Both arms passed 4/5 tests, but the recovered TorchScript model accepted only `src`; the verifier called it with `src` and `tgt`.

## Treatment and controls

Both arms used the official Terminal-Bench 2.1 tasks and verifier, `gpt-5.6-sol`, high reasoning, Codex 0.147.0, one attempt, no retries, and web search disabled. The PACIFY-X arm attached only the benchmark-relevant skills:

- `benchmark-and-route-agents`
- `evaluation-budget-allocator`
- `tool-loop-circuit-breaker`

The oracle-heavy verification-lab workflow was deliberately excluded. PACIFY-X profile freeze and matched-comparison preflight both passed before execution. The dataset subset hash is `877715d907a8c65397fd53ad7be906f41ab20b28cee4061db3d66abbe8feeab4`; the treatment hash is `b68ccd5d46101309bea350215fe17de17b2778316671452bebe38922199b7bfc`.

## Interpretation and limits

This treatment made Sol cheaper in input tokens and faster in aggregate agent time, but less accurate. The direct failure trace shows why: the bounded verification policy was too aggressive to recover from a failed check. There is no evidence in this sample that the current PACIFY-X treatment improves benchmark capability.

Harbor emitted a non-fatal Windows `cp1252` trajectory-conversion warning after trials. Official verifier rewards and raw Codex usage logs remained intact; Harbor's normalized aggregate cost fields were unavailable. Jobs ran concurrently, so the aggregate per-task agent times above are more useful than whole-job completion time. No significance claim is made at `n=12`, one attempt per arm.

## Evidence

- `matched-summary.json` — scored aggregate and deltas
- `custody.json` — PACIFY-X custody record and SHA-256 hashes
- `control-profile.json` and `pacify-profile.json` — frozen matched profiles
- `PACIFY_TREATMENT.md` — exact treatment instructions
- `preflight-checks.json` — comparability checks
- Raw Harbor job custody is represented by the content-addressed hashes in `custody.json`; the original machine-local temporary locator was removed from this portable report under `portability-repair.json`.
