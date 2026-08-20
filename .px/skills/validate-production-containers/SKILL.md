---
name: validate-production-containers
description: Validate production container images with isolated, temporary test harnesses while keeping test dependencies out of the shipped image and proving cleanup. Use for container-native integration tests, runtime import checks, health probes, or contract tests that must execute in the image environment.
---

# Validate Production Containers

1. Verify the image digest, target container, authorization, and expected immutable state.
2. Prefer starting a disposable sibling container from the same image.
3. Mount or copy a bounded harness into a unique temporary path; never overwrite application paths.
4. Use only dependencies already present unless an explicitly approved temporary tool directory is isolated from the image.
5. Run as the container user. Escalation requires a named reason and separate approval.
6. Capture command, exit status, logs, health, resource use, and assertions.
7. Remove the disposable container or temporary path through a recoverable/bounded cleanup action.
8. Compare pre/post filesystem, process, and application state and fail if residue remains.

Never modify or commit the production image during validation. Do not use broad recursive cleanup against an unresolved path.
