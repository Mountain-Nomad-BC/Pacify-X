# External tree scan — what we're missing, and how to proceed

**Date:** 2026-10-27 · **Scope:** `C:\Users\Ben\Music\Pacify-X-main` and `C:\Users\Ben\Videos\Pacify-X-main` searched for every item this project currently lacks.
**Method:** read-only path/function scan (`tree_scan.json`), then behavioural probes that executed the external code against our own runtime. Nothing was copied into the checkout.

---

## 0. Headline

Both trees are **full source checkouts**, not fragments. Music nests one level deeper (`Pacify-X-main\Pacify-X-main`); an initial scan of the Music root returned "absent" for everything, which was a **path error on my part, not an actual absence** — corrected before any conclusion was drawn.

**They solve three of our problems and create one trap.** The most valuable find is not code: it is **Videos' `semantic-entity.schema.json`, which is stricter than the one I authored**. The largest trap is that Videos' `usage_memory` reads and writes a **different storage location** than ours, so adopting it wholesale would silently break T.I.E. reads.

---

## 1. Inventory result

| Item needed | Music | Videos | Canonical (ours) | Verdict |
|---|---|---|---|---|
| `runtime/usage_memory.py` (T.I.E. fuse) | present, larger | present, larger + link checks | present, mine | **Videos is a superset** |
| `retrieve_studio_experience` / `_studio_memory` | absent | **present** | absent | **Only in Videos** |
| `runtime/semantic_entity.py` | present | present | present (fixed) | Ours repaired; theirs lacks the fix |
| `contracts/semantic/semantic-entity.schema.json` | present | present | **mine (weaker)** | **Videos stricter — adopt** |
| `contracts/semantic/locator-record` etc. | present | present | absent | Owners also present in both → **not dead** |
| `scripts/build_contract_ownership_registry.py` | present | present | present (fixed) | Ours has `SEMANTIC_DIR_OWNERS`; check theirs |
| `contracts/project_revision_succession/*` | present | present | present (unpackaged→fixed) | — |
| `extension/src/agentHarness/durableTaskState.js` | present | present | **absent** | Port candidate |
| `scripts/rollout/*`, `test_rollout_inventory.py` | present | present | **absent** | Port candidate |
| `billing-settlement-audit.test.js` | present | present | present | Already closed |

### 1.1 The semantic contracts are not dead after all

My earlier R01 conclusion was that 10 reference-only contract owners "would be unreachable here". That was **correct for this checkout but incomplete as a disposition**: the owners for `semantic_locator`, `compact_address`, relations and census **do exist in both external trees and are imported there**. So these are genuine features of the product that our checkout lacks — not noise. They belong in the reconciliation matrix as *real missing surface*, not as "reference-only, ignore".

---

## 2. The three real finds

### 2.1 `semantic-entity.schema.json` — mine is too permissive (highest value)

Behavioural comparison on the same emitted record set:

| Case | Mine (original) | Videos |
|---|---|---|
| unknown field (`path`) | refused | refused |
| bad `entity_id` | refused | refused |
| bad `entity_kind` | refused | refused |
| bad lifecycle state | refused | refused |
| `qualifier: "bad qualifier!"` | accepted | accepted |
| **`qualifier` omitted** | **ACCEPTED** | refused |
| `qualifier: null` | ACCEPTED | refused |

Structural difference: theirs **requires** `qualifier` on every `identity_basis`; mine made it optional. Since `entity_id` is derived *from* the qualifier, an absent qualifier means the identity cannot be re-derived or audited — their rule is correct.

*Correction to my own earlier analysis:* I first cited `qualifier: "bad qualifier!"` as the divergence. That was wrong — both contracts accept it because it legitimately matches `^[\s\S]{1,512}$`. The real divergence is a **missing** qualifier, verified against the pre-change copy preserved in the runbook snapshot (`ORIGINAL qualifier omitted ACCEPTED` vs the new contract `refused`).

**Decision: replace my contract with the stricter one.** This is not copying for convenience; it is the contract that matches the owner's actual derivation rule, and it closes a hole my own adversarial test missed because I only tested the fields I had declared.

### 2.2 T.I.E. supervision hardening — adopt selectively, not wholesale

