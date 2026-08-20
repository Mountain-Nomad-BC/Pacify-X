#!/usr/bin/env python3
from __future__ import annotations
import argparse
import hashlib
import json
from datetime import datetime, timezone, timedelta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--action", required=True)
    ap.add_argument("--risk", required=True)
    ap.add_argument("--scope", required=True)
    ap.add_argument("--evidence", action="append", default=[])
    ap.add_argument("--rollback", required=True)
    ap.add_argument("--expires-minutes", type=int, default=30)
    a = ap.parse_args()
    stable = json.dumps(
        [a.action, a.risk, a.scope, a.evidence, a.rollback, a.expires_minutes],
        sort_keys=True,
    )
    requested_at = datetime.now(timezone.utc)
    print(
        json.dumps(
            {
                "approval_id": "approval-"
                + hashlib.sha256(stable.encode()).hexdigest()[:12],
                "action": a.action,
                "risk": a.risk,
                "scope": a.scope,
                "evidence": a.evidence,
                "rollback": a.rollback,
                "requested_at": requested_at.isoformat(),
                "expires_at": (
                    requested_at + timedelta(minutes=a.expires_minutes)
                ).isoformat(),
                "status": "pending",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
