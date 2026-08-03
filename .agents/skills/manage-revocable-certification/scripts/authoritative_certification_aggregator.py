#!/usr/bin/env python3
from __future__ import annotations
import argparse,json
from pathlib import Path
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('reports',nargs='+'); ap.add_argument('--out',required=True); a=ap.parse_args(); rs=[json.loads(Path(x).read_text()) for x in a.reports]; statuses=[r.get('status') or r.get('certification_status') for r in rs]; out={'status':'PASS' if all(x in ('PASS','active') for x in statuses) else 'FAIL','reports':a.reports,'statuses':statuses,'limitations':['Aggregate status does not replace field validation or independent production approval.']}; Path(a.out).write_text(json.dumps(out,indent=2)+'\n'); print(json.dumps(out,indent=2)); raise SystemExit(0 if out['status']=='PASS' else 1)
if __name__=='__main__': main()
