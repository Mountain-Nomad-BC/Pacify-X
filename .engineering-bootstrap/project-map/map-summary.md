# Project Intelligence Map

Map revision: `9b9bcefc6882b1bd80548b86e1bc121ae863a21b8401fce485ec669afb3c46f7`
Source inventory: `70b52e0d3610a29d1977326903c27f298fc97bcc26d549799182424d7a4ea10b`

## Coverage

- Files: 5766
- Symbols: 8241
- Dependency edges: 7382
- Routes: 9
- Runtime services: 0
- Contracts: 201
- Configuration keys: 43429
- Retrieval documents: 57673

## Runtime markers

- No runtime category was proven from static manifests.

## Risks and unknowns

- **medium — unresolved-imports**: 1312 imports or service dependencies could not be resolved statically
- **low — truncated-text-scans**: 2 files exceeded the per-file text scan ceiling
- **medium — untested-source-candidates**: 305 source files have no static test link
- **informational — sensitive-config-keys**: 261 sensitive-looking configuration keys are referenced; values were not captured
- **informational — generated-surfaces**: 2 generated or vendor-like files were mapped
- Unknown: Dynamic runtime paths, reflection, plugin loading, external consumers, deployed configuration values, and production traffic are not proven by static mapping.

## Retrieval

Use `engineering-bootstrap project-map query --project <path> --query <goal>` to retrieve map records and a minimal source hydration plan.
