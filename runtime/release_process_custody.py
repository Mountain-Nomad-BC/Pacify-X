"""Current release commands require real commissioned pre-execution custody."""
import os
from .gremlin.host_configuration import (resolve_recovery_verifier_from_environment,
                                         load_configured_gremlin_runtime)


def require_release_host(root, *, supervisor_lookup=None):
    # Observational commissioning resolution; never create identity, key or approval.
    verifier = resolve_recovery_verifier_from_environment()
    if verifier is None:
        raise PermissionError("current release requires the independent commissioned Gremlin host verifier")
    if os.name != "nt":
        raise PermissionError("current release requires native Windows process-tree observation")
    from .gremlin.observers import ObserverSet
    from .gremlin.host_process_observer import make_process_tree_poller
    from .gremlin.host_enforcement_backend import ProcessSupervisorEnforcementBackend
    from .isolated_sandbox import load_sandbox_policy
    observers = ObserverSet()
    observers.register("process_tree", make_process_tree_poller())
    host = load_configured_gremlin_runtime(root, recovery_verifier=verifier, observers=observers,
        supervisor_backend=ProcessSupervisorEnforcementBackend(supervisor_lookup=supervisor_lookup or (lambda key: None)))
    policy = load_sandbox_policy(root)
    if policy is None:
        raise PermissionError("current release requires its explicit native sandbox policy")
    host.nanny.apply_sandbox_policy(policy)
    return host


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
        from pathlib import Path
        from .archive_io import reject_path_links
        def physical(value):
            if type(value) is not str or not value.strip() or "\0" in value:
                raise PermissionError("release scope must be a nonempty physical path")
            path = Path(value)
            path = path if path.is_absolute() else Path(root) / path
            try:
                reject_path_links(path)
                return path.resolve()
            except (OSError, ValueError) as error:
                raise PermissionError("release scope traverses an unsafe path") from error
        target_path = physical(target)
        if not any(target_path == (scope_path := physical(scope)) or target_path.is_relative_to(scope_path)
                   for scope in allowed):
            raise PermissionError("release command lacks exact "+effect+" authority for "+target)
    return admission


def release_command_effects(config, name, argv):
    """Exact additional capabilities of the closed current package/install commands."""
    from pathlib import Path
    from .release_source_identity import release_private_installation_relative
    private = config.root / release_private_installation_relative(config.candidate_id)
    targets = [("execute", str(Path(argv[0]).resolve()))]
    claims = []
    if name == "package-build":
        writes = (config.artifact.relative_to(config.root).as_posix(), "extension/SHA256SUMS.txt")
        targets += [("read", "extension"), ("execute", "extension/scripts/package-vsix.js")]
        targets += [("write", scope) for scope in writes]
        claims.append(("package-output", "write", writes))
    elif name in {"install-realize", "install-list"}:
        profile = private / "user-data"
        scope = private if name == "install-realize" else profile
        targets += [("read", str(config.code_command)),
                    ("read", str(config.installed_dir.parent)), ("write", str(scope))]
        if os.name == "nt":
            from scripts.run_release_stage_owner import vscode_cli_entrypoint
            targets.append(("read", str(vscode_cli_entrypoint(config.code_command))))
        claims.append(("installation-output", "write", (scope.relative_to(config.root).as_posix(),)))
        if name == "install-realize":
            targets.append(("read", str(config.artifact)))
            claims.append(("installation", "install", (private.relative_to(config.root).as_posix(),)))
    return tuple(targets), tuple(claims)


def assert_release_command_argv(config, name, argv):
    """Current command roles are closed; a renamed command cannot evade install authority."""
    import sys, shutil
    from pathlib import Path
    from .release_source_identity import release_private_installation_relative
    tail = None
    executable = Path(sys.executable).resolve()
    if name.startswith("sections-"):
        tail = ["-B", "-m", "runtime.cli", "test-section", "run", name[len("sections-"):]]
    elif name == "full_profile":
        tail = ["-B", "-m", "runtime.cli", "test-profile", "run", "full"]
    elif name == "validate":
        tail = ["-B", "-m", "runtime.cli", "validate"]
    elif name == "package-build":
        node = shutil.which("node")
        if not node:
            raise PermissionError("current package requires native Node")
        executable = Path(node).resolve()
        tail = [str(config.root / "extension/scripts/package-vsix.js")]
    elif name in {"install-realize", "install-list"}:
        executable = config.code_command.resolve()
        private = config.root / release_private_installation_relative(config.candidate_id)
        from scripts.run_release_stage_owner import vscode_cli_entrypoint
        tail = ([str(vscode_cli_entrypoint(config.code_command))] if os.name == "nt" else [])
        tail += ["--user-data-dir", str(private / "user-data"), "--extensions-dir", str(private / "extensions")]
        tail += (["--install-extension", str(config.artifact)] if name == "install-realize"
                 else ["--list-extensions", "--show-versions"])
    if tail is None or Path(argv[0]).resolve() != executable or list(argv[1:]) != tail:
        raise PermissionError("current release command differs from its closed native owner role")


