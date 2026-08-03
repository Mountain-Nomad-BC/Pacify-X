#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,math,re
from collections import Counter
from pathlib import Path
def toks(s): return re.findall(r'[a-z0-9_]+',s.lower())
def cos(a,b):
 keys=set(a)|set(b); dot=sum(a[k]*b[k] for k in keys); na=math.sqrt(sum(v*v for v in a.values())); nb=math.sqrt(sum(v*v for v in b.values())); return dot/(na*nb) if na and nb else 0
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('corpus'); ap.add_argument('query'); ap.add_argument('-k',type=int,default=5); a=ap.parse_args(); docs=json.loads(Path(a.corpus).read_text()); q=Counter(toks(a.query)); rows=[]
 for d in docs:
  body=d.get('text',''); lexical=sum(1 for t in set(toks(a.query)) if t in body.lower()); vector=cos(q,Counter(toks(body))); score=.55*vector+.45*(lexical/max(1,len(set(toks(a.query))))); rows.append({'id':d.get('id'),'score':score,'text':body,'metadata':d.get('metadata',{})})
 print(json.dumps({'query':a.query,'results':sorted(rows,key=lambda x:(-x['score'],str(x['id'])))[:a.k]},indent=2))
if __name__=='__main__': main()
