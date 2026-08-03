#!/usr/bin/env python3
from __future__ import annotations
import argparse,json
from pathlib import Path
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('record'); ap.add_argument('--kind',choices=['mcp','a2a','openapi','json-schema'],required=True); a=ap.parse_args(); d=json.loads(Path(a.record).read_text()); req={'mcp':['protocolVersion','capabilities'],'a2a':['name','url','version','capabilities'],'openapi':['openapi','paths'],'json-schema':['$schema','type']}[a.kind]; missing=[x for x in req if x not in d]; print(json.dumps({'kind':a.kind,'valid':not missing,'missing':missing,'version':d.get('protocolVersion') or d.get('version') or d.get('openapi') or d.get('$schema')},indent=2)); raise SystemExit(0 if not missing else 2)
if __name__=='__main__': main()
