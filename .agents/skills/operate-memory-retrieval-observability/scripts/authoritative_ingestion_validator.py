#!/usr/bin/env python3
from __future__ import annotations
import argparse,hashlib,json
from pathlib import Path
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('file'); a=ap.parse_args(); p=Path(a.file); raw=p.read_bytes(); txt=raw.decode('utf-8',errors='replace'); issues=[]
 if '\ufffd' in txt: issues.append('decode replacements present')
 if not txt.strip(): issues.append('empty content')
 print(json.dumps({'path':str(p),'bytes':len(raw),'characters':len(txt),'sha256':hashlib.sha256(raw).hexdigest(),'issues':issues,'valid':not issues},indent=2)); raise SystemExit(0 if not issues else 2)
if __name__=='__main__': main()
