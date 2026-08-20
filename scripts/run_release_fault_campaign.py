"""Run the bounded release fault matrix and retain content-addressed evidence."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import time


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(root: Path) -> dict[str, object]:
    path = root / "registry/release_fault_campaign.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema_version") != "px.release-fault-campaign/1.0":
        raise ValueError("unsupported fault-campaign schema")
    required = value.get("required_dimensions")
    lanes = value.get("lanes")
    if not isinstance(required, list) or not required or len(set(required)) != len(required):
        raise ValueError("fault-campaign dimensions are invalid")
    if not isinstance(lanes, list) or not lanes:
        raise ValueError("fault-campaign lanes are missing")
    covered: set[str] = set()
    for lane in lanes:
        if not isinstance(lane, dict) or set(lane) != {"id", "cwd", "command", "dimensions"}:
            raise ValueError("fault-campaign lane contract is invalid")
        command = lane["command"]
        if not isinstance(command, list) or not command or command[0] not in {"python", "node"}:
            raise ValueError("fault-campaign command is not admitted")
        cwd = (root / str(lane["cwd"])).resolve()
        cwd.relative_to(root)
        if not cwd.is_dir():
            raise ValueError("fault-campaign working directory is missing")
        for token in command:
            if not isinstance(token, str) or "\x00" in token:
                raise ValueError("fault-campaign command token is invalid")
        dimensions = lane["dimensions"]
        if not isinstance(dimensions, list) or not set(dimensions) <= set(required):
            raise ValueError("fault-campaign lane dimensions are invalid")
        covered.update(dimensions)
    if covered != set(required):
        raise ValueError("fault-campaign does not cover every required dimension")
    return value


def run_campaign(root: Path, output: Path) -> dict[str, object]:
    root = root.resolve(strict=True)
    campaign = _load(root)
    lane_receipts: list[dict[str, object]] = []
    for lane in campaign["lanes"]:
        command = list(lane["command"])
        cwd = (root / str(lane["cwd"])).resolve(strict=True)
        started = time.perf_counter()
        completed = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
            shell=False,
            check=False,
        )
        combined = f"{completed.stdout}\n{completed.stderr}".encode("utf-8")
        lane_receipts.append(
            {
                "id": lane["id"],
                "dimensions": lane["dimensions"],
                "command": command,
                "cwd": lane["cwd"],
                "exit_code": completed.returncode,
                "passed": completed.returncode == 0,
                "duration_seconds": round(time.perf_counter() - started, 6),
                "output_sha256": hashlib.sha256(combined).hexdigest(),
            }
        )
    inputs: list[dict[str, object]] = []
    seen: set[str] = set()
    for lane in campaign["lanes"]:
        for token in lane["command"]:
            if not isinstance(token, str) or not token.startswith("tests/"):
                continue
            relative = str(Path(str(lane["cwd"])) / token).replace("\\", "/")
            if relative in seen:
                continue
            target = (root / relative).resolve(strict=True)
            target.relative_to(root)
            seen.add(relative)
            inputs.append({"path": relative, "sha256": _sha(target)})
    receipt = {
        "schema_version": "px.release-fault-campaign-receipt/1.0",
        "campaign_id": campaign["campaign_id"],
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "required_dimensions": campaign["required_dimensions"],
        "lanes": lane_receipts,
        "inputs": sorted(inputs, key=lambda item: item["path"]),
        "passed": all(lane["passed"] for lane in lane_receipts),
        "authority": "bounded non-shell test campaign; no production mutation authority",
    }
    output = output.resolve()
    output.relative_to(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8", newline="\n")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("evidence/fault-campaign/release-fault-campaign-20260813.json"),
    )
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    output = args.output if args.output.is_absolute() else root / args.output
    receipt = run_campaign(root, output)
    print(json.dumps({"passed": receipt["passed"], "lanes": len(receipt["lanes"])}))
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
