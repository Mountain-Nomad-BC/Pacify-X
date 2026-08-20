---
name: diagnose-python-repair
description: Diagnose and repair Python service, async, authorization, schema, retry, transaction, logging, subprocess, path, test-isolation, container-readiness, and evidence failures. Use when a Python defect needs a root-cause explanation, focused patch, negative tests, rollback, and sanitized proof.
---

# Diagnose Python Repair

1. Reproduce the symptom with the smallest focused test; do not patch from the error string alone.
2. Identify the canonical owner and classify the failure boundary: API/async, security/data, or runtime/validation.
3. Read only the matching reference below.
4. Record root cause and failed approaches before proposing a narrow repair.
5. Add positive, negative, and effect-boundary tests. Preserve an explicit rollback.
6. Emit sanitized evidence and leave unrelated architecture unchanged.

- API lifecycle, async cancellation, retries: [api-async-retries.md](references/api-async-retries.md)
- Authorization, schema drift, transactions, redaction: [security-data.md](references/security-data.md)
- Subprocess/path safety, isolation, containers, evidence: [runtime-validation.md](references/runtime-validation.md)
