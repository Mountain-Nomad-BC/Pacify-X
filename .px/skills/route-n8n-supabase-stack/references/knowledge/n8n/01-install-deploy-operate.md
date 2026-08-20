
# n8n install, deploy, and operate

## Safe installation sequence

1. Decide Cloud, Docker, or npm.
2. Confirm current version support and pin the release or image digest.
3. Establish durable database/state and a stable encryption key before creating credentials.
4. Keep the service private until editor URL, webhook URL, ingress headers, TLS, and authentication are commissioned.
5. Run a non-destructive workflow and restart/recreate test.
6. Back up and restore before production exposure.

A workflow export is not a complete backup. Recovery may require the database, encryption key, configuration, binary data, custom/community node packages, and external-secret references.

## Queue mode

Use queue mode when measured concurrency, duration, or isolation warrants it. All main, worker, webhook, and runner components need compatible configuration, Postgres, Redis, encryption keys, and distributed binary-data handling. Test worker loss, retry duplication, database/Redis pressure, graceful drain, and downstream rate limits.

## Operations

Observe process health, queue age, execution rate/error/duration, Postgres/Redis saturation, credential expiry, storage growth, and business outcomes. Bound retention and redact execution data.
