# Pacify-X Model Fabric Integration

This client layer is subordinate to Pacify-X's existing model, provider, resource, and execution authorities.

## Client path

`VS Code Language Model API -> pxLanguageModelProvider.js -> mcpModelFabricBridge.js -> runtime.vscode_model_bridge -> ProviderInvocationGateway -> admitted local runtime`

The client never starts or loads a model, never accepts arbitrary localhost endpoints, and never grants provider/tool authority.

Only profiles that are **certified**, bound to the currently running governed router plan, and already reported `loaded`/`sleeping` are advertised to VS Code. Candidate profiles remain invisible.

The current integration record stays `candidate` until target-workstation certification admits the exact streaming adapter and at least one profile is certified.

## Roles

- `control`: resident CPU librarian/operator; bounded classification, candidate selection, query decomposition and context planning.
- `fast`: small low-latency generation/code lane.
- `balanced`: larger local lane used selectively.
- `deep`: hybrid CPU/GPU sparse/MoE reasoning lane, including the preferred Qwen3-30B-A3B candidate.
- `embedding` / `reranker`: retrieval-only services.

## Authority boundaries

A language-model request does not grant model-load, tool-execution, memory-write, knowledge-promotion, network, billing, or release authority. Tool calls returned by a model are proposals delivered to the VS Code host. Existing PX operation/MCP/approval owners remain responsible for execution.

Reasoning-delta events are deliberately not surfaced by the VS Code provider. Text, normalized tool calls, usage/accounting, cancellation and exact token counting remain governed by the provider gateway.

## Cancellation and accounting

VS Code cancellation is passed through the bridge to the child PX model-client process. The canonical provider gateway owns provider cancellation, durable lifecycle events, exact token accounting and non-billable local budget settlement.

## Installed-host gate

Before this integration can expose a model:

1. the GGUF/model identity must be frozen;
2. the runtime profile must be `certified`;
3. the router session must be current/running;
4. the model must already be loaded/sleeping;
5. `llama-cpp-stream` must be explicitly admitted/ready;
6. exact token count and stream conformance must pass on the target machine.
