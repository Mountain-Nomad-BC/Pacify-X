#!/usr/bin/env python3
from __future__ import annotations
import argparse,zipfile
from pathlib import Path
FIX=(2026,1,1,0,0,0)
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('root'); ap.add_argument('out'); a=ap.parse_args(); root=Path(a.root)
 with zipfile.ZipFile(a.out,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
  for p in sorted(root.rglob('*')):
   if p.is_file() and not any(x in p.parts for x in ['__pycache__','.pytest_cache']):
    i=zipfile.ZipInfo(str(Path(root.name)/p.relative_to(root)).replace('\\','/'),FIX); i.compress_type=zipfile.ZIP_DEFLATED; z.writestr(i,p.read_bytes())
 print(a.out)
if __name__=='__main__': main()
