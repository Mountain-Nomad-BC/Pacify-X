# Project Intelligence Map

Map revision: `74da011871fe44fbb2fc49a9eb74d2852d7438da9cc8c5549054c6f9f970351f`
Source inventory: `3fcd8228fdcd90f9ad342cecdb9fe6c21dc5569a8d9c233d7c1143a5a93409f6`

## Coverage

- Files: 6000
- Symbols: 10770
- Dependency edges: 9236
- Routes: 9
- Runtime services: 0
- Contracts: 226
- Configuration keys: 13635
- Retrieval documents: 30668

## Runtime markers

- No runtime category was proven from static manifests.

## Risks and unknowns

- **medium — parse-errors**: 1 parser errors or unsupported structures
- **medium — unresolved-imports**: 1625 imports or service dependencies could not be resolved statically
- **low — truncated-text-scans**: 3 files exceeded the per-file text scan ceiling
- **medium — untested-source-candidates**: 493 source files have no static test link
- **informational — sensitive-config-keys**: 100 sensitive-looking configuration keys are referenced; values were not captured
- **informational — generated-surfaces**: 3 generated or vendor-like files were mapped
- Unknown: Dynamic runtime paths, reflection, plugin loading, external consumers, deployed configuration values, and production traffic are not proven by static mapping.

## Retrieval

Use `engineering-bootstrap project-map query --project <path> --query <goal>` to retrieve map records and a minimal source hydration plan.
