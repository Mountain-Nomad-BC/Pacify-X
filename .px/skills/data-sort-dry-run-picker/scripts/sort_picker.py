#!/usr/bin/env python3
"""Bounded, read-only data-sort candidate picker with correctness receipts."""

from __future__ import annotations

import argparse
import csv
import hashlib
import heapq
import json
import math
from pathlib import Path
import random
import statistics
import time
from typing import Any, Callable, Iterable, Iterator


Item = tuple[Any, int, Any]
Algorithm = Callable[[list[Item]], list[Item]]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_array_records(path: Path, chunk_size: int = 1024 * 1024) -> Iterator[Any]:
    decoder = json.JSONDecoder()
    with path.open("r", encoding="utf-8") as handle:
        buffer = ""
        started = False
        finished = False
        while not finished:
            chunk = handle.read(chunk_size)
            eof = chunk == ""
            buffer += chunk
            position = 0
            while True:
                while position < len(buffer) and buffer[position].isspace():
                    position += 1
                if not started:
                    if position >= len(buffer):
                        break
                    if buffer[position] != "[":
                        raise ValueError("JSON input must be a top-level array; use JSONL for streams")
                    started = True
                    position += 1
                    continue
                while position < len(buffer) and (buffer[position].isspace() or buffer[position] == ","):
                    position += 1
                if position < len(buffer) and buffer[position] == "]":
                    finished = True
                    position += 1
                    break
                if position >= len(buffer):
                    break
                try:
                    value, end = decoder.raw_decode(buffer, position)
                except json.JSONDecodeError:
                    if eof:
                        raise ValueError("invalid or incomplete JSON array")
                    break
                yield value
                position = end
            buffer = buffer[position:]
            if eof:
                if not finished and buffer.strip():
                    raise ValueError("invalid or incomplete JSON array")
                break
        if not started or not finished:
            raise ValueError("JSON array terminator was not found")


def iter_records(path: Path, input_format: str) -> Iterator[Any]:
    kind = input_format if input_format != "auto" else {
        ".json": "json", ".jsonl": "jsonl", ".ndjson": "jsonl", ".csv": "csv"
    }.get(path.suffix.lower(), "lines")
    if kind == "json":
        yield from _json_array_records(path)
    elif kind == "jsonl":
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if line.strip():
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError as error:
                        raise ValueError(f"invalid JSON on line {line_number}: {error.msg}") from error
    elif kind == "csv":
        with path.open("r", encoding="utf-8", newline="") as handle:
            yield from csv.DictReader(handle)
    elif kind == "lines":
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                yield line.rstrip("\r\n")
    else:
        raise ValueError(f"unsupported input format: {kind}")


def extract_key(record: Any, key_path: str | None) -> Any:
    value = record
    if key_path:
        for segment in key_path.split("."):
            if isinstance(value, dict) and segment in value:
                value = value[segment]
            elif isinstance(value, list) and segment.isdigit() and int(segment) < len(value):
                value = value[int(segment)]
            else:
                raise ValueError(f"missing key path: {key_path}")
    if isinstance(value, (dict, list)) or value is None:
        raise ValueError("sort keys must be non-null scalars")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("NaN and infinity require an explicit normalization policy")
    return value


def coerce_key(value: Any, policy: str) -> Any:
    if policy == "none" or not isinstance(value, str):
        return value
    if policy in {"auto", "integer"}:
        try:
            return int(value)
        except ValueError:
            if policy == "integer":
                raise ValueError(f"key is not an integer: {value!r}")
    if policy in {"auto", "number"}:
        try:
            number = float(value)
            if not math.isfinite(number):
                raise ValueError("non-finite numeric key")
            return number
        except ValueError:
            if policy == "number":
                raise ValueError(f"key is not numeric: {value!r}")
    return value


def sample_records(path: Path, input_format: str, key_path: str | None, coerce: str, limit: int, seed: int) -> tuple[int, list[Item]]:
    rng = random.Random(seed)
    sample: list[Item] = []
    key_type: type | None = None
    count = 0
    for ordinal, record in enumerate(iter_records(path, input_format)):
        key = coerce_key(extract_key(record, key_path), coerce)
        current_type = bool if isinstance(key, bool) else type(key)
        if key_type is None:
            key_type = current_type
        if current_type is not key_type:
            raise ValueError(f"mixed key types are not a total order: {key_type.__name__} and {current_type.__name__}")
        item = (key, ordinal, record)
        count += 1
        if len(sample) < limit:
            sample.append(item)
        else:
            choice = rng.randrange(count)
            if choice < limit:
                sample[choice] = item
    if not count:
        raise ValueError("input contains no sortable records")
    return count, sample


