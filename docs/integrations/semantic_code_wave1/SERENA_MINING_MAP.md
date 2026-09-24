# Serena → PX Mining Map (Wave 1)

This is a behavior/invariant mining map, **not a source-code port map**.

| Mined idea | PX-native Wave 1 interpretation |
|---|---|
| Symbol-oriented navigation | `semantic_code_types.py`, `semantic_code_python.py`, `semantic_code_query.py` |
| Language backend abstraction | `semantic_code_backend.py`, `semantic_code_registry.py` |
| Symbol overview | `symbol_overview()` with bounded depth/results |
| Find symbol | typed `SymbolQuery`, exact/substr/path/kind filters |
| Find references | conservative local resolution + explicit ambiguity state |
| Diagnostics near symbols | normalized diagnostics + owner attachment |
| Symbol-body edits | immutable edit plans bound to source SHA-256 |
| Project-specific semantic state | canonical-root `SemanticProjectSession`; no global active project |
| Concurrent project requests | per-project session state + single-flight refresh |
| Cached semantic analysis | bounded SHA/backend-key LRU cache |
| Safe mutation concepts | PX `FileLock`, recheck, parse gate, fsync, atomic replace |
| Tool categorization concept | non-authoritative semantic operation descriptors for later PX admission |

## Important non-copy decision

The supplied Serena package declares `GPL-3.0-or-later`. PACIFY-X declares `Apache-2.0`. Wave 1 therefore uses Serena only as an architectural/behavioral research source and contains an original PX-specific implementation. No Serena source file is copied into this package and Serena is not added as a runtime dependency.
