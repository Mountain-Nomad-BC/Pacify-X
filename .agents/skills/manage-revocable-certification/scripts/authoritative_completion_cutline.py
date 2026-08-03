#!/usr/bin/env python3
from __future__ import annotations
import argparse,json
from pathlib import Path
BLOCKERS={'typed-contracts','evidence-ledger','safe-tools','durable-state','behavioral-evals','verification-lab','observability','memory-governance','security','supply-chain','revocable-certification'}
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('status'); a=ap.parse_args(); s=json.loads(Path(a.status).read_text()); done=set(s.get('completed',[])); missing=sorted(BLOCKERS-done); print(json.dumps({'foundational_complete':not missing,'missing_blockers':missing,'deferred_items':s.get('deferred',[]),'decision':'FREEZE_FOUNDATION' if not missing else 'COMPLETE_BLOCKERS_ONLY'},indent=2)); raise SystemExit(0 if not missing else 2)
if __name__=='__main__': main()
