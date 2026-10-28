from dataclasses import replace
from datetime import datetime, timezone
import pytest
from runtime.agent_runtime import AgentRuntimeController, _plan_execution_context
from runtime.model_attachment import build_model_attachment
from runtime.model_group_preparation import prepare_model_group
from runtime.execution_placement import route_hardware
from runtime.hardware_routing import WorkloadProfile, WorkloadKind, HardwareProfile, BenchmarkEvidence
from tests.test_model_group_preparation import prepared, plan_for
from tests.test_agent_runtime import fixtures


@pytest.fixture
def admitted_member(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    monkeypatch.setenv("PX_STUDIO_KEY_ROOT", str(tmp_path / "keys"))
    group, attachments, retrievals, _ = prepared(1, root)
    workload = WorkloadProfile(WorkloadKind.TEXT_ANALYSIS, 5, 1024, False, operation_id="studio-prepared-member")
    hardware = HardwareProfile(False, None, None, None, 0, 0, 16 * 1024**3, "windows", 8, 4, False, (), (), cuda_executor_available=False)
    benchmark = BenchmarkEvidence(workload.operation_id, hardware.fingerprint, 2.0, 1.0, True, 0, datetime.now(timezone.utc).isoformat(), workload_fingerprint=workload.fingerprint)
    original = attachments["model-0"]
    attachments["model-0"] = build_model_attachment(root, model_id=original.model_id, model_revision=original.model_revision, artifact_sha256=original.artifact_sha256, runtime=original.runtime, context_tokens=original.context_tokens, modalities=original.modalities, supports_tools=False, privacy=original.privacy, authority_class=original.authority_class, benchmark_revision=benchmark.revision, hardware_requirements=dict(original.hardware_requirements))
    preparation = prepare_model_group(group, attachments, retrievals, root=root)
    plan = plan_for(group, preparation)
    placement = route_hardware(plan.as_dict(), model_id="model-0", workload=workload, hardware=hardware, benchmark=benchmark, project_root=root)
    body = "Use only the prepared member context."
    spec, binding, grant = fixtures(body)
    spec = replace(spec, project_id=plan.project_id)
    controller = AgentRuntimeController(root)
    controller.create_candidate(spec, body)
    assert controller.test_candidate(spec)["passed"] is True
    controller.register_authority([binding], [grant])
    assert controller.admit(spec)["decision"] == "admitted"
    return controller, spec, plan, placement


def test_studio_runs_exact_prepared_member_and_retains_native_artifact(admitted_member):
    controller, spec, plan, placement = admitted_member
    seen = []
    def execute(invocation, **kwargs):
        seen.append((invocation.model_id, kwargs["execution_context"], kwargs["cancellation_token"]()))
        return {"answer": "native prepared member"}
    receipt = controller.execute_governed_plan(spec, task_plan=plan.as_dict(), placement=placement, approval=True, gpu_fn=None, cpu_fn=None, current_context_generation=plan.context_generation, member_executor=execute)
    assert seen[0][0] == "model-0" and seen[0][2] is False
    assert seen[0][1].project_id == plan.project_id
    assert receipt["outcome"]["branch_artifact"]["model_id"] == "model-0"
    assert receipt["outcome"]["capacity_release"]["released"] is True
    assert controller.run_control.read(receipt["run_id"])["state"] == "succeeded"


def test_missing_generation_denies_before_member_dispatch(admitted_member):
    controller, spec, plan, placement = admitted_member
    seen = []
    with pytest.raises((ValueError, PermissionError)):
        controller.execute_governed_plan(spec, task_plan=plan.as_dict(), placement=placement, approval=True, gpu_fn=None, cpu_fn=None, member_executor=lambda *a, **k: seen.append(True))
    assert seen == []


def test_parent_cancellation_prevents_member_output_commit(admitted_member):
    controller, spec, plan, placement = admitted_member
    parent = controller.run_control.create(kind="agent", subject_id=spec.agent_id, version=spec.version, owner=spec.owner, revision_sha256="a" * 64, request_sha256="b" * 64, checkpoint={"phase": "parent"})
    parent = controller.run_control.transition(parent["run_id"], "running", actor=spec.owner, approved=True, operation="fixture.parent.start")
    context = _plan_execution_context(plan.as_dict(), run_id=parent["run_id"], actor_id=spec.owner, revision=parent["sequence"], epoch=1)
    def execute(invocation, **kwargs):
        controller.run_control.transition(parent["run_id"], "cancel_requested", actor=spec.owner, approved=True, operation="fixture.parent.cancel")
        assert kwargs["cancellation_token"]() is True
        return {"answer": "must not commit"}
    with pytest.raises(RuntimeError, match="cancellation"):
        controller.execute_governed_plan(spec, task_plan=plan.as_dict(), placement=placement, approval=True, gpu_fn=None, cpu_fn=None, current_context_generation=plan.context_generation, member_executor=execute, execution_context_parent=context)
    controller.run_control.transition(parent["run_id"], "cancelled", actor=spec.owner, approved=True, operation="fixture.parent.closed")
    assert not list((controller.project_root / ".agentic_engineering_os_px/runtime-core/model-artifacts").glob("**/commitment.json"))


def test_group_owner_fences_replay_and_refuses_missing_attestation(admitted_member):
    from runtime.trusted_evidence import TrustedEvidenceResolver
    from runtime.effect_intent import EffectIntentLedger
    controller, spec, plan, placement = admitted_member
    store = controller.project_root / "evidence-store"
    store.mkdir()
    policy = controller.project_root / "trust-policy.json"
    policy.write_text("{}", encoding="utf-8")
    resolver = TrustedEvidenceResolver(store, policy)
    calls = []
    def execute(invocation, **kwargs):
        calls.append(invocation.model_id)
        return {"answer": "group member output"}
    kwargs = dict(task_plan=plan.as_dict(), placements={"model-0": placement}, approval=True, member_executor=execute, generation_observer=lambda: plan.context_generation, evidence_resolver=resolver, accepted_producers=set(), attestation_provider=None)
    result = controller.execute_governed_group(spec, **kwargs)
    assert calls == ["model-0"]
    assert result["control_state"] == "failed"
    from runtime.studio_models import digest
    assert digest(controller.read_governed_group_run(result["group_run_sha256"])) == digest(result)
    with pytest.raises(ValueError):
        controller.read_governed_group_run("../outside")
    assert result["assessment"]["convergence"]["status"] == "INDETERMINATE"
    assert controller.run_control.read(result["group_run_id"])["state"] == "failed"
    key = f"group-member:{plan.plan_sha256}:{plan.model_execution_group.group_sha256}:model-0"
    assert EffectIntentLedger(controller.project_root).fence(key)["disposition"] == "committed"
    replay = controller.execute_governed_group(spec, **kwargs)
    assert calls == ["model-0"]
    assert replay["control_state"] == "failed"
    assert "model-0" in replay["member_failures"]


def test_required_native_containment_denies_group_before_member(admitted_member):
    from runtime.gremlin.enrollment import ContainmentRequired
    controller, spec, plan, placement = admitted_member
    calls = []
    with pytest.raises(ContainmentRequired):
        controller.execute_governed_group(spec, task_plan=plan.as_dict(), placements={"model-0": placement}, approval=True, member_executor=lambda *a, **k: calls.append(True), generation_observer=lambda: plan.context_generation, evidence_resolver=None, accepted_producers=set(), attestation_provider=None, containment_required=True)
    assert calls == []


def test_group_reobserves_generation_after_member_returns(admitted_member):
    from runtime.trusted_evidence import TrustedEvidenceResolver
    controller, spec, plan, placement = admitted_member
    store = controller.project_root / "evidence-store"
    store.mkdir()
    policy = controller.project_root / "trust-policy.json"
    policy.write_text("{}", encoding="utf-8")
    changed = []
    def observe():
        if changed:
            return None
        return plan.context_generation
    def execute(invocation, **kwargs):
        changed.append(True)
        return {"answer": "completed under original generation"}
    result = controller.execute_governed_group(spec, task_plan=plan.as_dict(), placements={"model-0": placement}, approval=True, member_executor=execute, generation_observer=observe, evidence_resolver=TrustedEvidenceResolver(store, policy), accepted_producers=set(), attestation_provider=None)
    assert result["control_state"] == "failed"
    assert "generation drift after member" in result["member_failures"]["model-0"]["reason"]


def test_uncertain_member_failure_never_blindly_retries(admitted_member):
    from runtime.trusted_evidence import TrustedEvidenceResolver
    from runtime.effect_intent import EffectIntentLedger
    controller, spec, plan, placement = admitted_member
    store = controller.project_root / "evidence-store"
    store.mkdir()
    policy = controller.project_root / "trust-policy.json"
    policy.write_text("{}", encoding="utf-8")
    calls = []
    def execute(invocation, **kwargs):
        calls.append("effect may have happened")
        raise InterruptedError("unknown member outcome")
    kwargs = dict(task_plan=plan.as_dict(), placements={"model-0": placement}, approval=True, member_executor=execute, generation_observer=lambda: plan.context_generation, evidence_resolver=TrustedEvidenceResolver(store, policy), accepted_producers=set(), attestation_provider=None)
    first = controller.execute_governed_group(spec, **kwargs)
    assert first["control_state"] == "failed"
    key = f"group-member:{plan.plan_sha256}:{plan.model_execution_group.group_sha256}:model-0"
    assert EffectIntentLedger(controller.project_root).fence(key)["disposition"] == "failed"
    second = controller.execute_governed_group(spec, **kwargs)
    assert second["control_state"] == "failed"
    assert calls == ["effect may have happened"]
    assert not list((controller.project_root / ".agentic_engineering_os_px/runtime-core/model-artifacts").glob("**/commitment.json"))


@pytest.mark.parametrize("contained", [True, False])
def test_group_success_requires_real_signed_scoped_branch_assessment(admitted_member, tmp_path, contained):
    import json
    from runtime.trusted_evidence import TrustedEvidenceResolver, sign_evidence_record
    from tests.test_trust_boundaries import _authority
    controller, spec, plan, placement = admitted_member
    # Disposable test authority only; never enrolled into project release trust.
    key, policy, identity, publisher = _authority(tmp_path / "test-authority")
    store = tmp_path / "signed-evidence-store"
    store.mkdir()
    def attest(model, artifact):
        value = {"schema_version": "1.0", "evidence_id": "branch", "evidence_type": "postcondition", "producer": "trusted-test-producer", "project_id": plan.project_id, "subject_id": "model-branch:" + artifact["artifact_sha256"], "task_id": plan.plan_id, "execution_id": artifact["run_id"], "actor_id": spec.owner, "session_id": plan.model_execution_group.branches[0].agent_generation_id, "created_at": datetime.now(timezone.utc).isoformat(), "result": {"postconditions": {"branch_isolation": True, "independence_commit_before_peer_visibility": True, "process_tree_monitoring": contained, "network_attribution": contained}, "conclusion": "supported", "evidence": [{"evidence_id": "observed-fixture", "kind": "independent_observation", "origin_id": "fixture-authority"}]}}
        signed = sign_evidence_record(value, private_key=key, signature_path=store / "branch.json.sig", identity=identity, publisher=publisher)
        (store / "branch.json").write_text(json.dumps(signed), encoding="utf-8")
        return "evidence:branch"
    result = controller.execute_governed_group(spec, task_plan=plan.as_dict(), placements={"model-0": placement}, approval=True, member_executor=lambda *a, **k: {"answer": "signed fixture result"}, generation_observer=lambda: plan.context_generation, evidence_resolver=TrustedEvidenceResolver(store, policy), accepted_producers={"trusted-test-producer"}, attestation_provider=attest)
    assert result["control_state"] == ("succeeded" if contained else "failed")
    assert result["assessment"]["convergence"]["status"] == ("PASS" if contained else "INDETERMINATE")
    assert result["authority_granted"] is False
    if not contained:
        from runtime.model_convergence import converge_committed_group
        artifact = result["member_receipts"]["model-0"]["outcome"]["branch_artifact"]
        retried = converge_committed_group(controller.project_root, plan, {"model-0": artifact}, {"model-0": "evidence:branch"}, resolver=TrustedEvidenceResolver(store, policy), accepted_producers={"trusted-test-producer"}, actor_id=spec.owner, containment_proofs={"model-0": {"proven": True}})
        assert retried["convergence"]["status"] == "INDETERMINATE"


def test_group_cannot_report_closed_when_member_reconciliation_fails(admitted_member, monkeypatch):
    from runtime.trusted_evidence import TrustedEvidenceResolver
    controller, spec, plan, placement = admitted_member
    store = controller.project_root / "evidence-store"
    store.mkdir()
    policy = controller.project_root / "trust-policy.json"
    policy.write_text("{}", encoding="utf-8")
    roots = []
    original = controller.run_control.create
    def create(**kwargs):
        result = original(**kwargs)
        if kwargs["checkpoint"].get("phase") == "governed-group-authorized":
            roots.append(result["run_id"])
        return result
    def failed(*args, **kwargs):
        raise OSError("controlled reconciliation failure")
    monkeypatch.setattr(controller.run_control, "create", create)
    monkeypatch.setattr(controller.manager, "mark_run_ended", failed)
    with pytest.raises(RuntimeError, match="capacity reconciliation"):
        controller.execute_governed_group(spec, task_plan=plan.as_dict(), placements={"model-0": placement}, approval=True, member_executor=lambda *a, **k: {"answer": "retained"}, generation_observer=lambda: plan.context_generation, evidence_resolver=TrustedEvidenceResolver(store, policy), accepted_producers=set(), attestation_provider=None)
    assert controller.run_control.read(roots[0])["state"] == "failed"
