# V28 prospective all-packet native FIFO queue differential

## Material Passport

ARS-Codex source-derived verification,2026-10-13. Use saved V27 development
inputs only; no new/reserved numeric source opened. This addresses the queue
equivalence gap separately from release-planner parity. No novelty certificate.

Compile original DropTail files and three contiguous original service methods
with only a class-qualifier rename. Supply every saved planned mixed release
and every service opportunity, preserving same-time duplicates. Source-derived
attempt/output counter and bypass predicate; compare original and accepted-only
accounting as distinct variants. Match V27 ideal polling and same-time release
batch semantics,16 waiting slots,208000ms observation end.

For each of six load/PMR inputs, compare EVERY packet's completion/drop/unfinished
classification, output timestamp, source-to-output delay and bypass flag against
the corresponding Python FIFO outcomes. Also compare final counter and actual
resident count. Any mismatch fails visibly with retained raw output. This is
not OS/network emulator equivalence, priority validation or independent expert
review. Compile diagnostics and exact selected source provenance are retained.
