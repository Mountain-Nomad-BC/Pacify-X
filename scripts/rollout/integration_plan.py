"""Prepare/apply a non-deleting source overlay into an isolated Git worktree.

This is source custody, not release packaging. Historical evidence and managed
user data never enter the overlay. Existing target-only files remain untouched.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from runtime.source_boundary import classify_path  # noqa: E402


def digest(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def eligible(relative: str) -> bool:
    parts = Path(relative).parts
    policy = json.loads((ROOT / 'policies/release-artifact-policy.json').read_text(encoding='utf-8'))
    if len(parts) == 1 and relative not in policy['product_root_files']:
        return False
    if not parts or 'memory' in parts or any(p.startswith('.env') for p in parts):
        return False
    if any(p in {'node_modules', '__pycache__', 'build', 'dist', '.git',
                 '.agentic_engineering_os_px', '.engineering-bootstrap'} for p in parts):
        return False
    if relative.startswith(('evidence/', '.px/preserved-', 'registry/operational_gap_ledger')):
        return False
    if relative.endswith(('.lock', '.pyc', '.log', '.out.txt', '.err.txt')):
        return False
    return classify_path(relative)['classification'] in {
        'authored', 'generated', 'runtime_required_generated', 'packaging_generated', 'vendored'}


def make_plan(candidate: Path, target: Path, comparison: dict) -> dict:
    candidates = set(comparison['diff']['changed'] + comparison['diff']['candidate_only'])
    candidates.add('tests/test_rollout_inventory.py')
    for directory in ('scripts/rollout', 'docs/rollout', 'evidence/rollout-2026-10-24'):
        candidates.update(p.relative_to(candidate).as_posix()
                          for p in (candidate / directory).rglob('*') if p.is_file())
    files, excluded = [], []
    for relative in sorted(candidates):
        if relative == 'evidence/rollout-2026-10-24/integration-plan.json':
            continue  # The plan cannot contain its own digest.
        review_evidence = relative.startswith('evidence/rollout-2026-10-24/') and not relative.endswith('.log')
        if not eligible(relative) and not review_evidence:
            excluded.append(relative)
            continue
        source, destination = candidate / relative, target / relative
        if source.is_symlink() or any(p.is_symlink() for p in source.parents):
            raise ValueError(f'Link refused: {relative}')
        if not source.is_file():
            raise ValueError(f'Source missing: {relative}')
        after, before = digest(source), digest(destination)
        if after != before:
            files.append(dict(path=relative, before_sha256=before, after_sha256=after,
                              classification='review_evidence' if review_evidence else classify_path(relative)['classification']))
    return dict(schema_version='px.rollout-source-overlay/1', candidate=str(candidate),
                target=str(target), files=files, excluded=excluded,
                preserved_target_only=comparison['diff']['incumbent_only'],
                release_certified=False, deletes=[])


def apply_plan(plan: dict) -> None:
    candidate, target = Path(plan['candidate']), Path(plan['target'])
    if not (target / '.git').exists():
        raise ValueError('Target must be an isolated Git worktree')
    # Check the entire denominator before the first write. A partially applied
    # overlay is recoverable by its Git branch and retained original source.
    for item in plan['files']:
        rel = Path(item['path'])
        if rel.is_absolute() or '..' in rel.parts:
            raise ValueError('Unsafe path')
        source, destination = candidate / rel, target / rel
        if any(p.is_symlink() for p in [destination, *destination.parents]):
            raise ValueError(f'Target link refused: {rel}')
        if digest(source) != item['after_sha256'] or digest(destination) != item['before_sha256']:
            raise ValueError(f'Concurrent change: {rel}')
    for item in plan['files']:
        source, destination = candidate / item['path'], target / item['path']
        if digest(source) != item['after_sha256'] or digest(destination) != item['before_sha256']:
            raise ValueError(f'Concurrent change immediately before copy: {item["path"]}')
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        if digest(destination) != item['after_sha256']:
            raise ValueError(f'Copy verification failed: {item["path"]}')


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--comparison', type=Path, required=True)
    p.add_argument('--target', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--apply', action='store_true')
    args = p.parse_args()
    plan = make_plan(ROOT, args.target.resolve(strict=True), json.loads(args.comparison.read_text()))
    args.output.write_text(json.dumps(plan, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'files': len(plan['files']), 'excluded': len(plan['excluded']), 'deletes': 0}))
    if args.apply:
        apply_plan(plan)
        print('Overlay verified; release certification remains incomplete.')


if __name__ == '__main__':
    main()
