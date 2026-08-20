
# n8n workflow engineering

Treat each workflow as executable production software.

Define:
- trigger and input schema;
- required outcome;
- irreversible side effects;
- concurrency and deduplication;
- retryable versus permanent failure;
- compensation or reconciliation;
- owner, alert, and runbook.

Normalize inputs early. Use intent-revealing node names and stable sub-workflow contracts. Keep expressions short and visible. A Code node is justified when code is clearer than the equivalent node maze, not merely because it is familiar.

Test normal, empty, malformed, duplicate, timeout, rate-limit, credential-expiry, partial-completion, and replay cases. Verify the downstream state, not just the cheerful green execution badge.
