# V24: finite DropTail queue native core counterexample

ARS-Codex assistant implementation verification, 2026-10-13. This is a
baseline-integrity finding, not a new congestion algorithm or Q2 certification.

Pinned author source: williamsentosa95/cellreplay commit
2ca662cb01a222dd7fcc10f9ed79293803b4ef21. The five packet queue files were
obtained from paths identified by the author's Makefile. Queue classes and
dropping_packet_queue.cc were compiled unchanged. Two tiny build adapters
provide the unused exception header and myatoi via std::stoul; no networking,
timestamps, traffic captures, or reserved numerical inputs were executed.

The standalone source-derived harness couples that native admission code to
the original attempt-based increment, output-based decrement and light-bypass
predicate. The accepted packets are all drained before the probe. In-transit
and output buffers are omitted rather than represented as real OS execution.

| Variant | Dropped | Actual resident after drain | Maintained counter | Light bypass |
|---|---:|---:|---:|---|
| Original, packet limit 1 | 1 | 0 | 1 | No |
| Original, packet limit 2 | 0 | 0 | 0 | Yes |
| Derivative accepted-count increment, limit 1 | 1 | 0 | 0 | Yes |

All 18 event records satisfy counter-minus-resident equals cumulative drops in
the original variants, and counter equals resident in the corrected DropTail
variant. Thus a single silent admission refusal leaves a stale positive
counter even after the real queue empties; the next light-flagged packet takes
the heavy path in this source-derived coupling. The original final counter
still remains positive after that packet drains.

Output: results/native_queue_v24; PASS_NATIVE_CORE_COUNTEREXAMPLE.
Raw events SHA256 3edc9648a4bd733f89a2a067dd5fd290127c02b4ffb8b3093eb6344203bbd9a5.
Native executable SHA256 2ee85a5c1f5532c913ed88a2fc696483df02fefef8bd37137cca9eee521796e2.
No measured millisecond delay consequence is claimed. No full CellReplay
execution, published-paper invalidation, external expert audit, author issue,
or universal correction for other queue disciplines is claimed. Non-dropping
configurations are not affected by this demonstrated refusal case.

Before mixed-flow finite-buffer replay, explicitly label original versus
corrected queue accounting. Keep original outputs, losses and service inputs;
never silently repair the baseline or count this artifact as scheduler novelty.

Reproduce with new output directories:
python -m converged_sim.cellreplay_queue_source --out results/cellreplay_queue_source_v24
python -m converged_sim.native_queue_check --out results/native_queue_v24_replay

The runner was refactored only after the original result to expose its audit
for regression tests. Original native_queue_v24/freeze.json records the prior
runner hash. Fixture/source/native outputs were not changed. A second run in
a new directory must record the current runner hash.
