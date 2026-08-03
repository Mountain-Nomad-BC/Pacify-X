#!/usr/bin/env python3
from __future__ import annotations
import argparse,json
from pathlib import Path
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('cases'); a=ap.parse_args(); cases=json.loads(Path(a.cases).read_text()); vals=[]
 for c in cases:
  got=c.get('retrieved_ids',[]); rel=set(c.get('relevant_ids',[])); hit=len(rel&set(got)); vals.append({'id':c.get('id'),'recall':hit/max(1,len(rel)),'precision':hit/max(1,len(got)),'citation_supported':bool(c.get('citation_supported',False))})
 print(json.dumps({'cases':vals,'mean_recall':sum(x['recall'] for x in vals)/max(1,len(vals)),'mean_precision':sum(x['precision'] for x in vals)/max(1,len(vals))},indent=2))
if __name__=='__main__': main()
