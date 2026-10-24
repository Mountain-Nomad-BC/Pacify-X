"""Current release commands require real commissioned pre-execution custody."""
import os
from .gremlin.host_configuration import (resolve_recovery_verifier_from_environment,
                                         load_configured_gremlin_runtime)


def require_release_host(root):
    # This is observational commissioning resolution. It mints no identity/key/grant.
    verifier=resolve_recovery_verifier_from_environment()
    if verifier is None:raise PermissionError("current release requires the independent commissioned Gremlin host verifier")
    return load_configured_gremlin_runtime(root,recovery_verifier=verifier)


def require_release_admission(root,admission_event_id,targets):
    from .operational_gap_ledger import read_snapshot,guard_work_admission
    if type(admission_event_id) is not str or not admission_event_id:
        raise PermissionError("current release requires explicit current work admission")
    snapshot=read_snapshot(root)
    admission=next((row for row in snapshot.get("work_admissions",[]) if row["event_id"]==admission_event_id),None)
    if admission is None:raise PermissionError("release work admission is unavailable")
    for row in admission["effect_scopes"]:
        guard_work_admission(snapshot,gap_id=admission["gap_id"],effect=row["effect"],scope=row["scope"],admission_event_id=admission_event_id)
    for effect,target in targets:
        allowed=next((row["scope"] for row in admission["effect_scopes"] if row["effect"]==effect),())
        if not any(target==scope.rstrip("/") or target.startswith(scope.rstrip("/")+"/") for scope in allowed):
            raise PermissionError("release command lacks exact "+effect+" authority for "+target)
    return admission