Videos' `usage_memory` adds `reject_path_links` on every read plus strict-mode record handling and `retrieve_studio_experience`. Those are real improvements to *this* problem class (link/reparse custody), and `runtime/archive_io.reject_path_links` already exists in our tree, so the dependency is available.

**But it is not drop-in.** Measured, not assumed:

```
external recorder wrote:  orchestration/workflows/wf_probe/memory/usage.jsonl
external fuse read:       .engineering-bootstrap/studios/workflows/wf_probe-<hash>/revisions/1.0.0/record.json
→ FileNotFoundError → reported as state: corrupt_or_unavailable
canonical fuse on the same tree: state: available, lineage: ATTRIBUTED, 3 records
```

So the external implementation **cannot read its own recorder's output in our layout** — it expects a Studio revision store we do not have. Porting it as-is would make T.I.E. permanently report `corrupt_or_unavailable` while looking correct in isolation.

Also: its binding shape is **strictly** `{kind, identity, version}`, so it rejects the 2-field form my tests (and callers) use.

**Decision: keep my working implementation; port the two hardening behaviours** (`reject_path_links` on the log path, strict record mode) into it. Accept the 3-field binding as an alias. Do **not** import `retrieve_studio_experience` without first deciding whether a Studio revision store is in scope.

### 2.3 Genuinely missing modules we can now port

`extension/src/agentHarness/durableTaskState.js`, `scripts/rollout/compare_trees.py`, `scripts/rollout/integration_plan.py`, `tests/test_rollout_inventory.py` all exist in both trees. These were the blockers I recorded for the Node billing suite and the rollout-inventory required suite. **These are now unblocked.**

---

## 3. What does NOT solve anything

- Music and Videos both **lack the successor signing authority** — no private key, no policy issuer. That remains BLOCKER-001. Neither tree changes it.
- Neither tree supplies a `project_id`-bearing predecessor campaign. BLOCKER-002 stands.
- Videos' `semantic_entity.py` **does not contain** our contract-resolution fix (`framework_root` / `contract_path`). Copying it back would **reintroduce** the publish-then-unreadable defect we repaired. Any port from Videos into `semantic_entity.py` must preserve our fix.
- The 196-vs-203 ownership drift is unchanged by any of this; it still resolves only at the freeze.

---

## 4. How to proceed — ordered plan

**Step 1 — contract correction (do first, small, high value).**
Replace `contracts/semantic/semantic-entity.schema.json` with the stricter Videos structure, adapted to our schema-id convention. Re-run: corpus round-trip, `test_semantic_entity_contract.py`, `test_model_profile.py`, and the adversarial comparison above, so the previously-passing `bad qualifier` case now correctly fails. Recheck the ownership generator rule still matches (filename unchanged).

**Step 2 — T.I.E. hardening (contained).**
Add `reject_path_links(memory / "usage.jsonl")` before the bounded read, and accept `{kind, identity, version}` as an alias of `{kind, identity}`. Add tests: a symlink/junction log must be refused, not read. Keep our storage layout and our honest lineage reporting.

**Step 3 — port the four genuinely missing modules.**
`durableTaskState.js` + `billing-settlement-audit.test.js` (Node billing), then `scripts/rollout/*` + `test_rollout_inventory.py`. Each needs its own causal test run and a check that it does not assume a Studio layout.

**Step 4 — re-open the semantic surface question.**
The locator/relation/compact-address/census contracts have owners in both trees. Decide explicitly: **in scope** (then port owners + contracts + tests as a group, with callers) or **out of scope** (then record why, and mark the 9 records `RETIRE_WITH_REVIEW` rather than leaving them ambiguous). Do not port the contracts without the owners, which is what my earlier disposition risked.

**Step 5 — update records.** `RECONCILIATION_MATRIX.csv` gains a row per item with the external hashes; `BLOCKER_REGISTER.md` unchanged for 001/002/003; `SESSION_STATE.md` next action becomes Step 1.

---

## 5. Caveat on the pasted test file

The `test_tie_fusion.py` you pasted does not match what is on disk — it contains a broken line (`um.fuse_tie_experience(project, super().__init__` …) that would not parse. The on-disk copy of `tests/test_tie_fusion.py` is intact and passes (14 tests). I treated the on-disk file as authoritative and have **not** applied the pasted version. If the pasted text was meant to flag something about that test, tell me which assertion you want changed and I will make a precise edit.
