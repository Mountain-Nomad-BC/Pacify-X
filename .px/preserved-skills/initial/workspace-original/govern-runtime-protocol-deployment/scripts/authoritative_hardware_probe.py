#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import os
import platform
import shutil
import subprocess


def cmd(x, timeout_seconds):
    try:
        process = subprocess.run(
            x,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=timeout_seconds,
            check=False,
        )
        return process.stdout.strip() if process.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def main():
    parser = argparse.ArgumentParser(description="Report bounded local hardware facts.")
    parser.add_argument(
        "--probe-gpu",
        action="store_true",
        help="Opt in to a bounded external nvidia-smi probe.",
    )
    parser.add_argument("--gpu-timeout", type=float, default=2.0)
    args = parser.parse_args()
    if not 0.1 <= args.gpu_timeout <= 5.0:
        parser.error("--gpu-timeout must be between 0.1 and 5 seconds")
    mem = None
    try:
        for line in open("/proc/meminfo"):
            if line.startswith("MemTotal:"):
                mem = int(line.split()[1]) * 1024
                break
    except (OSError, ValueError):
        mem = None
    gpus = (
        cmd(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,driver_version",
                "--format=csv,noheader,nounits",
            ],
            args.gpu_timeout,
        )
        if args.probe_gpu
        else None
    )
    print(
        json.dumps(
            {
                "platform": platform.platform(),
                "python": platform.python_version(),
                "cpu_count_logical": os.cpu_count(),
                "memory_bytes": mem,
                "disk_free_bytes": shutil.disk_usage(".").free,
                "nvidia_gpus": gpus.splitlines() if gpus else [],
                "gpu_probe": "completed" if args.probe_gpu else "not_requested",
                "unknowns": (
                    ([] if mem else ["total memory unavailable"])
                    + ([] if args.probe_gpu else ["gpu inventory not requested"])
                ),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main() or 0)
