"""Generate or check commissioned framework profile projections."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def reconcile(root: Path, *, check: bool) -> dict[str, object]:
    root=root.resolve(); owner=root/"bootstrap/profiles"; projection=root/".engineering-bootstrap/profiles"; stale=[]; records=[]
    owner_names={path.name for path in owner.glob("*.toml")}; projection_names={path.name for path in projection.glob("*.toml")} if projection.is_dir() else set()
    extras=sorted(projection_names-owner_names)
    for source in sorted(owner.glob("*.toml")):
        expected=source.read_bytes(); target=projection/source.name
        if not target.is_file() or target.read_bytes()!=expected:
            stale.append(target.relative_to(root).as_posix())
            if not check:
                target.parent.mkdir(parents=True,exist_ok=True); target.write_bytes(expected)
        records.append({"id":source.stem,"owner":source.relative_to(root).as_posix(),"projection":target.relative_to(root).as_posix(),"sha256":hashlib.sha256(expected).hexdigest()})
    return {"schema_version":"1.0","valid":not stale and not extras if check else True,"owner_root":"bootstrap/profiles","projection_root":".engineering-bootstrap/profiles","records":records,"stale":stale,"extra":extras,"check":check}


def main()->int:
    parser=argparse.ArgumentParser();parser.add_argument("--root",type=Path,default=Path("."));parser.add_argument("--check",action="store_true")
    args=parser.parse_args();result=reconcile(args.root,check=args.check);print(json.dumps(result,indent=2));return 0 if result["valid"] else 1


if __name__=="__main__":raise SystemExit(main())
