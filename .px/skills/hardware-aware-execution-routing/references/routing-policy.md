# Hardware-aware routing policy

## Device matrix

| Workload | Default | GPU condition |
|---|---|---|
| Filesystem/NTFS, OS APIs, SQLite, serialization, reports | CPU | Never |
| Embeddings, model/image inference, vector search, large tensors | CPU until evidenced | Batched, compatible, memory-safe, correct, and benchmark-fast |
| Hashing, compression, sorting, text, dataframe transforms | CPU | Representative end-to-end benchmark required |
| RAPIDS dataframe, graph, clustering, vector analytics | CPU/Polars first | Optional Linux/WSL2 path beats CPU and uses batched exchange |

## Default resource policy

- Reserve at least 1.5 GiB free VRAM.
- Use at most 70% of currently free VRAM.
- Start with a conservative batch size.
- On CUDA OOM, halve the batch and retry at most twice.
- Fall back to CPU after bounded retry unless strict testing explicitly disables
  fallback.
- Keep optional GPU enrichment disabled unless the workload asks for it.

## Evidence contract

Measure tiny, small, medium, large, and representative production sizes. Record
cold start, warm execution, initialization, host-to-device transfer, kernel or
inference time, synchronization, device-to-host transfer, end-to-end wall time,
peak RAM/VRAM, throughput, correctness, numerical drift, and environment versions.
Synchronize CUDA before stopping a timed interval.

Select GPU automatically only when current evidence shows at least 1.25x
end-to-end speedup, correctness passes, VRAM remains within policy, and repeated
runs are stable. Fingerprint hardware, driver, runtime, providers, model, precision,
and relevant library versions so drift invalidates cached evidence.

## Safety

Keep cleanup and deletion rules deterministic and CPU-authoritative. Treat model
classification as advisory. Preserve requested precision and determinism; never
enable mixed precision silently. Keep local inventories local, redact secrets, and
do not read sensitive file contents for semantic enrichment.
