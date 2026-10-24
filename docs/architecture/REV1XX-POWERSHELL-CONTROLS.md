# Fresh campaign PowerShell controls

The three retained `run_auth`, `run_iso` and `run_broad2` entry points are
retired. They previously invoked broad reconciliation/checks outside the
current changed-section owner, coupled execution to a workstation path and
wrote/deleted external temporary outputs. They now fail before any action.
Use the currently admitted native changed-section gate instead. Broad
reconciliation, full-profile, build and install stages remain subject to
processing-order controls and the owner's explicit holds.

The three retained cleanup entry points also fail before any action. Names,
directory shapes, inactive-looking processes and historical approval labels
cannot establish current ownership, retention disposition or deletion authority.
The native ResourceManager ledger, reclamation gate, process identity and fresh
effect admission remain authoritative. No external cleanup was performed in
this repair, and no automatic deletion replacement was introduced.

`scripts/cert_env.ps1` now discovers literal application names, preserving the
current process PATH precedence and supplementing it with persisted PATH
entries. Missing requested tools fail without installation and restore the
previous PATH. Its report explicitly does not verify certification. It does
not sign, download, require an installed editor cache or configure a reconstructed
commencement document. Native release/certification validators remain unchanged.

The old script names remain fail-closed compatibility entry points; callers
depending on their former actions must migrate to native owners. Original
source bytes are retained in the scoped immutable archive. Offline native
PowerShell parsing and actual safe invocation tests cover the new behavior;
each test child is registered and closed by ResourceManager. These proofs do
not certify all PowerShell scripts or close the wider portability/semantic wave.
