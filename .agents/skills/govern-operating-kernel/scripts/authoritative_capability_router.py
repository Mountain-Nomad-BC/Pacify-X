#!/usr/bin/env python3
from __future__ import annotations
import argparse,json
from pathlib import Path

def main():
 ap=argparse.ArgumentParser(); ap.add_argument('task'); ap.add_argument('registry'); args=ap.parse_args()
 task=json.loads(Path(args.task).read_text()); reg=json.loads(Path(args.registry).read_text()); words=set((task.get('task_type','')+' '+task.get('description','')).lower().replace('_',' ').split())
 scored=[]
 for c in reg.get('skills',[]):
  txt=(c.get('id','')+' '+c.get('summary','')+' '+c.get('category','')).lower().replace('-',' ')
  score=sum(1 for w in words if w in txt)
  if task.get('risk') in ('high','critical') and c.get('security_class') in ('high','critical'): score+=2
  scored.append((score,c))
 selected=[c for s,c in sorted(scored,key=lambda x:(-x[0],x[1].get('id',''))) if s>0][:8]
 print(json.dumps({'selected':selected,'approval_required':task.get('risk') in ('high','critical') or bool(task.get('requires_production_write')),'verification':task.get('verification',[]),'unknowns':[] if selected else ['No capability matched task vocabulary.']},indent=2))
if __name__=='__main__': main()
