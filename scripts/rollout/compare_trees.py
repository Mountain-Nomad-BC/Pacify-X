"""Read-only, byte-exact source comparison; never copies or deletes files."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

import sys
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from runtime.secure_publish import read_physical_bytes

EXCLUDED = {'.git', '.venv', '.venv-certify', '__pycache__', 'node_modules',
            '.pytest_cache', '.ruff_cache', 'build', 'dist', 'Python',
            '.quarantine', 'repo_quarantine', '.tmp', '.pacify-x', '.audit-handoff',
            '.engineering-bootstrap', '.agentic_engineering_os_px',
            'projects', 'projects_tracking', 'current quar', '.audit-visible'}


def inventory(root: Path) -> dict:
    files, excluded, links = {}, [], []
    print(f'Inventory: {root}', flush=True)
    for directory, dirs, names in os.walk(root, followlinks=False):
        parent = Path(directory)
        for name in list(dirs):
            path = parent / name
            if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
                links.append(path.relative_to(root).as_posix())
                dirs.remove(name)
            elif name in EXCLUDED or name.startswith('.venv') or name.endswith('.egg-info'):
                excluded.append(path.relative_to(root).as_posix())
                dirs.remove(name)
        for name in names:
            path = parent / name
            rel = path.relative_to(root).as_posix()
            if name == '.git':
                excluded.append(rel + ' [Git pointer; never product source]')
                continue
            if path.suffix.lower() in {'.zip', '.vsix', '.whl', '.exe', '.dll', '.pdb', '.bin', '.gguf'}:
                excluded.append(rel + ' [binary payload; separate custody review]')
                continue
            if path.is_symlink():
                links.append(rel)
                continue
            if name.endswith(('.pyc', '.pyo')):
                continue
            if path.stat().st_size > 64 * 1024 * 1024:
                excluded.append(rel + ' [over 64 MiB; requires separate custody review]')
                continue
            raw = read_physical_bytes(path, max_bytes=64 * 1024 * 1024)
            files[rel] = {'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
            if len(files) % 2000 == 0:
                print(f'Hashed {len(files)} files; {rel}', flush=True)
    encoded = json.dumps(files, sort_keys=True, separators=(',', ':')).encode()
    return dict(root=str(root), files=files, excluded=sorted(excluded),
                links_refused=sorted(links), manifest_sha256=hashlib.sha256(encoded).hexdigest())


def compare(candidate: dict, incumbent: dict) -> dict:
    left, right = candidate['files'], incumbent['files']
    return dict(candidate_only=sorted(left.keys() - right.keys()),
                incumbent_only=sorted(right.keys() - left.keys()),
                changed=sorted(k for k in left.keys() & right.keys() if left[k] != right[k]),
                equal_count=sum(left[k] == right[k] for k in left.keys() & right.keys()))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--incumbent', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    candidate, incumbent = inventory(args.candidate.resolve(strict=True)), inventory(args.incumbent.resolve(strict=True))
    result = dict(schema_version='px.rollout-source-comparison/1', candidate=candidate,
                  incumbent=incumbent, diff=compare(candidate, incumbent),
                  boundary='Scoped source comparison. Exclusions are explicit; this is not a full custody snapshot or release certificate.')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps({k: len(v) if isinstance(v, list) else v for k, v in result['diff'].items()}))


if __name__ == '__main__':
    main()
