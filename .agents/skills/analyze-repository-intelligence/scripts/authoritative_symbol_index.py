#!/usr/bin/env python3
from __future__ import annotations
import argparse,ast,json
from pathlib import Path
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('root'); ap.add_argument('--query'); a=ap.parse_args(); rows=[]
 for p in sorted(Path(a.root).rglob('*.py')):
  if any(x in p.parts for x in ['.git','.venv','venv','__pycache__']): continue
  try:
   t=ast.parse(p.read_text(encoding='utf-8'))
   for n in ast.walk(t):
    if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):
     row={'name':n.name,'kind':type(n).__name__,'file':str(p),'line':n.lineno};
     if not a.query or a.query.lower() in n.name.lower(): rows.append(row)
  except (OSError, UnicodeError, SyntaxError): continue
 print(json.dumps({'symbols':rows,'count':len(rows)},indent=2))
if __name__=='__main__': main()
