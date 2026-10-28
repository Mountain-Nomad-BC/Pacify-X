# Workflow approval verification and remote integration

Status: native ingress verified; remote prepared-group workflow integration OPEN. No release or independent acceptance.

## Verified trust chain

| Boundary | Owner | Observation |
|---|---|---|
| Webview request to host authorization | extension/src/extension.js, studioOperation handler | Mutations obtain a native modal authorization, except explicitly configured owned-host automation. Caller approved_by is not the signing authority. Installed behavior remains to be exercised. |
| Host capability issuance | extension/src/pxBridge.js, issueStudioApproval | RSA claim binds project, kind, operation, canonical payload hash, expiry and random nonce. |
| External native request | runtime/studio_api.py, studio_operation | Consumes capability before constructing workflow owner; overwrites caller approval metadata with verified identity. |
| Capability verification/replay | runtime/studio_authority.py, consume_host_operation_approval | Verifies enrolled public trust and exact payload; exclusive consumption prevents replay. |
| Node approval | runtime/workflow_studio.py, issue_approval | Trusted owner issues exact revision/node/effect approval. This is not a public authentication API. |
| Node effect boundary | runtime/studio_authority.py, consume_approval | Checks scoped stored approval and one-use consumption. |

Evidence: resume10-approval-boundary-wire.json (13 passed), resume10-approval-host-neighbors.json (41 passed). The native success case actually executes increment/double through studio_operation. Unsigned approval claims, payload/operation/signature/project substitution and both operation/node approval replay are denied. These are disposable-fixture checks, not installed-system or production signing evidence. Earlier test-authoring request format failures are retained in approval-boundary and approval-boundary-json logs.

## Concrete remaining integration cards

### W1: Resolve admitted prepared-group ownership ? partial, positive admission depends on W2

Implemented the read-only WorkflowStudio.resolve_prepared_group_owner. It verifies the exact persisted plan/preparation, immutable typed revision and location, current signed admission, live authority hashes, and model-group executor identity. It scans bounded directories, refuses linked/reparse ancestors and hardlinked revision files, and grants no execution authority. The reference tree implements a bounded immutable revision scan, but its dependent _definition_from_record helper and group node validation are also absent here. Port a coherent dependency closure, using current physical-file and revision integrity owners. Refuse zero/multiple owners, links/reparse escapes, stale plan digest, altered revision, and any unadmitted model-group node. Resolution must grant no execution authority. Test actual persisted plans and workflow revisions, not a fake owner.

### W2: Execute prepared-group nodes through native effect custody

Current workflow executor has no prepared-model-group execution mode. Do not add only the two missing method names: that would leave the actual execution engine disconnected. Integrate current task plan, group executor, durable run control, effect-intent fencing, member outcomes, and artifact custody. Preserve cancellation/restart semantics. Exercise successful member output, failed/partial member, deadline, interruption after dispatch, and idempotent recovery without duplicated effects.

The reference execute_prepared_group_node accepts approved_by alone and assumes its caller already consumed a capability. Before exposing a new execution entry point, choose one owner for proof consumption and bind its verified result to the exact prepared reference and owner revision. A caller identity string must never substitute for that proof. Do not consume the same single-use proof twice, and do not issue fresh node authority merely from untrusted caller fields.

### W3: Wire remote bridge and outcome verification

After W1/W2, execute remote_model_bridge.chat with signed exact selection, matching current profile/member attachment, actual workflow commit, branch artifact and effect-intent settlement. Test stale profile/owner before dispatch and after await, forged outcome digests, missing member result, replay, cancellation and uncertain dispatch. Keep remote availability false until host custody and actual operating acceptance are proved. No live provider/network/service call is authorized by the present bounded local execution admission.

### W4: Installed approval scenario

Use a separately admitted owned installed-host run. Verify canceling the native dialog creates no capability/effect, caller-supplied approved_by cannot bypass the dialog, cross-panel payload changes fail, and a confirmed operation executes exactly once. Test the explicit owned-host authorization configuration separately. The 41 Node neighbors do not establish these installed outcomes.

After each card: retain original failing evidence, run focused causal checks and required changed-section attempts, append repository and first-kit tracking, and checkpoint material progress. Independent acceptance remains 0/105. No generated refresh, full profile, package, install or certificate while current repair intake remains unresolved.


## Progress: 2026-10-27 ownership segment

**W1a completed:** typed immutable record decoder, exact approval-required/fail-closed prepared-reference declaration, read-only ownership scan and fail-closed admission checks. Ordinary arithmetic adapters explicitly reject prepared-group mode. Real persisted-plan/revision tests exercise stale digest, altered revision, missing/ambiguous owners, missing admission, directory bound, malformed declaration, real hardlink and real directory symlink rejection. No symlink skip occurred.

