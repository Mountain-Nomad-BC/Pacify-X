#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("workload")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    w = json.loads(Path(a.workload).read_text())
    p = {
        "user": "non-root",
        "workspace": w.get("workspace", "/workspace"),
        "filesystem": {
            "read_only": ["/usr", "/bin", "/lib"],
            "read_write": [w.get("workspace", "/workspace")],
            "hidden": ["/home", "/root", "/run/secrets"],
        },
        "network": {"default": "deny", "allow": w.get("network_allow", [])},
        "resources": {
            "cpu": w.get("cpu", 2),
            "memory_mb": w.get("memory_mb", 4096),
            "pids": w.get("pids", 256),
            "timeout_seconds": w.get("timeout_seconds", 300),
        },
        "devices": [],
        "host_sockets": [],
        "container_socket": "deny",
        "production_credentials": "deny",
    }
    Path(a.out).write_text(json.dumps(p, indent=2) + "\n")
    print(json.dumps(p, indent=2))


if __name__ == "__main__":
    main()
