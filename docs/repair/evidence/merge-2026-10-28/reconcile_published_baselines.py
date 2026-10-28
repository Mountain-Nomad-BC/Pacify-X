"""Retain both Git-stage projections; restore a parseable historical baseline.

This does not run generators, refresh hashes or issue currentness/release proof.
Every Git child has its own native owned process receipt.
"""
import sys,os,json,hashlib,shutil
from pathlib import Path
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'pyproject.toml').is_file())
sys.path.insert(0,str(ROOT))
from runtime.resource_lifecycle import ResourceManager,RunState
from runtime.process_supervisor import ProcessSupervisor
workspace=Path(os.environ['TMPDIR']);assert (workspace/'planned-command.json').is_file()
manager=ResourceManager(workspace/'git-child-resources.json')
files=['artifact_reachability.json','build_claims.json','contract_ownership.json','effect_surface_ownership.json','provider_route_scan.json','python_dependency_ownership.json','python_surface_ownership.json','test_group_index.json']
directory=ROOT/'docs/repair/evidence/merge-2026-10-28';rows=[];images={}
for name in files:
 path='registry/'+name
 (directory/(name+'.conflicted.txt')).write_bytes((ROOT/path).read_bytes())
 row={'path':path,'baseline_current':False,'generator_executed':False,'stages':{}}
 for stage in (2,3):
  run='merge-projection-'+name+'-'+str(stage)
  budget=dict(startup_timeout_seconds=10,idle_timeout_seconds=20,total_timeout_seconds=30,graceful_shutdown_seconds=2,force_shutdown_seconds=5,stdout_limit_bytes=16*1024*1024,stderr_limit_bytes=65536)
  action=dict(action_id=run,effects=['process'],allowed_effects=['process'],owned_paths=[str(ROOT)],target_paths=[str(ROOT)],budget=budget,limits=budget,approval=True,policy_override_requested=False)
  result=ProcessSupervisor(manager).run([shutil.which('git'),'show',f':{stage}:{path}'],cwd=ROOT,action=action,project_id='merge-recovery',run_id=run,lane_id='projection-custody',creator='codex')
  assert result.exit_code==0 and result.tree_closed and not manager.ledger.get(result.resource_id).active
  assert not result.stdout.truncated and not result.stderr.truncated
  image=result.stdout.text.encode('utf-8');json.loads(image)
  dest=directory/(name+f'.stage{stage}.json.txt');dest.write_bytes(image)
  images[path,stage]=image
  row['stages'][str(stage)]={'archive':dest.relative_to(ROOT).as_posix(),'sha256':hashlib.sha256(image).hexdigest(),'receipt':result.receipt_path,'tree_closed':True,'resource_inactive':True}
  manager.mark_run_ended(run,RunState.COMPLETED,retain_reason='Retain both published baseline branch images and Git process custody; not regenerated/current proof.')
 rows.append(row)
# Entire read/parse/custody denominator is verified before any baseline write.
for name in files:
 path='registry/'+name;(ROOT/path).write_bytes(images[path,2])
(directory/'published-baseline-resolution.json').write_text(json.dumps({'decision':'Restore complete repair-branch published snapshots from stage2; retain complete incoming stage3 and conflicted images. These are explicitly stale historical baselines. Recompute once only after repair freeze through native owners; source/test-profile denominator reconciliation remains separate. No currentness or passing certification manufactured.','records':rows},indent=2),encoding='utf-8')
print('Retained both stages and restored 8 parseable, explicitly noncurrent published baselines')
