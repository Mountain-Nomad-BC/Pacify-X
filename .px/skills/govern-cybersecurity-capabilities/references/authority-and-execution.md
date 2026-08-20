# Authority and execution contract

The cybersecurity provider supplies untrusted candidate knowledge. Only Pacify-X runtime policy may grant authority.

| Class | Default | Required before selection for action |
|---|---|---|
| R0 | Advisory | Target context and evidence provenance |
| R1 | Read-only defensive | Scoped targets, allowlist, read-only mode, evidence handling |
| R2 | Controlled change | Written authorization, human approval, change window, rollback, cleanup, verification |
| R3 | Intrusive authorized test | R2 gates plus valid rules of engagement, exact allowlist, time bounds, kill switch, non-production default |
| R4 | High-impact dual use | Knowledge-only or explicitly authorized isolated lab; never production by default |

Evaluate per engagement and per target. A valid engagement does not authorize an unlisted target, an unadmitted tool, an undeclared effect, or a later session outside the authorization window.

Tool availability is not permission. For each proposed tool, require a canonical registry match, exact version, allowed arguments and targets, filesystem/network/credential/privilege effects, timeout, output limit, cancellation, evidence capture, and cleanup oracle.

Evidence originals are immutable. Record source hash, acquisition, actor, timestamp, authorization artifact, transformations, output hashes, decision, and cleanup result. A scanner or model result begins as an observation; verification evidence is required before it becomes a finding.