Evidence: `resume10-owner-resolution-bounds.json` (25 passed, 45 deselected); `resume10-owner-model-neighbors.json` (66 passed); `resume10-owner-physical-paths.json` (13 passed after final path check). Owned processes closed and resources inactive. Initial `resume10-owner-resolution.log` records seven setup errors that exposed another missing prerequisite: task config was entirely closed. Added only the exact reference-only declaration; it grants no adapter admission.

**W1 remains partial:** successful resolution of an actually admitted group cannot be proved until the model-group executor is integrated. Existing admission intentionally rejects it. No synthetic signed runnable receipt was substituted for that missing implementation.

**W2 started ? dependency audit:** current StudioAuthorityStore's transaction, single executor registration and resolve_executor all omit model-group; workflow_worker only supports arithmetic/identity adapters. The reference worker contains native effect-intent verification, exact placements, group outcome checks and commissioned host composition absent here. Integrate those together with parent workflow task-plan handoff and cancellation/recovery. Merely adding model-group to the allowlists would create false admission, so allowlists remain closed. The reference's namespace paths also differ from current legacy studio state; preserve the current authoritative writer until the separate migration cutover.

Required studio-memory-graph section was attempted and refused at the processing-order gate: current historical campaign is installed_operational, not repair/revision_reconciled. This is blocked gate evidence, not a passed section. W3 and W4 have not started. No full profile, generated refresh, production effects or release artifacts.


### W2a: closed execution declaration integrated (2026-10-27)
Ported runtime/workflow_group_config.py after reviewing its native AgentSpec dependency. WorkflowNode now invokes the exact four-field parser (mode, prepared reference, agent spec, placements); the earlier reference-only declaration remains non-executable. Parser accepts no caller approval fields or path references. This does not admit a model-group adapter. Arithmetic executors refuse both group declaration forms.

Final combined suite: **79 passed**, evidence `docs/repair/evidence/resume10-group-declaration-key-isolation.json`; owned tree closed and resource inactive. Eleven parser/declaration tests include a real persisted workflow and native rejected admission. An earlier test used a key directory inside its project and correctly failed the authority boundary; its original log remains in `resume10-group-declaration-integrated.log`. The test now uses sibling project/key paths. This was a test isolation error, not a production bypass.

W1a and W2a substeps are complete; W1/W2 overall remain partial. Next: W2b integrate commissioned host composition and exact persisted-plan handoff into parent/worker with native effect-intent fencing and cancellation/recovery; only then enable adapter admission and prove W1 positive. W3/W4 remain open. Governed section attempt remains phaseblocked (`resume10-group-declaration-section.json`). No generated refresh, full profile, service, production remote request, package, install, certificate, push, merge or VSIX.


### W2b progress: worker pre-dispatch repair and persisted-plan binding (2026-10-27)

**Completed W2b.1:** the native workflow worker now checks node kind, closed non-validation configuration and consumed approval before invoking any adapter. Three real signed-task reproductions showed the sleep adapter being invoked before denial; all three original failures are retained in `resume10-worker-pre-dispatch-red.log`. The repaired checks and real native workflow approval/run neighbors passed (27 checks, `resume10-worker-pre-dispatch-green.json`). These tests use the actual worker entry point and native signed task authority, with an observed adapter callback; they are not production group effects.

**Completed W2b.2:** added `resolve_workflow_group_plan` and wired it into full-config prepared-group owner resolution. It reads the actual persisted plan/preparation, decodes the native AgentSpec and verifies exact project/member denominator, native placement digest, plan digest, attachment digest and member context digest. It grants no execution authority or live generation/capacity/provider admission. A three-member persisted-plan success case and independently rehashed stale project/member/plan/attachment/context/digest cases are covered. Combined suite **47 passed** (`resume10-group-plan-binding.json`); all owned children closed and resource records inactive.

Required changed-section attempts remain phaseblocked (`resume10-worker-pre-dispatch-section.json`, `resume10-group-plan-binding-section.json`). No passed governed receipt is claimed. The reference group execution depends on `AgentRuntimeController.execute_governed_group`, which is also absent from this checkout; W2 is a controller/worker/host integration, not just two missing WorkflowStudio methods. The reference's generation observer is unavailable without a real host observer, so saved context vectors cannot be substituted as fresh authority.

**Next W2b.3:** integrate native governed group controller with parent/worker signed task-plan handoff, current generation owner, commissioned suspended worker custody and durable effect intents. Keep model-group out of the authority allowlists until this coherent path exists and has success/failure/cancel/restart/uncertain-effect proofs. Then finish W1 positive admission, proceed to W3 remote outcomes and W4 installed host. W1/W2 overall remain partial; no reviewed closures, certification, Git merge, package or VSIX.


