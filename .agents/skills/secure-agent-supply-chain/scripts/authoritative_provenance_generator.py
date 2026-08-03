#!/usr/bin/env python3
from __future__ import annotations
import argparse,hashlib,json,platform,shlex
from datetime import datetime,timezone
from pathlib import Path
def h(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--subject',action='append',default=[]); ap.add_argument('--material',action='append',default=[]); ap.add_argument('--command',action='append',default=[]); ap.add_argument('--out',required=True); a=ap.parse_args(); d={'_type':'https://in-toto.io/Statement/v1','predicateType':'https://slsa.dev/provenance/v1','subject':[{'name':x,'digest':{'sha256':h(x)}} for x in a.subject],'predicate':{'buildDefinition':{'buildType':'local-reference-build','externalParameters':{'commands':a.command},'resolvedDependencies':[{'uri':x,'digest':{'sha256':h(x)}} for x in a.material]},'runDetails':{'builder':{'id':'local-python-reference'},'metadata':{'invocationId':hashlib.sha256(('\n'.join(a.command)).encode()).hexdigest()[:24],'startedOn':datetime.now(timezone.utc).isoformat()},'environment':{'python':platform.python_version(),'platform':platform.platform()}}}}; Path(a.out).write_text(json.dumps(d,indent=2,sort_keys=True)+'\n'); print(json.dumps(d,indent=2))
if __name__=='__main__': main()
