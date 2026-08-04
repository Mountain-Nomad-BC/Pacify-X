# Merge and compatibility report

- Starting branch: `main`
- Starting commit: `267abe7f501280d5bc6fb0a5f820e92e5014e98c`
- Repair branch: `repair/trust-boundary-hardening`
- Integration commit: `4d795e11210d076c632e8135470ed273a9ece872`
- Evidence-closure commit: the commit containing this report; resolve with `git log -1 --format=%H -- evidence/repairs/trust-boundary-hardening/`
- Target branch: `main`
- Final target commit: the published `main` tip after the fast-forward merge; resolve with `git rev-parse origin/main`
- Remote: `git@github.com:Mountain-Nomad-BC/Pacify-X.git`

The nine cards were integrated in their required dependency order and share one trust resolver and one exit-code policy. No feature branch or mechanical conflict strategy was used. The target had not diverged during implementation; final synchronization, merge, post-merge smoke checks, and public CI status are recorded when those actions complete.

Compatibility changes are intentional at the public authority boundary:

- old inline outcome claims move to `evaluate-outcome-claims`;
- old Boolean admission evidence moves to `evaluate-admission-claims`;
- old caller-allowed authorization moves to `simulate-authorization`;
- `review-candidate` rejection and quarantine return nonzero disposition codes;
- `authorize`, `review-candidate`, and `verify-outcome` reserve authoritative language for resolved signed evidence.

The parser, unrelated command names, source invocation, Windows behavior, installed-wheel entry point, and deterministic help remain compatible. Migration details are in `docs/trust-boundary-migration.md`.

No unrelated defect was silently changed. The only deferred external action is publication of durable custody assets by a future authorized signed release; the implementation and local reconstruction tests are complete, but v0.6.3 remains immutable.
