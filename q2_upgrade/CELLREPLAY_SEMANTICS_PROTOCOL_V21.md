# V21 primary implementation semantics and development-only feasibility

## Material Passport

ARS-Codex source verification/execution under autonomous research authority,
2026-10-12. No new control-flow experiment or innovation certificate.

Source pin2ca662cb01a222dd7fcc10f9ed79293803b4ef21; inspect
src/frontend/cellular_queue.cc,.hh and cellularshell.cc, obtained from observed
GitHub tree paths. Source text only; no build/execution of upstream code,
root/network namespace operations or installs. GitHub tree requests subsequently
hit an API rate limit; stop those calls rather than bypassing that API limit.

Verified selected implementation contract: max content/PDO budget1400bytes;
heavy trace integer millisecond timestamps, duplicates allowed; light records
timestamp, integer base delay and light PDO vector; size-offset table100byte
increments, floating offsets rounded by the replay. All incoming packets go
through a delay/light release planner with nondecreasing end-release clamp;
light bypass is conditional on an empty downstream link queue. The timer option
defaults0 in this source, not automatically5ms/calibrated. Compare code with the
primary NSDI2025 description; do not silently equate paper and CLI defaults.

Before any actual trace values are opened, screen only the sealed DEVELOPMENT
groups T-Mobile/stationary-good and T-Mobile/weak-signal. Components: both
directions' delay-light-pdo and latency-offset files, eight members total.
Calibration driving and every Verizon RESERVED component remain unopened.
Do not open any heavy PDO member this stage. Source archive/hash/split must
match; read selected members via bounded streaming, no extraction to paths.

Freeze loader/protocol/source receipts before screening. Verify numeric schema,
nondecreasing light timestamps, light PDO order/nonnegativity, nonempty vectors,
offset sizes starting100 with100 increments, and finite offsets. Preserve member
SHA/CRC-read completion and numeric summaries; invalid rows fail visibly without
dropping/removing them. Record count, duplicate timestamps, gap, first/last time,
base-delay min/P50/P99/max and fraction>=20/40ms. Also report size compensation
at declared CONTENT lengths150,600,1200bytes. These are not application payload
sizes; the earlier1500B bulk contract is outside this source's accepted range.

Base-delay/offset distributions are feasibility diagnostics, not measured
control P99, physical lower bounds, impossible-SLO proofs, channel capacity,
new random trials or means for retrospective load normalization. Interpolation,
release-order clamp, active-state persistence, offsets and heavy service must
be retained in any eventual replay. No deadline, selection or reserve split may
be changed solely to obtain passing experimental outcomes. Report infeasibility
or unresolved calibration assumptions instead of claiming a radio-safe method.
