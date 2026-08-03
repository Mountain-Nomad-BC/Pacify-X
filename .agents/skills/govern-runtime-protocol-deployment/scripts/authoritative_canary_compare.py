#!/usr/bin/env python3
from __future__ import annotations
import argparse,json
from pathlib import Path
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('baseline'); ap.add_argument('candidate'); ap.add_argument('--quality-drop',type=float,default=.02); ap.add_argument('--latency-rise',type=float,default=.1); ap.add_argument('--error-rise',type=float,default=.01); a=ap.parse_args(); b=json.loads(Path(a.baseline).read_text()); c=json.loads(Path(a.candidate).read_text()); checks={'quality':c['quality']>=b['quality']-a.quality_drop,'latency':c['latency']<=b['latency']*(1+a.latency_rise),'errors':c['error_rate']<=b['error_rate']+a.error_rise}; print(json.dumps({'checks':checks,'decision':'expand' if all(checks.values()) else 'rollback'},indent=2)); raise SystemExit(0 if all(checks.values()) else 4)
if __name__=='__main__': main()
