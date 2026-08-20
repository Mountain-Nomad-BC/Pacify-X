# API, async, and retry repairs

## Diagnose

- Reproduce request lifespan, dependency injection, cancellation, timeout, and cleanup behavior.
- Distinguish transient transport failures from validation, authorization, and invariant failures.
- Treat swallowed cancellation, blocking calls in async paths, and unbounded task creation as root causes.

## Repair

- Keep application lifespan and resource ownership explicit.
- Propagate cancellation; bound concurrency, timeouts, attempts, and jittered backoff.
- Retry only classified transient failures and only when the operation is idempotent.

## Prove and roll back

- Test success, timeout, cancellation, exhausted retry, non-retryable failure, and cleanup.
- Record retry count and bounded elapsed time without secrets.
- Roll back the narrow call path or configuration flag; never mask a failing dependency.

Lineage: generalized engineering corpus patterns; locally revalidated before use.
