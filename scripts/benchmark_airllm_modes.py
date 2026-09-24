#!/usr/bin/env python3
"""Reduce captured AirLLM mode measurements into deterministic evidence.

This script does not import AirLLM, prepare/download a model, or promote a mode.
The operator supplies captured measurements from separately governed runs.
"""
from __future__ import annotations
import argparse, hashlib, json, math
from pathlib import Path
from statistics import median


def canonical(v):
    return json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

def finite(v, name, minimum=0.0):
    if type(v) not in (int,float) or type(v) is bool or not math.isfinite(float(v)) or float(v)<minimum:
        raise ValueError(f"{name} must be finite and >= {minimum}")
    return float(v)

def main(argv=None):
    ap=argparse.ArgumentParser()
    ap.add_argument('--input', required=True)
    ap.add_argument('--output', required=True)
    ns=ap.parse_args(argv)
    source=Path(ns.input); out=Path(ns.output)
    raw=source.read_bytes()
    if len(raw)>4*1024*1024: raise ValueError('benchmark input exceeds byte bound')
    data=json.loads(raw)
    if type(data) is not dict or set(data)!={'schema_version','model_id','source_revision','prepared_set_sha256','cases'} or data['schema_version']!='px.airllm-benchmark-input/1.0':
        raise ValueError('unsupported AirLLM benchmark input')
    for field in ('model_id','source_revision'):
        if type(data[field]) is not str or not data[field].strip() or len(data[field].encode('utf-8')) > 256:
            raise ValueError(f'{field} must be bounded nonempty text')
    digest=data['prepared_set_sha256']
    if type(digest) is not str or len(digest)!=64 or any(c not in '0123456789abcdef' for c in digest):
        raise ValueError('prepared_set_sha256 must be lowercase SHA-256')
    cases=data['cases']
    if type(cases) is not list or not 1<=len(cases)<=256: raise ValueError('benchmark cases must be bounded')
    groups={}
    for row in cases:
        required={'compression','prefetching','success','cold_start_seconds','total_seconds','output_tokens','peak_ram_bytes','peak_vram_bytes','failure_type'}
        if type(row) is not dict or set(row)!=required: raise ValueError('benchmark case fields are invalid')
        comp=row['compression']
        if comp not in {'none','4bit','8bit'} or type(row['prefetching']) is not bool or type(row['success']) is not bool:
            raise ValueError('benchmark mode fields are invalid')
        if comp!='none' and row['prefetching']: raise ValueError('compression+prefetch is not a supported AirLLM mode')
        cold=finite(row['cold_start_seconds'],'cold_start_seconds'); total=finite(row['total_seconds'],'total_seconds')
        if type(row['output_tokens']) is not int or isinstance(row['output_tokens'],bool) or row['output_tokens']<0: raise ValueError('output_tokens invalid')
        for f in ('peak_ram_bytes','peak_vram_bytes'):
            if type(row[f]) is not int or isinstance(row[f],bool) or row[f]<0: raise ValueError(f'{f} invalid')
        if row['failure_type'] is not None and (type(row['failure_type']) is not str or len(row['failure_type'])>128): raise ValueError('failure_type invalid')
        groups.setdefault((comp,row['prefetching']),[]).append((row,cold,total))
    modes=[]
    for (comp,prefetch), rows in sorted(groups.items()):
        successes=[x for x in rows if x[0]['success']]
        body={'compression':comp,'prefetching':prefetch,'samples':len(rows),'successes':len(successes),'failures':len(rows)-len(successes)}
        if successes:
            body.update({
                'median_cold_start_seconds':median(x[1] for x in successes),
                'median_total_seconds':median(x[2] for x in successes),
                'median_tokens_per_second':median((x[0]['output_tokens']/x[2]) if x[2]>0 else 0.0 for x in successes),
                'peak_ram_bytes':max(x[0]['peak_ram_bytes'] for x in successes),
                'peak_vram_bytes':max(x[0]['peak_vram_bytes'] for x in successes),
            })
        modes.append(body)
    evidence={
      'schema_version':'px.airllm-benchmark-evidence/1.0','model_id':data['model_id'],'source_revision':data['source_revision'],
      'prepared_set_sha256':data['prepared_set_sha256'],'input_sha256':hashlib.sha256(raw).hexdigest(),'modes':modes,
      'promotion_authority':False,'preparation_authority':False,
    }
    evidence['evidence_sha256']=hashlib.sha256(canonical(evidence)).hexdigest()
    out.parent.mkdir(parents=True,exist_ok=True); out.write_bytes(json.dumps(evidence,indent=2,sort_keys=True).encode()+b'\n')
    return 0
if __name__=='__main__': raise SystemExit(main())
