#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, uuid
from datetime import datetime, timezone
from pathlib import Path

def load(p): return json.loads(Path(p).read_text()) if Path(p).exists() else {'claims':[]}
def save(p,d): Path(p).write_text(json.dumps(d,indent=2,sort_keys=True)+'\n')
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('ledger'); sub=ap.add_subparsers(dest='cmd',required=True)
 a=sub.add_parser('add'); a.add_argument('statement'); a.add_argument('--type',default='inference'); a.add_argument('--confidence',type=float,default=0.5); a.add_argument('--evidence',action='append',default=[])
 v=sub.add_parser('verify'); v.add_argument('claim_id'); v.add_argument('--status',choices=['supported','verified','conflicted','rejected','stale'],required=True)
 sub.add_parser('list'); args=ap.parse_args(); d=load(args.ledger)
 if args.cmd=='add':
  c={'claim_id':'claim-'+uuid.uuid4().hex[:12],'statement':args.statement,'claim_type':args.type,'status':'unverified','evidence':[{'locator':x} for x in args.evidence],'assumptions':[],'conflicts':[],'confidence':max(0,min(1,args.confidence)),'verified_at':None,'stale_after':None}; d['claims'].append(c); save(args.ledger,d); print(json.dumps(c,indent=2))
 elif args.cmd=='verify':
  c=next((x for x in d['claims'] if x['claim_id']==args.claim_id),None)
  if not c: raise SystemExit('claim not found')
  c['status']=args.status; c['verified_at']=datetime.now(timezone.utc).isoformat(); save(args.ledger,d); print(json.dumps(c,indent=2))
 else: print(json.dumps(d,indent=2))
if __name__=='__main__': main()
