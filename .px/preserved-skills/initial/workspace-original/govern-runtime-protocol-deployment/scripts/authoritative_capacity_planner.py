#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--params-b", type=float, required=True)
    ap.add_argument("--weight-bits", type=float, default=16)
    ap.add_argument("--layers", type=int, required=True)
    ap.add_argument("--kv-heads", type=int, required=True)
    ap.add_argument("--head-dim", type=int, required=True)
    ap.add_argument("--context", type=int, required=True)
    ap.add_argument("--batch", type=int, default=1)
    ap.add_argument("--kv-bytes", type=int, default=2)
    ap.add_argument("--overhead", type=float, default=1.2)
    a = ap.parse_args()
    weights = a.params_b * 1e9 * a.weight_bits / 8
    kv = 2 * a.layers * a.batch * a.context * a.kv_heads * a.head_dim * a.kv_bytes
    total = (weights + kv) * a.overhead
    print(
        json.dumps(
            {
                "weights_bytes": weights,
                "kv_cache_bytes": kv,
                "estimated_total_bytes": total,
                "estimated_total_gib": total / 2**30,
                "assumptions": vars(a),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
