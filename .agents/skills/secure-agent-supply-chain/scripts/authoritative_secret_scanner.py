#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,re
from pathlib import Path
PATTERNS={'private_key':r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----','aws_access_key':r'\bAKIA[0-9A-Z]{16}\b','generic_secret':r'(?i)\b(api[_-]?key|secret|password|token)\s*[:=]\s*["\']?[^\s"\']{8,}','github_token':r'\bgh[pousr]_[A-Za-z0-9_]{20,}\b'}
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('root'); a=ap.parse_args(); hits=[]
 for p in Path(a.root).rglob('*'):
  if not p.is_file() or any(x in p.parts for x in ['.git','node_modules','.venv']): continue
  try: s=p.read_text(errors='ignore')
  except Exception: continue
  for kind,pat in PATTERNS.items():
   for m in re.finditer(pat,s): hits.append({'file':str(p),'kind':kind,'line':s.count('\n',0,m.start())+1,'value':'[REDACTED]'})
 print(json.dumps({'findings':hits,'count':len(hits)},indent=2)); raise SystemExit(2 if hits else 0)
if __name__=='__main__': main()
