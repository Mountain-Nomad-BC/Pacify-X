#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,uuid
from datetime import datetime,timezone
from pathlib import Path

def now(): return datetime.now(timezone.utc).isoformat()
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('state'); sub=ap.add_subparsers(dest='cmd',required=True)
 n=sub.add_parser('new'); n.add_argument('--task',required=True)
 t=sub.add_parser('transition'); t.add_argument('to_state'); t.add_argument('--evidence',action='append',default=[])
 sub.add_parser('show'); a=ap.parse_args(); p=Path(a.state)
 if a.cmd=='new': d={'task_id':'task-'+uuid.uuid4().hex[:12],'task':a.task,'state':'RECEIVED','version':1,'history':[{'state':'RECEIVED','at':now()}],'idempotency_keys':[],'artifacts':[],'approvals':[]}
 else:
  d=json.loads(p.read_text())
  if a.cmd=='transition': d['state']=a.to_state; d['version']+=1; d['history'].append({'state':a.to_state,'at':now(),'evidence':a.evidence})
 if a.cmd!='show': p.write_text(json.dumps(d,indent=2,sort_keys=True)+'\n')
 print(json.dumps(d,indent=2))
if __name__=='__main__': main()