def timsort(items: list[Item]) -> list[Item]:
    return sorted(items, key=lambda item: (item[0], item[1]))


def merge_sort(items: list[Item]) -> list[Item]:
    width = 1
    source = list(items)
    target = source.copy()
    while width < len(source):
        for start in range(0, len(source), width * 2):
            left, mid, right = start, min(start + width, len(source)), min(start + width * 2, len(source))
            i, j, out = left, mid, left
            while i < mid and j < right:
                if (source[i][0], source[i][1]) <= (source[j][0], source[j][1]):
                    target[out] = source[i]; i += 1
                else:
                    target[out] = source[j]; j += 1
                out += 1
            while i < mid: target[out] = source[i]; i += 1; out += 1
            while j < right: target[out] = source[j]; j += 1; out += 1
        source, target = target, source
        width *= 2
    return source


def heap_sort(items: list[Item]) -> list[Item]:
    heap = [((item[0], item[1]), item) for item in items]
    heapq.heapify(heap)
    return [heapq.heappop(heap)[1] for _ in range(len(heap))]


def quick_3way(items: list[Item]) -> list[Item]:
    values = list(items)
    stack = [(0, len(values) - 1)]
    while stack:
        low, high = stack.pop()
        if low >= high:
            continue
        pivot = (values[(low + high) // 2][0], values[(low + high) // 2][1])
        left, index, right = low, low, high
        while index <= right:
            key = (values[index][0], values[index][1])
            if key < pivot:
                values[left], values[index] = values[index], values[left]; left += 1; index += 1
            elif key > pivot:
                values[index], values[right] = values[right], values[index]; right -= 1
            else:
                index += 1
        stack.extend([(low, left - 1), (right + 1, high)])
    return values


def counting_sort(items: list[Item]) -> list[Item]:
    keys = [item[0] for item in items]
    low, high = min(keys), max(keys)
    buckets: list[list[Item]] = [[] for _ in range(high - low + 1)]
    for item in items: buckets[item[0] - low].append(item)
    return [item for bucket in buckets for item in bucket]


def radix_sort(items: list[Item]) -> list[Item]:
    low = min(item[0] for item in items)
    shifted = [(item[0] - low, item) for item in items]
    place = 1
    maximum = max(key for key, _ in shifted)
    while maximum // place:
        buckets: list[list[tuple[int, Item]]] = [[] for _ in range(256)]
        for pair in shifted: buckets[(pair[0] // place) % 256].append(pair)
        shifted = [pair for bucket in buckets for pair in bucket]
        place *= 256
    return [item for _, item in shifted]


def bucket_sort(items: list[Item]) -> list[Item]:
    low, high = min(float(item[0]) for item in items), max(float(item[0]) for item in items)
    if low == high: return list(items)
    count = max(2, min(4096, int(math.sqrt(len(items))) or 2))
    buckets: list[list[Item]] = [[] for _ in range(count)]
    for item in items:
        index = min(count - 1, int((float(item[0]) - low) / (high - low) * count))
        buckets[index].append(item)
    return [item for bucket in buckets for item in sorted(bucket, key=lambda row: (row[0], row[1]))]


ALGORITHMS: dict[str, Algorithm] = {
    "timsort": timsort, "merge-sort": merge_sort, "heap-sort": heap_sort,
    "quick-3way": quick_3way, "counting-sort": counting_sort,
    "radix-sort": radix_sort, "bucket-sort": bucket_sort,
}


def compatible_algorithms(items: list[Item]) -> tuple[list[str], dict[str, str]]:
    keys = [item[0] for item in items]
    integer = all(isinstance(key, int) and not isinstance(key, bool) for key in keys)
    numeric = integer or all(isinstance(key, (int, float)) and not isinstance(key, bool) for key in keys)
    accepted = ["timsort", "merge-sort", "heap-sort", "quick-3way"]
    reasons = {name: "homogeneous total-order comparison keys" for name in accepted}
    if numeric:
        accepted.append("bucket-sort"); reasons["bucket-sort"] = "finite homogeneous numeric keys"
    if integer:
        span = max(keys) - min(keys) + 1
        if span <= min(2_000_000, max(4096, len(keys) * 8)):
            accepted.append("counting-sort"); reasons["counting-sort"] = f"bounded integer range ({span})"
        accepted.append("radix-sort"); reasons["radix-sort"] = "homogeneous signed integer keys"
    return accepted, reasons


def validate_output(output: list[Item], reference: list[Item]) -> tuple[bool, bool, str | None]:
    if len(output) != len(reference): return False, False, "record-count-mismatch"
    if [item[1] for item in output] != [item[1] for item in reference]: return False, False, "reference-order-mismatch"
    stable = all(output[index - 1][0] != output[index][0] or output[index - 1][1] < output[index][1] for index in range(1, len(output)))
    return True, stable, None


def benchmark(name: str, algorithm: Algorithm, items: list[Item], reference: list[Item], repeats: int) -> dict[str, Any]:
    timings: list[int] = []
    correct = stable = True
    error: str | None = None
    for _ in range(repeats):
        started = time.perf_counter_ns()
        try:
            output = algorithm(list(items))
            elapsed = time.perf_counter_ns() - started
            run_correct, run_stable, run_error = validate_output(output, reference)
            correct = correct and run_correct; stable = stable and run_stable
            error = error or run_error
            timings.append(elapsed)
        except Exception as exc:  # candidate failure is evidence, not a harness crash
            correct = stable = False; error = f"{type(exc).__name__}: {exc}"; break
    ordered = sorted(timings)
    p95 = ordered[min(len(ordered) - 1, math.ceil(len(ordered) * .95) - 1)] if ordered else None
    return {"algorithm": name, "correct": correct, "stable": stable, "error": error, "runs_ns": timings,
            "median_ns": int(statistics.median(timings)) if timings else None, "p95_ns": p95}


def build_receipt(path: Path, *, input_format: str, key_path: str | None, coerce: str, sample_limit: int, repeats: int, seed: int) -> dict[str, Any]:
    count, sample = sample_records(path, input_format, key_path, coerce, sample_limit, seed)
    sample_hash = hashlib.sha256(json.dumps([(item[0], item[1]) for item in sample], ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()
    reference = timsort(sample)
    names, reasons = compatible_algorithms(sample)
    pilot_size = min(4096, len(sample))
    pilot = sample[:pilot_size]
    pilot_reference = timsort(pilot)
    pilot_results = [benchmark(name, ALGORITHMS[name], pilot, pilot_reference, 1) for name in names]
    qualified = sorted((row for row in pilot_results if row["correct"]), key=lambda row: (row["median_ns"], row["algorithm"]))[:3]
    final_results = [benchmark(row["algorithm"], ALGORITHMS[row["algorithm"]], sample, reference, repeats) for row in qualified]
    winners = sorted((row for row in final_results if row["correct"] and row["stable"]), key=lambda row: (row["median_ns"], row["algorithm"]))
    return {
        "schema_version": "1.0", "operation": "data-sort-dry-run-picker", "dry_run": True,
        "input": {"path": str(path.resolve()), "bytes": path.stat().st_size, "records": count, "sha256": sha256_file(path), "format": input_format, "key_path": key_path, "coerce": coerce},
        "sample": {"records": len(sample), "coverage_ratio": len(sample) / count, "strategy": "full" if count <= sample_limit else "deterministic-reservoir", "seed": seed, "sha256": sample_hash},
        "candidate_compatibility": [{"algorithm": name, "reason": reasons[name]} for name in names],
        "pilot": {"records": pilot_size, "results": pilot_results, "advanced": [row["algorithm"] for row in qualified]},
        "benchmark": {"repeats": repeats, "results": final_results},
        "selected": winners[0]["algorithm"] if winners else None,
        "decision": "selected-fastest-correct-stable-median" if winners else "no-candidate-passed",
        "full_run_requirement": "external-merge-plan" if count > sample_limit else "selected-algorithm-may-be-applied-with-separate-write-approval",
        "residual_risks": (["sample may not represent full-data distribution"] if count > sample_limit else []) + ["benchmark is runtime/hardware/implementation specific"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--format", choices=["auto", "json", "jsonl", "csv", "lines"], default="auto")
    parser.add_argument("--key")
    parser.add_argument("--coerce", choices=["auto", "none", "integer", "number"], default="auto")
    parser.add_argument("--sample-records", type=int, default=50_000)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--seed", type=int, default=8675309)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.sample_records < 100 or args.sample_records > 1_000_000: raise SystemExit("sample-records must be between 100 and 1000000")
    if args.repeats < 1 or args.repeats > 25: raise SystemExit("repeats must be between 1 and 25")
    if not args.input.is_file(): raise SystemExit("input must be a readable regular file")
    try:
        receipt = build_receipt(args.input, input_format=args.format, key_path=args.key, coerce=args.coerce, sample_limit=args.sample_records, repeats=args.repeats, seed=args.seed)
    except (OSError, UnicodeError, ValueError) as error:
        raise SystemExit(str(error)) from error
    payload = json.dumps(receipt, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if receipt["selected"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
