#!/usr/bin/env python3
from __future__ import annotations
import argparse,hashlib,json
from pathlib import Path
def h(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--file',action='append',default=[]); ap.add_argument('--out',required=True); a=ap.parse_args(); files=[{'path':x,'sha256':h(x),'bytes':Path(x).stat().st_size} for x in sorted(a.file)]; b={'files':files,'replay_requirements':['restore declared versions','stub destructive side effects','verify all hashes before execution']}; Path(a.out).write_text(json.dumps(b,indent=2)+'\n'); print(json.dumps(b,indent=2))
if __name__=='__main__': main()
