#!/usr/bin/env python3
"""Validate a retrieval generation and emit immutable admission evidence.

Certification never activates the candidate.  Activation remains a separate
explicit-authority operation on RetrievalGenerationStore.
"""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from runtime.retrieval_generation import RetrievalGateEvidence, RetrievalGenerationStore


def main() -> int:
    p=argparse.ArgumentParser(); p.add_argument("--state-root",required=True,type=Path); p.add_argument("--artifact-root",required=True,type=Path); p.add_argument("--generation-id",required=True); p.add_argument("--benchmark-evidence",required=True,type=Path); p.add_argument("--policy",default=ROOT/"models"/"retrieval-policy.json",type=Path); a=p.parse_args()
    store=RetrievalGenerationStore(a.state_root)
    manifest=store.load_manifest(a.generation_id)
    artifact_report=store.validate_artifacts(a.generation_id,a.artifact_root)
    bench=json.loads(a.benchmark_evidence.read_text(encoding="utf-8")); policy_bytes=a.policy.read_bytes(); policy=json.loads(policy_bytes)
    if bench.get("schema_version")!="px.retrieval-benchmark-evidence/1.0" or bench.get("generation_id")!=a.generation_id:
        raise ValueError("benchmark evidence does not match retrieval generation")
    claimed=bench.get("evidence_sha256")
    unsigned={k:v for k,v in bench.items() if k != "evidence_sha256"}
    if type(claimed) is not str or hashlib.sha256(json.dumps(unsigned,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode("utf-8")).hexdigest()!=claimed:
        raise ValueError("benchmark evidence digest mismatch")
    expected_policy_sha=manifest.get("identity",{}).get("query_policy_sha256")
    if hashlib.sha256(policy_bytes).hexdigest()!=expected_policy_sha:
        raise ValueError("retrieval policy bytes do not match the candidate generation")
    gates=policy.get("activation_gates",{}); metrics=bench.get("metrics",{}); readiness=bench.get("readiness",{})
    evidence=RetrievalGateEvidence(
        build_ok=bool(artifact_report["valid"]), source_manifest_ok=readiness.get("source_manifest_ok") is True, provenance_ok=readiness.get("provenance_ok") is True,
        lexical_ready=readiness.get("lexical_ready") is True, vector_ready=readiness.get("vector_ready") is True,
        calibration_ready=readiness.get("calibration_ready") is True, graph_ready=readiness.get("graph_ready") is True,
        golden_recall=float(metrics["golden_recall"]), golden_recall_min=float(gates["golden_recall_min"]),
        exact_identifier_pass_rate=float(metrics["exact_identifier_pass_rate"]), exact_identifier_min=float(gates["exact_identifier_pass_rate_min"]),
        p95_latency_ms=float(metrics["p95_latency_ms"]), p95_latency_max_ms=float(gates["p95_latency_ms_max"]),
        high_severity_findings=int(bench.get("high_severity_findings",-1)), high_severity_findings_max=int(gates["high_severity_findings_max"]),
    )
    receipt=store.record_validation(a.generation_id,evidence)
    print(json.dumps(receipt,sort_keys=True)); return 0 if receipt["admission"]["allowed"] else 2
if __name__=="__main__": raise SystemExit(main())
