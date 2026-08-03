#!/usr/bin/env python3
from __future__ import annotations
import argparse,hashlib,json,zipfile
from pathlib import Path
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('zip'); a=ap.parse_args(); z=zipfile.ZipFile(a.zip); bad=z.testzip(); names=z.namelist(); transient=[n for n in names if '__pycache__' in n or n.endswith(('.pyc','.pyo'))]; dups=[n for n in set(names) if names.count(n)>1]; print(json.dumps({'zip':a.zip,'sha256':hashlib.sha256(Path(a.zip).read_bytes()).hexdigest(),'entries':len(names),'crc_error':bad,'transient_entries':transient,'duplicate_entries':dups,'valid':not bad and not transient and not dups},indent=2)); raise SystemExit(0 if not bad and not transient and not dups else 1)
if __name__=='__main__': main()
