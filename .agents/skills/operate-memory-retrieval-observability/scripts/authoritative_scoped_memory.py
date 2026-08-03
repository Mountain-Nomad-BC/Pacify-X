#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,uuid
from datetime import datetime,timezone
from pathlib import Path
def load(p): return json.loads(p.read_text()) if p.exists() else {'records':[]}
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('db'); sub=ap.add_subparsers(dest='cmd',required=True)
 w=sub.add_parser('write'); w.add_argument('--scope',required=True); w.add_argument('--type',choices=['working','episodic','semantic','procedural'],required=True); w.add_argument('--content',required=True); w.add_argument('--source',required=True); w.add_argument('--verified',action='store_true')
 q=sub.add_parser('query'); q.add_argument('--scope',required=True); q.add_argument('--contains',default='')
 d=sub.add_parser('delete-scope'); d.add_argument('--scope',required=True); a=ap.parse_args(); p=Path(a.db); db=load(p)
 if a.cmd=='write':
  if a.type in ('semantic','procedural') and not a.verified: raise SystemExit('verified flag required for durable trusted memory')
  r={'id':'mem-'+uuid.uuid4().hex[:12],'scope':a.scope,'type':a.type,'content':a.content,'source':a.source,'verified':a.verified,'created_at':datetime.now(timezone.utc).isoformat()}; db['records'].append(r); p.write_text(json.dumps(db,indent=2,sort_keys=True)+'\n'); print(json.dumps(r,indent=2))
 elif a.cmd=='query': print(json.dumps({'records':[r for r in db['records'] if r['scope']==a.scope and a.contains.lower() in r['content'].lower()]},indent=2))
 else:
  before=len(db['records']); db['records']=[r for r in db['records'] if r['scope']!=a.scope]; p.write_text(json.dumps(db,indent=2,sort_keys=True)+'\n'); print(json.dumps({'deleted':before-len(db['records']),'scope':a.scope},indent=2))
if __name__=='__main__': main()
