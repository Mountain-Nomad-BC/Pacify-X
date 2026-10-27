"""Review-bound, non-deleting source integration with retained preimages.

Plans are diagnosis, never permission to bulk overlay. Each file requires an
explicit semantic disposition. Publication is atomic PER FILE, not a multi-file
transaction; interrupted work retains its recovery journal and all preimages.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from runtime.archive_io import portable_member_name, reject_path_links
from runtime.secure_publish import atomic_write_bytes, read_physical_bytes
from runtime.source_boundary import classify_path
from runtime.resource_lifecycle import ResourceManager
from runtime.file_lock import FileLock


def digest(path: Path) -> str | None:
    try:
        return hashlib.sha256(read_physical_bytes(path)).hexdigest()
    except FileNotFoundError:
        return None


def eligible(relative: str) -> bool:
    try:
        portable_member_name(relative, allow_directory=False)
    except (ValueError, TypeError):
        return False
    parts = relative.split('/')
    policy = json.loads((ROOT/'policies/release-artifact-policy.json').read_text(encoding='utf-8'))
    if len(parts) == 1 and relative not in policy['product_root_files']: return False
    if parts[0] not in policy['product_roots'] and len(parts) > 1: return False
    lowered = [part.casefold() for part in parts]
    if 'memory' in lowered or any(part.startswith('.env') for part in lowered): return False
    if any(part in {'.git','node_modules','__pycache__','build','dist','.agentic_engineering_os_px','.engineering-bootstrap'} for part in lowered): return False
    if relative.startswith(('evidence/','.px/preserved-','registry/operational_gap_ledger','docs/repair/')): return False
    if relative.endswith(('.lock','.pyc','.log','.out.txt','.err.txt')): return False
    # Generated/custody bytes cannot be made authoritative by copying them.
    return classify_path(relative)['classification'] in {'authored','vendored'}


def make_plan(candidate: Path, target: Path, comparison: dict) -> dict:
    files, excluded = [], []
    for relative in sorted(set(comparison['diff']['changed'] + comparison['diff']['candidate_only'])):
        if not eligible(relative):
            excluded.append(relative); continue
        after, before = digest(candidate/relative), digest(target/relative)
        if after is None: raise ValueError(f'Source missing: {relative}')
        if after != before:
            files.append(dict(path=relative,before_sha256=before,after_sha256=after,
                              disposition='REVIEW_REQUIRED',review_note=''))
    return dict(schema_version='px.rollout-source-overlay/2',candidate=str(candidate),target=str(target),files=files,
                excluded=excluded,preserved_target_only=comparison['diff']['incumbent_only'],deletes=[],release_certified=False)


def apply_plan(plan: dict) -> dict:
    candidate, target = Path(plan['candidate']).absolute(), Path(plan['target']).absolute()
    reject_path_links(candidate); reject_path_links(target)
    candidate, target = candidate.resolve(strict=True), target.resolve(strict=True)
    if candidate == target or candidate in target.parents or target in candidate.parents:
        raise ValueError('Source and target trees must be independent')
    marker = target/'.git'; reject_path_links(marker)
    if not marker.exists(): raise ValueError('Target must be an isolated Git worktree')
    if plan.get('deletes'): raise ValueError('Source integration never deletes')
    files=plan['files']
    if not isinstance(files,list) or len(files)>10000: raise ValueError('Invalid source denominator')
    seen=set(); images={}; originals={}; total_bytes=0
    # Validate the ENTIRE denominator before creating any target source file.
    for item in files:
        rel=item['path']
        if not eligible(rel): raise ValueError(f'Unsafe or non-source path: {rel}')
        key=rel.casefold()
        if key in seen: raise ValueError('Duplicate or aliased target path')
        seen.add(key)
        if item.get('disposition') not in {'port','merge'} or not str(item.get('review_note','')).strip():
            raise ValueError(f'Semantic review required: {rel}')
        if item['disposition']=='merge': raise ValueError('Merged bytes must be reviewed in a separate candidate tree')
        raw=read_physical_bytes(candidate/rel)
        after=hashlib.sha256(raw).hexdigest()
        before=digest(target/rel)
        if after!=item['after_sha256'] or before!=item['before_sha256']:
            raise ValueError(f'Concurrent change: {rel}')
        images[rel]=raw; originals[rel]=None if before is None else read_physical_bytes(target/rel)
        total_bytes += len(raw) + len(originals[rel] or b'')
        if total_bytes > 64*1024*1024: raise ValueError('Source integration total byte budget exceeded')
    owned=target/'.tmp/rollout-integration';reject_path_links(owned);owned.mkdir(parents=True,exist_ok=True);reject_path_links(owned)
    manager=ResourceManager(owned/'resources.json')
    record=manager.create_workspace(owned,project_id='source-integration',run_id='reviewed-plan',lane_id='source-custody',creator='integration-plan',retention_required=True)
    workspace=Path(record.path)
    journal=dict(schema_version='px.source-integration-recovery/1',candidate=str(candidate),target=str(target),files=files,
                 published=[],completed=False,atomicity='per-file; interrupted partial integration requires review',release_certified=False)
    for index,item in enumerate(files):
        old=originals[item['path']]
        if old is not None: atomic_write_bytes(workspace/f'{index:05d}.before',old)
    recovery=workspace/'recovery.json';atomic_write_bytes(recovery,json.dumps(journal,indent=2).encode())
    try:
        # Serialize cooperative apply commands. External editors are not governed
        # by this lock: preimage comparisons still run immediately per file.
        with FileLock(owned/'writer.lock'):
            for item in files:
                rel=item['path']
                if digest(candidate/rel)!=item['after_sha256'] or digest(target/rel)!=item['before_sha256']:
                    raise ValueError(f'Concurrent change immediately before publication: {rel}')
                atomic_write_bytes(target/rel,images[rel])
                if digest(target/rel)!=item['after_sha256']: raise ValueError(f'Publication verification failed: {rel}')
                journal['published'].append(rel)
                atomic_write_bytes(recovery,json.dumps(journal,indent=2).encode())
        journal['completed']=True
        atomic_write_bytes(recovery,json.dumps(journal,indent=2).encode())
        return dict(completed=True,recovery=str(recovery),published=journal['published'],deletes=[],release_certified=False)
    except BaseException as error:
        journal['failure']=str(error)
        atomic_write_bytes(recovery,json.dumps(journal,indent=2).encode())
        raise


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--candidate',type=Path);p.add_argument('--target',type=Path)
    p.add_argument('--comparison',type=Path);p.add_argument('--output',type=Path)
    p.add_argument('--apply-plan',type=Path)
    args=p.parse_args()
    if args.apply_plan:
        print(json.dumps(apply_plan(json.loads(read_physical_bytes(args.apply_plan)))));return
    if not all([args.candidate,args.target,args.comparison,args.output]): p.error('planning requires candidate,target,comparison,output')
    plan=make_plan(args.candidate.resolve(strict=True),args.target.resolve(strict=True),json.loads(read_physical_bytes(args.comparison)))
    with args.output.open('x',encoding='utf-8') as f:json.dump(plan,f,indent=2)
    print(json.dumps({'review_required':len(plan['files']),'deletes':0,'applied':False}))

if __name__=='__main__': main()
