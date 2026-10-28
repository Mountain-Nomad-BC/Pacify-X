import sys,json,hashlib,os
from pathlib import Path
ROOT=next(parent for parent in Path(__file__).resolve().parents if (parent/'pyproject.toml').is_file() and (parent/'runtime').is_dir())
sys.path.insert(0,str(ROOT))
from runtime.process_supervisor import ProcessSupervisor
from runtime.resource_lifecycle import ResourceManager, RunState
name=sys.argv[1]; args=sys.argv[2:]
owned=ROOT/'.tmp/resume10/owned';owned.mkdir(parents=True,exist_ok=True)
manager=ResourceManager(owned/'resources.json')
record=manager.create_workspace(owned,project_id='resume10',run_id=name,lane_id='focused-repair',creator='codex',retention_required=True)
w=Path(record.path)
import shutil
command=([shutil.which('node'),*args[1:]] if args and args[0]=='--node' else [sys.executable,*args])
budget=dict(startup_timeout_seconds=20,idle_timeout_seconds=45,total_timeout_seconds=120,graceful_shutdown_seconds=2,force_shutdown_seconds=5,stdout_limit_bytes=1048576,stderr_limit_bytes=1048576)
action=dict(action_id=name,effects=['process'],allowed_effects=['process'],owned_paths=[str(ROOT)],target_paths=[str(ROOT)],budget=budget,limits=budget,approval=True,policy_override_requested=False)
(w/'planned-command.json').write_text(json.dumps({'command':command,'cwd':str(ROOT),'action':action},indent=2))
result=ProcessSupervisor(manager).run(command,cwd=ROOT,action=action,project_id='resume10',run_id=name,lane_id='focused-repair',creator='codex',environment={**os.environ,'TMP':str(w),'TEMP':str(w),'TMPDIR':str(w)})
if result.tree_closed and not manager.ledger.get(result.resource_id).active:
 manager.mark_run_ended(name,RunState.COMPLETED if result.exit_code==0 else RunState.FAILED,retain_reason='Retained focused repair proof, not release certification.')
log=ROOT/'docs/repair/evidence'/('resume10-'+name+'.log')
log.write_text(result.stdout.text+'\n'+result.stderr.text,encoding='utf-8')
proof={'command':command,'exit_code':result.exit_code,'tree_closed':result.tree_closed,'resource_inactive':not manager.ledger.get(result.resource_id).active,'receipt':result.receipt_path,'workspace':str(w),'log':str(log),'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest()}
(ROOT/'docs/repair/evidence'/('resume10-'+name+'.json')).write_text(json.dumps(proof,indent=2))
print(json.dumps(proof));print(result.stdout.text[-1400:].encode('ascii','backslashreplace').decode());print(result.stderr.text[-500:].encode('ascii','backslashreplace').decode())
assert result.tree_closed and not manager.ledger.get(result.resource_id).active
sys.exit(result.exit_code if result.exit_code is not None else 99)