### W2c dependency closure: convergence and terminal dispositions (2026-10-27)
Ported runtime/model_convergence.py and runtime/work_disposition.py with contracts/models/work-disposition.schema.json and an explicit source ownership rule. Published ownership is intentionally not regenerated during intake; the previously reported missing-contract denominator is now historical and will increase by this newly added schema.

37 focused checks passed (`resume10-group-committed-convergence.json`). Typed quorum checks cover correlated origins, dissent, missing/duplicate/failed members and uncontained observations. The committed boundary consumes native branch artifact custody and the native trusted-evidence resolver. A real committed artifact without an attestation remains blocked, including when a caller supplies proven=True. No independent reviewer, certificate or native containment authority is fabricated.

Reference adaptation: removed the ability for caller-provided containment_proofs dictionaries to replace false signed postconditions. All required isolation/containment/commit postconditions must be present in verified signed assessment; live native custody remains an additional execution requirement. Full positive signed-attestation integration still needs exercising and is not claimed here. These new owners are controller dependencies; execute_governed_group is not yet integrated.

Next dependency: remote provider placement and local/remote member outcome custody, then the group controller and parent/worker integration. Group authority allowlists remain closed.


### W2d dependency and native controller integration (2026-10-27)

Completed the remote placement owner and native governed member/controller path. Remote placements are derived from actual signed profiles and native grants; service/origin/plan/context substitution is denied even after rehashing (10 checks with attachment neighbors, `resume10-remote-placement-binding.json`). No remote request or network operation ran. Mixed local/remote custody remains unavailable until the missing local outcome verifier is integrated; ordinary local-only groups do not import that missing owner.

AgentRuntimeController now resolves exact prepared members in preview, accepts current context generation and explicit member executors, builds parent/child execution contexts and propagates cancellation before output commitment. The existing signed receipt publication semantics were retained; the reference's later advisory receipt rewrite was not copied. Three real disposable Studio member checks passed (`resume10-studio-prepared-member.json`), and 12 existing governed/member neighbors passed. The cancellation assertion was then corrected to inspect the actual canonical model-artifacts/commitment.json owner, not a nonexistent legacy directory.

Added execute_governed_group through the real durable run controller, current-generation observer, capacity/branch custody, member effect-intent fencing and convergence owner. A real group test exposed a reference defect: missing signed assessment gave INDETERMINATE convergence but a succeeded root. Original failing evidence retained in `resume10-native-group-owner.log`; success now requires PASS convergence. Added post-member generation reobservation to halt on drift before group acceptance. Committed and uncertain-failure intents refuse blind retry. Native required containment denies before execution when unavailable.

Real OpenSSH-signed, scoped branch-assessment fixtures now exercise success and negative containment through the native evidence resolver. Disposable fixture keys are not release authority and were not enrolled into production trust. The fixture attests controlled test conditions; it does not prove real native process/network containment. A caller-supplied proven dictionary cannot override false signed containment postconditions. Combined result: 25 passed (`resume10-native-group-signed-containment.json`). Earlier 26 checks cover replay, uncertain failure, native worker guards and placement/convergence neighbors (`resume10-native-group-uncertain-replay.json`). Existing trust fixture signing helpers create OpenSSH descendants inside the owned runner Job; separate per-descendant creation records are not asserted. These receipts are focused repair evidence, not certification closure.

The current native group implementation is reachable as a trusted library owner. It is NOT yet connected to the external WorkflowStudio prepared-group run route. Missing workflow effect verifier, suspended worker host composition, provider adapter/member outcome settlement and live generation transport remain W2e; keep model-group out of StudioAuthorityStore allowlists until those paths are integrated. W1 positive external admission, W3 and W4 remain open. Required governed attempts remain processing-order blocked; published projections were not regenerated. Newly ported work-disposition schema has an explicit source owner and existing models wildcard package inclusion, but published ownership count is deliberately stale.


### W2e parent/worker effect boundary and resumed runtime (2026-10-27)

Completed native workflow effect verification: exact running root, revision/epoch/node authority, deadline, in-flight intent and active scope lease are checked before worker adapter dispatch. Group signed-task verification also requires consumed approval evidence and exact agent/placement/plan bindings. The current legacy workflow session owner is retained consistently; no namespace cutover was performed.

Completed parent preparation/observation plumbing: scope leases and intents precede worker launch; stable run/node effect keys survive retries; uncertainty retains quarantined scope exclusion and prevents automatic replay. Parent settlement only observes exact native committed results and never manufactures commits from worker assertions. Exception text containing tree_closed=true is explicitly not physical closure proof. Native supervisor launch progress controls closure evidence. Focused receipts: worker-effect-boundary-integrated (23 pass), worker-native-settlement-observation (11 pass), parent-native-effect-settlement (26 pass), parent-fence-native-workflow (26 pass), parent-effect-quarantine (27 pass). Counts overlap and are not summed.

