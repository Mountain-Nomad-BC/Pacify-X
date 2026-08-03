#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,re
SENSITIVE=[r'(?i)password\s*[:=]',r'(?i)api[_ -]?key\s*[:=]',r'\b\d{3}-\d{2}-\d{4}\b']
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('candidate'); a=ap.parse_args(); c=json.loads(open(a.candidate).read()); reasons=[]
 if not c.get('source'): reasons.append('missing provenance')
 if c.get('type') in ('semantic','procedural') and not c.get('verified'): reasons.append('trusted memory is not verified')
 if any(re.search(p,c.get('content','')) for p in SENSITIVE): reasons.append('sensitive pattern detected')
 if not c.get('scope'): reasons.append('missing isolation scope')
 print(json.dumps({'allow':not reasons,'reasons':reasons},indent=2)); raise SystemExit(0 if not reasons else 3)
if __name__=='__main__': main()
