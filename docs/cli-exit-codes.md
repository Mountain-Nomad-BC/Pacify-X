# CLI exit-code contract

PACIFY-X uses one process-exit policy from `runtime/exit_codes.py`.

| Code | Meaning | Examples |
|---:|---|---|
| 0 | Authoritative success, ordinary successful command, or explicitly non-authoritative simulation completed | admitted; verified; claims evaluated |
| 1 | Command execution failure | unreadable input; unexpected runtime error |
| 2 | Admitted with restrictions | `review-candidate` returns `restrict` |
| 3 | Quarantined | `review-candidate` returns `quarantine` |
| 4 | Rejected | `review-candidate` returns `reject` |
| 5 | Authoritative verification failed | postcondition or policy denial |
| 6 | Insufficient trusted evidence | missing, stale, out-of-scope, or unapproved evidence |
| 7 | Invalid authoritative request | required request or contract data missing |
| 8 | Evidence integrity failure | record, artifact, or expected hash mismatch |

JSON fields keep separate meanings: `evaluated` says the decision procedure ran, `request_valid` says the request shape was usable, `accepted` says admission occurred, `verified` says authoritative outcome verification passed, and `authoritative` says the result can affect governed state. `valid` remains only the CLI's general success projection and is not evidence by itself.

## Independent assurance gates

Run gates with receipts outside the product tree:

```powershell
engineering-bootstrap gates run --receipt-dir <GATE_RECEIPT_DIR>
engineering-bootstrap gates finalize --receipt-dir <GATE_RECEIPT_DIR>
```

Each gate receipt is sealed to that gate's declared input hashes and its dependency receipts. A current passing receipt is reused. A failed or stale gate reruns without rerunning unrelated current gates. Finalization executes nothing; it succeeds only when every registered gate has a current, untampered passing receipt.
