# Team Fabric integration

The supplied v0.2.0 pack was inventoried in full: 78 files / 147,147 bytes, 76 text scans, two hashed non-text files, zero exclusions, and zero read errors. Its path-bearing raw audit is retained outside the VSIX; the sanitized source disposition receipt is `evidence/team-fabric-integration-dispositions.json` in the Pacify-X source.

Pacify-X 0.4 merges the pack into the existing coordination owner:

- attributed, hash-linked project events;
- exclusive/shared/informational claims;
- local/speculative authority and an explicit unimplemented Team Hub boundary;
- monotonic per-target fencing tokens, renewal, expiry, stale replay rejection, release, and receipts;
- goal, scope, effect, acceptance, usage, and budget fields in portable task envelopes;
- durable hard stops and ordered stop diagnostics;
- derived WorkRooms that cannot grant engineering authority;
- worker adapter doctor records with executor/authentication/billing separation;
- Agent Companies-style package inventory, hashes, collision policies, and non-canonical staging;
- `px-lean-engineering` and `px-work-stop-diagnostics` skills/orchestrations.

Team Hub, Buzz, and ACP remain explicit inactive adapters. No server is started, no external account is configured, and no billable API is enabled. Automatic worktree creation is also deferred because the current extension intentionally has no Git mutation authority; task envelopes already carry worktree/branch fields for a future Git-owned adapter.
