# Sorting algorithm knowledge catalog

Use this catalog to choose compatible candidates before benchmarking. Complexity is for `n` records, `k` key range/buckets, and `d` key digits. Implementations and data shape can dominate theory.

| Family | Algorithms | Typical time | Stable | Extra space | Appropriate use |
|---|---|---:|---|---:|---|
| Exchange | Bubble, Cocktail/Shaker, Odd-even, Comb, Gnome | O(n²), Comb often better in practice | Bubble/Cocktail/Odd-even/Gnome yes; Comb no | O(1) | Education, tiny/nearly sorted data, networks for odd-even |
| Insertion | Insertion, Binary insertion, Library sort, Patience sort, Shell sort | O(n²); Shell depends on gaps; Patience O(n log n) | Insertion variants yes; Shell generally no | O(1) to O(n) | Tiny runs, nearly sorted data, hybrid base cases |
| Selection | Selection, Double selection, Cycle sort | O(n²) | Usually no | O(1) | Minimal writes (Cycle), tiny arrays |
| Heap/tree | Heapsort, Smoothsort, Tournament, Tree sort, Cartesian tree sort | O(n log n) | Usually no | O(1) to O(n) | Worst-case bounds, selection/merging, constrained memory |
| Divide/conquer | Merge, Natural merge, Quicksort, 3-way quicksort, Introsort | O(n log n) average; Quicksort O(n²) worst without protection | Merge yes; Quick/Intro no | O(log n) to O(n) | General arrays, duplicate-aware quicksort, guaranteed hybrids |
| Adaptive hybrids | Timsort, Powersort, Block sort, Grailsort | O(n log n), near O(n) on runs | Usually yes | O(1) to O(n) | Real-world partially ordered data; language runtimes |
| Distribution | Counting, Pigeonhole, Bucket/Bin, Flashsort, American flag sort | O(n+k) average/qualified | Counting/Bucket can be; others vary | O(n+k) | Bounded numeric domains or known distributions |
| Radix/digit | LSD radix, MSD radix, Burstsort, Spreadsort | O(d(n+k)) | LSD commonly yes; MSD varies | O(n+k) | Integers, fixed-width keys, strings with controlled alphabets |
| String-specific | Trie sort, Burstsort, Multikey quicksort, MSD/LSD string radix | O(total key characters) qualified | Varies | Often O(n) | Large string collections and prefix-heavy keys |
| External | External merge sort, polyphase merge, replacement selection, external distribution sort | O(n log n) I/O-aware | Can be | Bounded RAM + disk runs | Data larger than memory; sequential I/O |
| Parallel | Parallel merge, Sample sort, Bitonic sort, Odd-even merge network, GPU radix | Work/depth varies | Varies | Varies | Multicore/GPU/distributed systems after transfer/merge costs are measured |
| Network/oblivious | Bitonic network, Odd-even merge network, Batcher networks, AKS (theoretical) | O(log² n) depth common | No unless decorated | Hardware dependent | SIMD/GPU/hardware, data-oblivious execution |
| Partial/selection | Quickselect, Introselect, `nth_element`, partial sort, Top-k heap | O(n) average or O(n log k) | Not generally | O(1) to O(k) | Do not fully sort when only ranks/top-k are needed |
| Integer specialized | Proxmap, Address-calculation, Bead/Gravity sort | Qualified/non-general | Varies | Often large | Narrow domains or research; require explicit evidence |
| Novelty/impractical | Bogo, Bozo, Stooge, Slowsort, Sleep sort | Super-polynomial, O(n^2.7), timing-dependent | Irrelevant | Varies | Demonstration only; never bulk production |

## Decision notes

- Python/Java object sorting: benchmark the platform's adaptive stable sort first.
- Dense bounded integers: compare Counting, Radix, and the platform sort; account for range memory.
- Numeric data with defensible near-uniform distribution: compare Bucket, platform sort, and Merge.
- Duplicate-heavy keys: use stable Timsort/Merge or 3-way Quicksort if stability is unnecessary.
- Nearly sorted data: Timsort, Natural Merge, Insertion for tiny runs, or Smoothsort.
- Hard worst-case/in-place requirement: Heapsort or Introsort.
- Data larger than memory: generate sorted runs, retain per-run hashes, k-way external merge, and verify final count/order/multiset.
- Distributed data: measure partition skew, serialization, network transfer, spill, merge, and failure recovery; local comparison time alone is insufficient.
- Security/data-oblivious requirement: use a validated sorting network or specialized oblivious sort, not data-dependent Quicksort.
