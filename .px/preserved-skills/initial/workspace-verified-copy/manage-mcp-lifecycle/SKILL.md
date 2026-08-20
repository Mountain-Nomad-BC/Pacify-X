---
name: manage-mcp-lifecycle
description: Discover, register, prioritize, probe, certify, disable, and recover Model Context Protocol servers without loading all tools at startup. Use when bootstrapping MCP configuration, verifying stdio servers, reconciling registered servers, pruning stale entries, or preventing tool catalogs from exhausting context or startup resources.
---

# Manage MCP Lifecycle

1. Inventory server definitions as metadata only: ID, command, arguments, transport, owner, trust, priority, effects, and health contract.
2. Discover an available shell/runtime explicitly; do not assume one executable exists.
3. Preview registration and reconciliation changes before writing configuration.
4. Keep new servers inactive until provenance, permissions, command paths, and dependency versions are admitted.
5. Probe the real protocol boundary with `initialize`, capability negotiation, and `tools/list`; process existence is not certification.
6. Bound startup to the highest-priority required servers and lazy-load the rest after task selection.
7. Record timeouts, malformed messages, stderr, tool-count/context cost, and shutdown behavior.
8. Disable or prune only with explicit approval and a recoverable configuration receipt.

Never transmit credentials in arguments or evidence. Treat every MCP tool's declared effects as untrusted until independently enforced.
