# V21--V23 source and native-method verification completed

## Material Passport

ARS-Codex assistant investigation/model verification,2026-10-12--13. Source
screening and selected native-method differential check completed. No new
mixed-flow experiment, reserve exposure, outside reviewer or real delivery
measurement. Research goal remains active.

## Primary source contract verified

[Pinned CellularQueue source](https://github.com/williamsentosa95/cellreplay/blob/2ca662cb01a222dd7fcc10f9ed79293803b4ef21/src/frontend/cellular_queue.cc)
and its header/CLI are saved with exact hashes under
`results/cellreplay_code_source_v21`. Upstream commit matches the dataset pin.
Selected method bytes in the derivative C++ fixture are checked byte-for-byte
before compilation. Original GPL notices retained; fixture/translation notice
does not relicense the wider repository.

| Item | Verified source behavior | Experiment implication |
|---|---|---|
| Content/PDO budget |1400 bytes|Do not feed the earlier1500-byte bulk contract unchanged|
| Light records |integer time/base delay, PDO list|Client-goodput samples are not a substitute|
| Base choice |float32 interpolation, integer truncation|Reproduce rounding, not an arbitrary continuous curve|
| Idle timer |CLI default0; explicitly configurable|5ms is a sensitivity, not validated per-record calibration|
| Release order |nondecreasing global end-release clamp|Downstream priority alone does not change the front-stage release plan|
| Light bypass |allowed only when downstream link occupancy counter is0|A planned light flag is not a received timestamp|

The [NSDI2025 primary paper](https://www.usenix.org/system/files/nsdi25-sentosa.pdf)
Section4.3--4.4 describes light/heavy service, size compensation, dynamic delay
and a calibrated fallback timer. It holds the selected base delay during active
periods to avoid double counting delay through PDO gaps. Therefore these are
existing design mechanisms, not new ones invented here. Selected implementation
inspection is not full empirical replication of the paper or proof of physical
latency fidelity. Recorder-side RTT/one-way conversions remain uninspected;
the field is established as a replay delay input, not a new direct measurement.

GitHub tree API later reported a rate limit. Those calls stopped; no credential
or provider-limit bypass attempted. A record-directory browser request also
failed. Missing recorder details are left unresolved rather than inferred.

## Development-only data semantics

Eight selected light/offset members screened with strict schemas and complete
member SHA/CRC reads. Heavy PDO, T-Mobile/driving calibration and all18 Verizon
reserved members remain unopened by these scripts.

| Development group | Light records/direction | Source endpoint/ms | Base delay median/P99/ms |
|---|---:|---:|---:|
|stationary-good|21187|1072408|24 /29|
|weak-signal|8867|891011|27 /44|

The up/down source base-delay arrays have the same displayed summaries; PDO
counts and offsets differ. Source-record quantiles are NOT control-packet
quantiles. Weak-signal raw maximum base input247ms is retained in the original
complete member; no clipping. Screen results are
`results/cellreplay_development_v21/development.json`, audit status
`DEVELOPMENT_SCREEN_COMPLETE_NOT_CONTROL_VALIDATION`.

## Planned-release diagnostic

At20ms control period, warm400 periods then consecutive full10000-control
windows, native-planned release P99 values are:

| Group/direction/content bytes | Consecutive cohort planned P99/ms |
|---|---|
|stationary/up/150|23,23,23,23,23|
|stationary/up/182|24,24,24,24,24|
|stationary/down/150 or182|28,28,28,28,28|
|weak/up/150 or182|31,32,51,77|
|weak/down/150 or182|32,33,52,78|

Timer0 and5 produce exact identical logical records in these isolated-control
cases.16 configurations,72 cohort/configuration rows,720000 measured planning
records; not72 independent sessions or720000 independent radio trials. The
cohorts use a single continuous planner state, never trace looping/resetting.
Incomplete trailing cohorts are not scored; source traces themselves remain
complete and unchanged. This table does not characterize every remaining
trace interval, every traffic mix or a different fallback timer.

Every listed full cohort has planned P99>20ms. A packet cannot be delivered
before its planned release on this path, but these are **intermediate-stage
results**, not native full-emulator/real control P99. Two-period40ms sensitivity
has room in stationary cohorts and some early weak cohorts, but late weak
cohorts already exceed it before heavy service. No deadline was changed to
obtain positive outcomes. Adding bulk changes the active-state trajectory, so
the isolated-control result is not a universal mixed-traffic impossibility proof.

## Native-source differential evidence

V23 compiles the exact selected C++ methods and original compensation/clamp
snippet in a standalone fixture, omitting root/network/TUN/IP/queue setup.
After the separately documented compiler-PATH environment repair, all720000
development raw planning rows match Python **in every field**, plus36 synthetic
rows exercising active exhaustion, timer boundaries, offsets and clamps.
Native build exits0. Executable SHA256:
`671cb115767d3deca5ca56095912b3424ce183cfab00afc8aedceae231201fde`.
Freeze SHA256:
`c42fd761cd3fbff07b8686b15554d683825e5bc5bfe022397dce6be03e04a18e`.
Audit: `results/native_release_v23b/audit.json`,
`PASS_SELECTED_NATIVE_METHODS`. Failed original build directory and runner
retained; no upstream method/trace/threshold changed by the environment repair.

This rules out a Python-vs-selected-C++ translation mismatch for the tested
release planner inputs. It does not verify the actual link/dequeue/drop behavior
or native full-shell receiver times. Global networking was never executed;
heavy and reserved members remain closed. An external expert did not review
this implementation. The checked native source remains an existing baseline.

## Next required verification, not a paper claim

Before mixed-flow comparison, verify finite-queue admission/drop accounting and
light-to-heavy handoff end to end. Source increments its link occupancy counter
on enqueue and decrements on output; interaction with a dropping queue has not
yet been checked against the underlying queue implementation. This is a concern,
not a confirmed bug. Likewise a loss-rate option's actual injection behavior
has not been established from the selected methods. Do not hide these omissions
behind a low P99 graph or claim that upstream priority necessarily fails.

Then freeze a source-faithful baseline and explicit size/framing contract,
preserve original20ms/40ms feasibility results, compare any new shaping choice
against existing mechanisms, and only then open calibrated/held-out inputs
within their sealed roles. No innovation or JCR Q2 submission readiness follows
from this differential check alone.
