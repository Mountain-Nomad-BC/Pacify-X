# Engineering intelligence analysis contract

The runtime owner is `runtime.engineering_intelligence`.

Inputs are bounded mappings rather than unrestricted repository scans:

- architecture baseline/current adjacency maps;
- dependency adjacency map and changed component IDs;
- baseline/current typed contracts;
- provenance-backed claims;
- change risk facts;
- named health dimensions;
- path-to-source mappings for Python structural analysis;
- required and available capability IDs.

Outputs include baseline/current hashes, affected paths, uncertainty, explicit unknowns, and proposal-only actions. `code_genome` parses ASTs without importing or executing source. Shockwave traversal is depth- and node-bounded. Refactoring output always has `auto_apply: false`.

Research canonicalization is owned by `runtime.research_assimilation`. Every paper mechanism requires a source hash, citation, claim, mechanism, assumptions, evaluation context, limitations, and reproduction requirements. Missing citations block the bundle. Multiple sources record convergence but never constitute production proof.
