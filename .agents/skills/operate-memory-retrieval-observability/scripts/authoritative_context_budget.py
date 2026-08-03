#!/usr/bin/env python3
from __future__ import annotations
import argparse,json
from pathlib import Path
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('items'); ap.add_argument('--tokens',type=int,required=True); a=ap.parse_args(); items=json.loads(Path(a.items).read_text()); chosen=[]; used=0
 for x in sorted(items,key=lambda z:(-(z.get('utility',0)*z.get('evidence_priority',1)),z.get('tokens',0))):
  if used+x.get('tokens',0)<=a.tokens: chosen.append(x); used+=x.get('tokens',0)
 print(json.dumps({'budget':a.tokens,'used':used,'selected':chosen,'excluded':[x for x in items if x not in chosen]},indent=2))
if __name__=='__main__': main()
