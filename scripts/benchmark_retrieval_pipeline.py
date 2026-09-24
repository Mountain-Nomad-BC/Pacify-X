#!/usr/bin/env python3
"""Reduce captured retrieval benchmark cases into deterministic gate evidence.

This script intentionally does not execute models or mutate the active retrieval
generation.  Hardware/model runners capture cases; this reducer makes the gate
evidence deterministic and auditable.
"""
from __future__ import annotations
import argparse, hashlib, json, math
from pathlib import Path


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def percentile(values: list[float], q: float) -> float:
    if not values: raise ValueError("benchmark requires at least one latency sample")
    rows=sorted(values); index=max(0,min(len(rows)-1,math.ceil(q*len(rows))-1)); return rows[index]


def reduce_cases(payload: dict[str, object]) -> dict[str, object]:
    if payload.get("schema_version") != "px.retrieval-benchmark-cases/1.0":
        raise ValueError("unsupported retrieval benchmark schema")
    gid=payload.get("generation_id")
    if type(gid) is not str or len(gid)!=64 or any(c not in "0123456789abcdef" for c in gid):
        raise ValueError("benchmark generation_id must be a lowercase SHA-256")
    cases=payload.get("cases")
    if type(cases) is not list or not 1 <= len(cases) <= 100000:
        raise ValueError("benchmark cases must be a bounded nonempty list")
    readiness=payload.get("readiness")
    readiness_names=("source_manifest_ok","provenance_ok","lexical_ready","vector_ready","graph_ready","calibration_ready")
    if type(readiness) is not dict or any(type(readiness.get(name)) is not bool for name in readiness_names):
        raise ValueError("benchmark readiness evidence must contain literal booleans")
    findings=payload.get("high_severity_findings",0)
    if type(findings) is not int or findings < 0:
        raise ValueError("high_severity_findings must be a nonnegative integer")
    normalized=[]
    for row in cases:
        if type(row) is not dict: raise ValueError("benchmark case must be an object")
        case_id=row.get("id")
        if type(case_id) is not str or not case_id or len(case_id.encode())>512: raise ValueError("benchmark case id is invalid")
        vals={}
        for name in ("lexical_recall","dense_recall","fused_recall"):
            v=row.get(name)
            if type(v) not in (int,float) or type(v) is bool or not math.isfinite(float(v)) or not 0<=float(v)<=1: raise ValueError(f"{name} must be finite in [0,1]")
            vals[name]=float(v)
        latency=row.get("latency_ms")
        if type(latency) not in (int,float) or type(latency) is bool or not math.isfinite(float(latency)) or float(latency)<0: raise ValueError("latency_ms must be finite and nonnegative")
        if type(row.get("exact_identifier_pass")) is not bool: raise ValueError("exact_identifier_pass must be boolean")
        normalized.append({"id":case_id,**vals,"latency_ms":float(latency),"exact_identifier_pass":row["exact_identifier_pass"]})
    normalized.sort(key=lambda x:x["id"])
    lat=[x["latency_ms"] for x in normalized]
    metrics={
        "case_count":len(normalized),
        "lexical_recall_mean":sum(x["lexical_recall"] for x in normalized)/len(normalized),
        "dense_recall_mean":sum(x["dense_recall"] for x in normalized)/len(normalized),
        "golden_recall":sum(x["fused_recall"] for x in normalized)/len(normalized),
        "exact_identifier_pass_rate":sum(1 for x in normalized if x["exact_identifier_pass"])/len(normalized),
        "p50_latency_ms":percentile(lat,0.50),
        "p95_latency_ms":percentile(lat,0.95),
    }
    evidence={"schema_version":"px.retrieval-benchmark-evidence/1.0","generation_id":gid,"metrics":metrics,"readiness":{name:readiness[name] for name in readiness_names},"high_severity_findings":findings,"cases_sha256":hashlib.sha256(canonical(normalized)).hexdigest()}
    return {**evidence,"evidence_sha256":hashlib.sha256(canonical(evidence)).hexdigest()}


def main() -> int:
    p=argparse.ArgumentParser(); p.add_argument("--cases",required=True,type=Path); p.add_argument("--output",required=True,type=Path); a=p.parse_args()
    result=reduce_cases(json.loads(a.cases.read_text(encoding="utf-8")))
    a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_bytes(canonical(result)+b"\n"); print(json.dumps(result,sort_keys=True)); return 0
if __name__=="__main__": raise SystemExit(main())