def run_release_command(config, name, argv, *, timeout_seconds):
    """Refuse unavailable custody before allocation; retain ambiguity after launch."""
    import hashlib, re
    from datetime import datetime, timedelta, timezone
    from pathlib import Path
    from .studio_authority import StudioAuthorityStore
    from .studio_models import digest
    from .execution_context import ExecutionContext
    from .release_source_identity import capture_release_source_identity, release_private_installation_relative
    from .release_campaign import release_campaign_status
    from .resource_lifecycle import ResourceManager
    from .process_supervisor import ProcessSupervisor
    from .scope_lease import ScopeLeaseStore
    from .effect_intent import EffectIntentLedger
    from .gremlin.enrollment import enroll_supervised_process
    from .archive_io import reject_path_links
    from .isolated_sandbox import load_sandbox_policy
    root = config.root
    manager = None
    def native_job(job_id):
        if manager is not None:
            for resource_id, job in tuple(manager._process_jobs.items()):
                if job.custody_id == job_id and manager.verify_owned_job(resource_id).job_object_id == job_id:
                    return job
        return None
    host = require_release_host(root, supervisor_lookup=native_job)
    StudioAuthorityStore.open_existing(root)
    if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 14400 or not re.fullmatch(r"[A-Za-z0-9_-]{1,120}", name):
        raise ValueError("release command name/budget is invalid")
    if not argv or any(type(x) is not str or not x or "\0" in x for x in argv):
        raise ValueError("exact non-shell argv required")
    stage = name.split("-", 1)[0]
    if stage not in {"sections", "full_profile", "validate", "package", "install"}:
        raise PermissionError("unknown current command stage")
    assert_release_command_argv(config, name, argv)
    admission_id = os.environ.get("PX_RELEASE_ADMISSION_EVENT_ID")
    log = config.log_dir / (config.candidate_id + "-" + name + ".log")
    relative = log.relative_to(root).as_posix()
    extra_targets, extra_claims = release_command_effects(config, name, argv)
    targets = (("execute", "runtime"), ("read", "registry"), ("read", "policies"),
               ("read", ".agentic_engineering_os_px/processing-order"),
               ("write", ".agentic_engineering_os_px/runtime-core"),
               ("write", ".agentic_engineering_os_px/resource-lifecycle"), ("write", relative), *extra_targets)
    install_admission = os.environ.get("PX_RELEASE_INSTALL_ADMISSION_EVENT_ID")
    install_target = root / release_private_installation_relative(config.candidate_id)
    def admit():
        require_release_admission(root, admission_id, targets)
        if name == "install-realize":
            require_release_admission(root, install_admission, (("install", str(install_target)),))
    admit()
    observed = release_campaign_status(root, verify_source=True)
    if observed.get("valid") is not True or observed.get("campaign_id") != config.candidate_id:
        raise PermissionError("release command lacks genuine current source kernel")
    version = observed["identity"]["release_version"]
    source = capture_release_source_identity(root, version=version)
    if source.get("valid") is not True or source["source_freeze"] != config.source_freeze_reference:
        raise PermissionError("release command source freeze differs")
    binding = {"candidate_id": config.candidate_id, "name": name, "argv": list(argv), "source": source}
    key = "release-command-" + digest(binding)
    execution = key
    expiry = (datetime.now(timezone.utc) + timedelta(seconds=timeout_seconds + 120)).isoformat()
    context = ExecutionContext(execution, None, execution, str(root), config.candidate_id, 1, 1, None,
        digest(binding), digest({"timeout_seconds": timeout_seconds}), execution, expiry,
        "native-release-owner", None, execution, gremlin_revision=host.nanny.gremlin_revision)
    reject_path_links(log)
    if log.exists():
        raise PermissionError("release command output already exists; no replay")
    leases, intents = ScopeLeaseStore(root), EffectIntentLedger(root)
    execute_scopes = ("runtime", *(scope for effect, scope in extra_targets if effect == "execute"))
    specifications = (("execute", "execute", execute_scopes),
                      ("log", "write", (relative,)), *extra_claims)
    owned = [("lease-" + key + "-" + suffix, key + "-" + suffix, effect,
              tuple(sorted({scope.replace(chr(92), "/") for scope in scopes})))
             for suffix, effect, scopes in specifications]
    if intents.fence(key)["disposition"] != "new" or any(intents.fence(intent)["disposition"] != "new" for _, intent, _, _ in owned):
        raise PermissionError("release command already attempted; no replay")
    manager = ResourceManager(root / ".agentic_engineering_os_px/runtime-core/release/processes" / digest(binding) / "resources.json")
    supervisor = ProcessSupervisor(manager)
    custody = enrollment = None
    acquired = []
    intended = set()
    launch_invoked = False
    def current(ctx):
        admit()
        try:
            host.nanny.observers.observers["process_tree"]()
        except Exception as error:
            host.nanny.observers.health.process_tree = False
            raise PermissionError("native release process observer is unavailable") from error
        host.nanny.observers.health.process_tree = True
        observed_source = capture_release_source_identity(root, version=version)
        if ctx != context or datetime.now(timezone.utc) >= datetime.fromisoformat(expiry) or observed_source != source:
            detail = observed_source.get("errors", ["identity or authority differs"])
            raise PermissionError("release command source/authority changed: " + str(detail))
        for lease, _, effect, scopes in owned:
            if not any(row.lease_id == lease and row.execution_id == execution and row.scopes == scopes
                       for row in leases.active(effect=effect)):
                raise PermissionError("release command native lease is no longer live")
    def before_release(proof):
        nonlocal custody, enrollment
        current(context)
        custody = proof
        if native_job(proof.job_object_id) is None:
            raise PermissionError("native release enforcement is not bound to its exact Job")
        for lease, _, _, _ in owned:
            leases.quarantine(lease_id=lease, execution_id=execution, execution_context=context,
                              manager=manager, resource_id=proof.parent_resource_id)
        host.nanny.apply_sandbox_policy(load_sandbox_policy(root))
        enrollment = enroll_supervised_process(host.nanny, manager, proof, execution_id=execution,
            agent_id="native-release-owner", policy_profile="release-command", orchestration_id=config.candidate_id)
    budget = {"startup_timeout_seconds": min(30, timeout_seconds), "idle_timeout_seconds": timeout_seconds,
        "total_timeout_seconds": timeout_seconds, "graceful_shutdown_seconds": 5, "force_shutdown_seconds": 5,
        "stdout_limit_bytes": 1048576, "stderr_limit_bytes": 1048576}
    environment = {k: v for k, v in os.environ.items() if k not in {"NODE_OPTIONS", "NODE_PATH"}}
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    if stage == "install":
        environment = {k: v for k, v in environment.items() if not k.upper().startswith("VSCODE_")}
        if os.name == "nt":
            environment["ELECTRON_RUN_AS_NODE"] = "1"
    try:
        for lease, intent, effect, scopes in owned:
            leases.acquire(lease_id=lease, execution_id=execution, effect=effect, scopes=scopes,
                           reason="native current release command", expires_utc=expiry)
            acquired.append(lease)
            intents.intend(idempotency_key=intent, execution_id=execution, effect=effect, scopes=scopes)
            intended.add(intent)
        current(context)
        launch_invoked = True
        result = supervisor.run(argv, cwd=root, action={"action_id": key, "effects": ["process"], "allowed_effects": ["process"],
            "owned_paths": [str(root)], "target_paths": [], "budget": budget, "limits": budget, "approval": True,
            "policy_override_requested": False}, project_id=str(root), run_id=execution, lane_id=name,
            creator="native-release-owner", environment=environment,
            execution_context=context, assert_execution_current=current, before_release=before_release)
        if custody is None or enrollment is None or result.resource_id != custody.parent_resource_id:
            raise PermissionError("native release process correlation is missing")
        host.nanny.close_supervised_execution(execution, manager, result.resource_id)
        closure = manager.read_physical_process_tree_closure(result.resource_id, project_root=root, job_object_id=custody.job_object_id)
        current(context)
        if (result.status != "exited" or result.exit_code != 0 or not result.tree_closed
            or result.stdout.truncated or result.stderr.truncated):
            raise RuntimeError("native release command failed or exceeded output budget; outcome remains fenced")
        reject_path_links(log)
        config.log_dir.mkdir(parents=True, exist_ok=True)
        with log.open("x", encoding="utf-8") as stream:
            stream.write(result.stdout.text + result.stderr.text)
        receipt = {"path": relative, "sha256": hashlib.sha256(log.read_bytes()).hexdigest(), "size": log.stat().st_size,
            "argv": list(argv), "returncode": result.exit_code, "timeout_seconds": timeout_seconds,
            "process_receipt_path": Path(result.receipt_path).relative_to(root).as_posix(),
            "resource_id": result.resource_id, "execution_context": context.as_dict(), "physical_closure": closure,
            "admission_event_id": admission_id,
            "install_admission_event_id": install_admission if name == "install-realize" else None,
            "enrollment": enrollment.as_dict(), "source_identity": source, "valid": True}
        current(context)
        # Retain exclusion through host log publication. Resolved tombstones are
        # intentionally not active leases and must never authorize another write.
        for lease in acquired:
            leases.resolve_quarantine(lease_id=lease, execution_id=execution, manager=manager)
        for lease, intent, _, _ in reversed(owned):
            intents.commit(idempotency_key=intent, execution_id=execution, result_sha256=digest(receipt))
            leases.release(lease_id=lease, execution_id=execution)
        admit()
        if capture_release_source_identity(root, version=version) != source:
            raise PermissionError("release source changed after effect settlement")
        return receipt
    except BaseException as error:
        for lease, intent, _, _ in reversed(owned):
            if lease not in acquired:
                continue
            if not launch_invoked:
                if intent in intended:
                    intents.fail(idempotency_key=intent, execution_id=execution, failure_type="prelaunch:" + type(error).__name__)
                leases.release(lease_id=lease, execution_id=execution)
            elif custody is None:
                leases.quarantine_unresolved(lease_id=lease, execution_id=execution, run_id=config.candidate_id, node_id=name,
                    authority_reference_sha256=context.authority_reference_sha256, attempt=1)
        raise
