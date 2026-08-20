"""Read-only locator for the VS Code host's Studio approval verifier.

Approval issuance intentionally does not exist in project Python. The VS Code
extension host signs an exact claim with a private key held in SecretStorage;
the Python mutation boundary only verifies and consumes that proof.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .studio_authority import StudioAuthorityStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--describe-verifier", action="store_true")
    args = parser.parse_args(argv)
    if not args.describe_verifier:
        parser.error("this module describes the verifier only; approval signing is host-owned")
    authority = StudioAuthorityStore(args.root.resolve(strict=True))
    print(json.dumps({
        "schema_version": "px.studio-host-approval-verifier-location/2.0",
        "project_identity": authority.project_identity,
        "key_root": str(authority.key_root),
        "record_path": str(authority.approval_verifier_path),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
