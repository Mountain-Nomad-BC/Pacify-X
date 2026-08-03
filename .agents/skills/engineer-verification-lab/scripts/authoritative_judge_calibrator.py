#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,json,statistics
from pathlib import Path
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('csv'); a=ap.parse_args(); rows=list(csv.DictReader(Path(a.csv).open())); total=len(rows); agree=sum(r.get('human')==r.get('judge') for r in rows); swaps=[r for r in rows if r.get('pair_id') and r.get('position')]
 by={}
 for r in swaps: by.setdefault(r['pair_id'],{})[r['position']]=r.get('judge')
 unstable=sum(1 for x in by.values() if len(set(x.values()))>1)
 print(json.dumps({'samples':total,'human_agreement':agree/total if total else None,'position_pairs':len(by),'position_instability':unstable/len(by) if by else None,'accepted':bool(total and agree/total>=0.8 and (not by or unstable/len(by)<=0.1))},indent=2))
if __name__=='__main__': main()