Before these changes the combined native controller/approval/member/declaration suites passed 74 checks (group-controller-final-neighbors). Native group cleanup denial passed 10 controller checks; reconciliation failures are propagated instead of silently swallowed. Production model-group executor registration remains closed until suspended worker composition and provider/native outcome paths are coherent. W1 overall, W2 overall, W3, W4 remain open.

On resume, both old virtual environments failed because their Temp/py3145t base was gone. Python3.11 ran the ledger; expired session36231 was closed at36244, checkpoint36245 created, and fresh exact-scope admission36246 opened. A first closure payload omitted its gap/session fields and was rejected before append; corrected through the native ledger. Existing repository Python/pythoncore-3.14-64/python.exe is Python3.14.7 with GIL enabled. The retained focused runner now uses its invoking interpreter instead of the vanished path; original runner preimage is registered at .tmp/resume10/owned/pacifyx-8l9uakj1. Old runtimes and receipts are untouched. Compatible existing .venv-certify site-packages are selected via PYTHONPATH with PYTHONNOUSERSITE=1 for the focused runner. No installation/download occurred. Stable-runtime-check passed 17 checks with closed process tree/inactive resource. This does not reproduce prior free-threaded Python3.14.5 concurrency evidence.

Next: complete configured provider adapter/member settlement dependencies and the suspended group worker composition. Do not enable group admission simply to make W1 positive. Production provider health, native containment/generation transport and independent review remain unproved; no certificate/package/merge/VSIX claim.


### W2f provider, wire and worker composition integration (2026-10-27)

Ported the native provider binding/stream/member/outcome owners: remote_provider_adapters, group_provider_adapters, member_execution and remote_member_execution. Remote bindings use actual signed profile/grant/policy and recheck native registry/policy currentness; three controlled binding tests pass with socket creation forbidden. Named service recordings exposed Gemini surface rejection and missing Claude cached input accounting (three original failures retained). Added Gemini text-only request/stream translation and strict reported usage aggregation while preserving incremental UTF-8, whitespace and unsuccessful-terminal fixes. Protocol/gateway neighbors: 36 passed; no live connection was made.

Ported configured group-worker composition, exact legacy workflow resource-ledger references, native recovery/custody reconstruction and host-only generation/assessment adapters. Saved vectors are not live observers, task JSON cannot select code, assessment callbacks return only native evidence references, and native trusted evidence still verifies signatures/scopes/postconditions. A composition audit caught two unbound callback names in my integration; corrected before enabling group registration. Dedicated host/composition/binding/wire checks: 20 passed. Native parent pre-release enrollment and resource quarantine/closure are wired; 35 workflow/custody/import/host neighbors passed. Group registration is still closed pending genuine protected worker/provider operating proof.

Corrected local-only provider effects: production group plans declare exact loopback/origin plus owned gateway event/budget writes as well as execute/runtime. Local-only and mixed groups use the same signed workflow custody and native provider outcome settlement; production member execution explicitly requires provider custody. Direct library controlled callbacks remain separate from production provider proof. Native group/controller/declaration/fence/placement checks: 49 passed.

Actual hostile managed-project reproduction showed runtime/__init__.py shadowing the engine before worker checks. Original marker failure retained. Added Python safe-path (-P) to workflow, session worker, terminal observer and agent harness launches. Actual native workflow and boundary neighbors then passed 28 checks. Agent owned pause/resume/cancel lifecycle passed. Workflow lifecycle exposed my incorrect treatment of every grant permission as an attempted effect: pure closed arithmetic adapters may hold broader scheduling grants without pretending to perform writes. Native effect manifests now distinguish that case; group mutations still need all exact fences. Original fixture was not weakened. Verbose workflow/custody/hostile-import scenario: 17 passed in47.71s. Its prior silent run was stopped at the focused runner's20s startup-output bound, exit0xC000013A; retained as a stopped run, not source success.

Changed section attempts: studio-memory-graph/native-provider-protocol/billing-budget remain phaseblocked. I first ran them concurrently and two hit the shared orchestration lock; original receipts retained. Sequential retries reached the actual processing-order blocker. No passed section, full profile, generated reconciliation, install, certificate or release artifact is claimed.

Next: finish the prepared-group approval execution entry point and bridge receipt-owner consistency; obtain actual commissioned host/generation/assessment/provider evidence before enabling group admission and marking W1/W2 operating acceptance. W3/W4 and independent review remain open.
