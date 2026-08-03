#!/usr/bin/env python3
from __future__ import annotations
import argparse,json
from pathlib import Path
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('events'); ap.add_argument('--correlation',required=True); a=ap.parse_args(); rows=[]
 for line in Path(a.events).read_text().splitlines():
  try:
   e=json.loads(line)
   if a.correlation in json.dumps(e,sort_keys=True): rows.append(e)
  except (json.JSONDecodeError, TypeError): continue
 rows.sort(key=lambda x:str(x.get('timestamp',''))); print(json.dumps({'correlation':a.correlation,'events':rows,'gaps':[] if rows else ['No matching events.']},indent=2))
if __name__=='__main__': main()
