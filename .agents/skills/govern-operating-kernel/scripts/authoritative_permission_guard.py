#!/usr/bin/env python3
from __future__ import annotations
import argparse,fnmatch,json
from pathlib import Path

def allowed(value,patterns): return any(fnmatch.fnmatch(value,p) for p in patterns)
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('policy'); ap.add_argument('--read'); ap.add_argument('--write'); ap.add_argument('--network'); ap.add_argument('--process'); args=ap.parse_args(); p=json.loads(Path(args.policy).read_text()); checks={}
 for kind,val in [('filesystem_read',args.read),('filesystem_write',args.write),('network',args.network),('process',args.process)]:
  if val is not None: checks[kind]={'value':val,'allowed':allowed(val,p.get(kind,[]))}
 ok=all(x['allowed'] for x in checks.values()); print(json.dumps({'allowed':ok,'checks':checks,'approval':p.get('approval','none')},indent=2)); raise SystemExit(0 if ok else 3)
if __name__=='__main__': main()