def run_release_command(config,name,argv,*,timeout_seconds):
    """Real owner path; unavailable host/admission is rejected before mkdir/spawn."""
    import hashlib,re
    from datetime import datetime,timedelta,timezone
    from pathlib import Path
    from .studio_authority import StudioAuthorityStore
    from .studio_models import digest
    from .execution_context import ExecutionContext
    from .release_source_identity import capture_release_source_identity
    from .release_campaign import release_campaign_status
    from .resource_lifecycle import ResourceManager
    from .process_supervisor import ProcessSupervisor
    from .scope_lease import ScopeLeaseStore
    from .effect_intent import EffectIntentLedger
    from .gremlin.enrollment import enroll_supervised_process
    from .archive_io import reject_path_links
    from .isolated_sandbox import load_sandbox_policy
    root=config.root
    host=require_release_host(root)
    StudioAuthorityStore.open_existing(root)
    if type(timeout_seconds) is not int or not 1<=timeout_seconds<=14400 or not re.fullmatch(r"[A-Za-z0-9_-]{1,120}",name):
        raise ValueError("release command name/budget is invalid")
    if not argv or any(type(x) is not str or not x or "\0" in x for x in argv):raise ValueError("exact non-shell argv required")
    stage=name.split("-",1)[0]
    if stage not in {"sections","full_profile","validate","package","install"}:raise PermissionError("unknown current command stage")
    admission_id=os.environ.get("PX_RELEASE_ADMISSION_EVENT_ID")
    log=config.log_dir/(config.candidate_id+"-"+name+".log")
    relative=log.relative_to(root).as_posix()
    targets=(("execute","runtime"),("read","registry"),("read","policies"),
             ("read",".agentic_engineering_os_px/processing-order"),
             ("write",".agentic_engineering_os_px/runtime-core"),
             ("write",".agentic_engineering_os_px/resource-lifecycle"),("write",relative))
    require_release_admission(root,admission_id,targets)
    observed=release_campaign_status(root,verify_source=True)
    if observed.get("valid") is not True or observed.get("campaign_id")!=config.candidate_id:
        raise PermissionError("release command lacks genuine current source kernel")
    version=observed["identity"]["release_version"]
    source=capture_release_source_identity(root,version=version)
    if source.get("valid") is not True or source["source_freeze"]!=config.source_freeze_reference:
        raise PermissionError("release command source freeze differs")
    binding={"candidate_id":config.candidate_id,"name":name,"argv":list(argv),"source":source}
    key="release-command-"+digest(binding); execution=key
    expiry=(datetime.now(timezone.utc)+timedelta(seconds=timeout_seconds+120)).isoformat()
    context=ExecutionContext(execution,None,execution,str(root),config.candidate_id,1,1,None,
        digest(binding),digest({"timeout_seconds":timeout_seconds}),execution,expiry,
        "native-release-owner",None,execution,gremlin_revision=host.nanny.gremlin_revision)
    reject_path_links(log)
    if log.exists():raise PermissionError("release command output already exists; no replay")
    leases,intents=ScopeLeaseStore(root),EffectIntentLedger(root)
    if intents.fence(key)["disposition"]!="new":raise PermissionError("release command already attempted; no replay")
    lease="lease-"+key
    leases.acquire(lease_id=lease,execution_id=execution,effect="execute",scopes=("runtime",),reason="native current release command",expires_utc=expiry)
    intents.intend(idempotency_key=key,execution_id=execution,effect="execute",scopes=("runtime",))
    log_key=key+"-log";log_lease=lease+"-log"
    leases.acquire(lease_id=log_lease,execution_id=execution,effect="write",scopes=(relative,),reason="native bounded release log publication",expires_utc=expiry)
    intents.intend(idempotency_key=log_key,execution_id=execution,effect="write",scopes=(relative,))
    manager=ResourceManager(root/".agentic_engineering_os_px/runtime-core/release/processes"/digest(binding)/"resources.json")
    supervisor=ProcessSupervisor(manager); custody=None;enrollment=None
    def current(ctx):
        require_release_admission(root,admission_id,targets)
        if ctx!=context or datetime.now(timezone.utc)>=datetime.fromisoformat(expiry) or capture_release_source_identity(root,version=version)!=source:
            raise PermissionError("release command source/authority changed")
        if not any(row.lease_id==lease and row.execution_id==execution for row in leases.active(effect="execute")):
            raise PermissionError("release command native lease is no longer live")
    def before_release(proof):
        nonlocal custody,enrollment
        current(context);custody=proof
        for owned_lease in (lease,log_lease):
            leases.quarantine(lease_id=owned_lease,execution_id=execution,execution_context=context,
                              manager=manager,resource_id=proof.parent_resource_id)
        host.nanny.apply_sandbox_policy(load_sandbox_policy(root))
        enrollment=enroll_supervised_process(host.nanny,manager,proof,execution_id=execution,
            agent_id="native-release-owner",policy_profile="release-command",orchestration_id=config.candidate_id)
    budget={"startup_timeout_seconds":min(30,timeout_seconds),"idle_timeout_seconds":timeout_seconds,
        "total_timeout_seconds":timeout_seconds,"graceful_shutdown_seconds":5,"force_shutdown_seconds":5,
        "stdout_limit_bytes":1048576,"stderr_limit_bytes":1048576}
    result=None
    try:
        current(context)
        result=supervisor.run(argv,cwd=root,action={"action_id":key,"effects":["process"],"allowed_effects":["process"],
            "owned_paths":[str(root)],"target_paths":[],"budget":budget,"limits":budget,"approval":True,
            "policy_override_requested":False},project_id=str(root),run_id=config.candidate_id,lane_id=name,
            creator="native-release-owner",environment={**os.environ,"PYTHONDONTWRITEBYTECODE":"1"},
            execution_context=context,assert_execution_current=current,before_release=before_release)
        if custody is None or enrollment is None or result.resource_id!=custody.parent_resource_id:
            raise PermissionError("native release process correlation is missing")
        host.nanny.close_supervised_execution(execution,manager,result.resource_id)
        closure=manager.read_physical_process_tree_closure(result.resource_id,project_root=root,job_object_id=custody.job_object_id)
        for owned_lease in (lease,log_lease):
            leases.resolve_quarantine(lease_id=owned_lease,execution_id=execution,manager=manager)
        current(context)
        if result.status!="exited" or result.exit_code!=0 or not result.tree_closed:
            raise RuntimeError("native release command failed; actual effect outcome remains fenced")
        if not any(row.lease_id==log_lease and row.execution_id==execution and row.scopes==(relative,) for row in leases.active(effect="write")):
            raise PermissionError("native log publication lease is no longer current")
        reject_path_links(log)
        config.log_dir.mkdir(parents=True,exist_ok=True)
        with log.open("x",encoding="utf-8") as stream:stream.write(result.stdout.text+result.stderr.text)
        receipt={"path":relative,"sha256":hashlib.sha256(log.read_bytes()).hexdigest(),"size":log.stat().st_size,
            "argv":list(argv),"returncode":result.exit_code,"timeout_seconds":timeout_seconds,
            "process_receipt_path":Path(result.receipt_path).relative_to(root).as_posix(),
            "resource_id":result.resource_id,"execution_context":context.as_dict(),"physical_closure":closure,
            "enrollment":enrollment.as_dict(),"source_identity":source,"valid":True}
        current(context)
        intents.commit(idempotency_key=log_key,execution_id=execution,result_sha256=receipt["sha256"])
        leases.release(lease_id=log_lease,execution_id=execution)
        intents.commit(idempotency_key=key,execution_id=execution,result_sha256=digest(receipt))
        leases.release(lease_id=lease,execution_id=execution)
        return receipt
    except BaseException:
        if custody is None:
            for owned_lease in (lease,log_lease):
                leases.quarantine_unresolved(lease_id=owned_lease,execution_id=execution,run_id=config.candidate_id,node_id=name,
                    authority_reference_sha256=context.authority_reference_sha256,attempt=1)
        raise
