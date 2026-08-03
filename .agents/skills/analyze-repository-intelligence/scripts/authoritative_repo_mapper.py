#!/usr/bin/env python3
from __future__ import annotations
import argparse,ast,hashlib,json,os
from collections import Counter
from pathlib import Path
SKIP={'.git','node_modules','.venv','venv','dist','build','__pycache__'}
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('root'); ap.add_argument('--out'); a=ap.parse_args(); root=Path(a.root).resolve(); files=[]; langs=Counter(); symbols=[]; imports=[]
 for p in sorted(root.rglob('*')):
  if not p.is_file() or any(x in SKIP for x in p.parts): continue
  rel=str(p.relative_to(root)); ext=p.suffix.lower() or '[none]'; langs[ext]+=1
  rec={'path':rel,'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}; files.append(rec)
  if p.suffix=='.py':
   try:
    t=ast.parse(p.read_text(encoding='utf-8'))
    for n in ast.walk(t):
     if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)): symbols.append({'file':rel,'name':n.name,'kind':type(n).__name__,'line':n.lineno})
     elif isinstance(n,(ast.Import,ast.ImportFrom)): imports.append({'file':rel,'module':getattr(n,'module',None) or ','.join(x.name for x in n.names),'line':n.lineno})
   except Exception as e: rec['parse_error']=str(e)
 out={'root':str(root),'file_count':len(files),'languages':dict(langs),'files':files,'python_symbols':symbols,'python_imports':imports,'limitations':['Dynamic dispatch and non-Python symbol extraction require language adapters.']}
 s=json.dumps(out,indent=2,sort_keys=True)+'\n'; Path(a.out).write_text(s) if a.out else print(s,end='')
if __name__=='__main__': main()
