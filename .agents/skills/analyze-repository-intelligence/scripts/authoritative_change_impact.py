#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,re
from pathlib import Path
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('repo_map'); ap.add_argument('--changed',action='append',required=True); a=ap.parse_args(); m=json.loads(Path(a.repo_map).read_text()); changed=set(a.changed); impacted=set(changed); reasons=[]
 mods={Path(x).stem for x in changed}
 for imp in m.get('python_imports',[]):
  if any(mod==imp.get('module','').split('.')[0] or mod in imp.get('module','') for mod in mods): impacted.add(imp['file']); reasons.append({'file':imp['file'],'reason':'imports changed module','evidence':imp})
 tests=[f['path'] for f in m.get('files',[]) if 'test' in f['path'].lower() and any(Path(c).stem in f['path'] for c in changed)]
 print(json.dumps({'changed':sorted(changed),'impacted':sorted(impacted),'candidate_tests':tests,'reasons':reasons,'unknowns':['Runtime reflection and external consumers are not statically resolved.']},indent=2))
if __name__=='__main__': main()
