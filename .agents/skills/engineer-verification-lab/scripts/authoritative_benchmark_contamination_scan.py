#!/usr/bin/env python3
from __future__ import annotations
import argparse,hashlib,json,re
from pathlib import Path
def grams(s,n=8):
 s=re.sub(r'\s+',' ',s.lower()); return {s[i:i+n] for i in range(max(0,len(s)-n+1))}
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('benchmark'); ap.add_argument('corpus'); a=ap.parse_args(); b=Path(a.benchmark).read_text(errors='ignore'); c=Path(a.corpus).read_text(errors='ignore'); bg,cg=grams(b),grams(c); overlap=len(bg&cg)/max(1,len(bg)); print(json.dumps({'benchmark_sha256':hashlib.sha256(b.encode()).hexdigest(),'corpus_sha256':hashlib.sha256(c.encode()).hexdigest(),'character_ngram_overlap':overlap,'risk':'high' if overlap>.5 else 'medium' if overlap>.1 else 'low','limitations':['Heuristic screen; not proof of training-data membership.']},indent=2))
if __name__=='__main__': main()
