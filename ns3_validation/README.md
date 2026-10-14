# ns-3.47 packet-level validation

This directory contains an independent packet-level validation of the synthetic
FIFO study. It is a validation layer, not a wireless-MAC model: three UDP
sources (control, sensor, and bulk) enter a router over fast point-to-point
access links and contend at one finite point-to-point bottleneck.

## Frozen semantics

- Control packets are 150-byte IPv4 packets every 20 ms. The normalized
  deadline defaults to one control period.
- Sensor packets are 600-byte IPv4 packets every two control periods.
- Bulk packets are 1500-byte IPv4 packets. `R` is the peak-to-mean rate ratio;
  `tauB` is the full ON/OFF cycle divided by the control period. The ON duration
  is `tauB / R`, so amplitude (`R`) and cycle time (`tauB`) are independent.
- The target aggregate offered load is `rho * nominal bottleneck rate`. Only
  bulk mean rate changes with `rho`; control and sensor traffic stay fixed.
- The default bottleneck is 6 Mbit/s with a 150,000-byte root queue. `fifo` is
  one byte-limited FIFO. `priority` is a non-preemptive two-band strict-priority
  queue with the same aggregate byte limit; only EF-marked control traffic uses
  the high band.
- `alternating` service switches between mean-matched low/high rates. The
  deterministic phase is a function of `seed` and `run`, so configurations
  with the same pair share the phase fraction.
- Warm-up and measurement windows must contain whole burst, sensor, and (when
  enabled) service cycles. This makes finite-window mean-load matching explicit
  instead of relying on a long-run approximation.
- Offered load uses requested IPv4 packet bits divided by nominal mean link
  rate. ns-3 point-to-point framing adds a small serialization overhead. Both
  target and realized IP offered load are therefore written to the summary.

The scenario writes (1) one summary row and (2) one row for every measured
control packet. Lost or still-undelivered packets after the conservative drain
are deadline misses and are not inserted into delivered-packet P99. P99 uses
linear R-7 interpolation. Output paths must be new; the executable refuses to
overwrite any existing result.

## Build on this workspace

The local source is ns-3.47 under
`third_party/msys_extract/ns-3.47`. Use the MSYS2 MinGW64 release build in
`build-mingw`; the earlier UCRT64 binaries failed to initialize. A source or
build directory alone is not a successful validation result. From the
repository root in PowerShell:

```powershell
$ns3 = (Resolve-Path '.\third_party\msys_extract\ns-3.47').Path
$cmake = 'C:\msys64\mingw64\bin\cmake.exe'
& $cmake -S .\ns3_validation -B .\ns3_validation\_build_mingw -G Ninja `
  '-DCMAKE_MAKE_PROGRAM=C:\msys64\mingw64\bin\ninja.exe' `
  '-DCMAKE_CXX_COMPILER=C:\msys64\mingw64\bin\c++.exe' "-DNS3_ROOT=$ns3"
& $cmake --build .\ns3_validation\_build_mingw
$env:PATH = "$ns3\build-mingw\lib;C:\msys64\mingw64\bin;$env:PATH"
```

This standalone CMake target links the already-built ns-3 import libraries; it
does not copy a source file into `scratch/` and does not modify the vendored
ns-3 tree.

The local ns-3 core has the explicitly disclosed initialization-only change in
`WINDOWS_COMPATIBILITY.md`. Apply that change before rebuilding the core on this
Windows toolchain; do not describe these binaries as unmodified upstream ns-3.

## Audited corroboration sweep

```powershell
& .\ns3_validation\validation_sweep.ps1 -OutDir results\ns3_validation_v2
python ns3_validation\audit.py --input results\ns3_validation_v2 --out results\ns3_validation_v2_analysis
```

This fixed 60-run subset records 10,080 control packets per run and compares
two loads, three traffic arms, two queues and five paired phase runs. Existing
output directories are rejected. The audit recomputes P99, misses and delivery
counts from all 604,800 raw control records and checks realized offered-load
and service-phase matching. This is corroboration, not a calibrated replication
of the Python model or a statistically certified admission boundary.

## One run

```powershell
$exe = '.\ns3_validation\_build_mingw\bin\burst-tail-validation.exe'
& $exe --rho=0.60 --R=3 --tauB=5 --queue=fifo --service=alternating `
  --tauS=5 --seed=20260925 --run=1 `
  --summaryCsv=.\results\ns3\run-001-summary.csv `
  --packetCsv=.\results\ns3\run-001-packets.csv
```

Important command options are printed by `--PrintHelp`. Defaults retain 1,000
warm-up periods and 10,000 measured control packets. Use a new output name for
every configuration.

## Minimal smoke sweep

```powershell
& .\ns3_validation\smoke_sweep.ps1
```

The script builds the standalone executable and runs four tiny cases
(`fifo`/`priority` crossed with `R=1`/`R=3`) under alternating service. It makes
a timestamp-and-UUID output directory on every invocation, so it never reuses
or overwrites prior results. These short runs test APIs and output invariants;
they are not inferential evidence for the paper.

## FQ CoDel extension

```powershell
& .\ns3_validation\validation_sweep.ps1 -OutDir results\ns3_schedulers_v3 -Queues fifo,fifo_packet,priority,fq_codel -Seed 20261012
python ns3_validation\audit.py --input results\ns3_schedulers_v3 --out results\ns3_schedulers_v3_analysis
```

`fifo_packet` and `fq_codel` both have a 100-packet root limit; `fifo` and
`priority` retain 150,000 bytes. FQ-CoDel in this version prohibits byte-unit
capacity. Its Target=5ms, Interval=100ms, ECN=false, Flows=1024 and fixed hash
perturbation 0. Only the packet-limited pair is a matched-capacity comparison.
The completed 120-run result and cost are in `q2_upgrade/NS3_SCHEDULER_RESULTS_V3.md`.

## Delayed-feedback candidate (V9)

The new standalone `feedback-validation` target includes the frozen helper
scenario without changing it. Build it with the same MinGW environment:

```powershell
& $cmake --build .\ns3_validation\_build_mingw --target feedback-validation
python -m ns3_validation.feedback_cli sweep --config q2_upgrade/ns3_feedback_v9.json --out results/ns3_feedback_v9_replay --workers 4
python -m ns3_validation.feedback_cli audit --input results/ns3_feedback_v9_replay --out results/ns3_feedback_v9_analysis_replay
python -m converged_sim.ns3_feedback_figure --input results/ns3_feedback_v9_analysis_replay --out results/ns3_feedback_v9_analysis_replay/protection_cost.svg
python -m converged_sim.ns3_fluid_bridge --input results/ns3_feedback_v9_replay --analysis results/ns3_feedback_v9_analysis_replay --out results/ns3_fluid_bridge_v9_replay
```

160 full runs and 16,327,552 all-flow rows completed. Final audit is
`results/ns3_feedback_v9_quantized_analysis/audit.json`, PASS. Original-generation
cohorts include source waiting/loss, with separately reported source-release IP
load. Quantized source replay and actual occupancy counting are post-experiment
audit amendments; earlier failed attempts remain retained, and exact continuous-
clock equivalence is NOT claimed. No tolerance widening or raw data changes.
Six-case development replays are byte-identical; 80 matched-input fluid timing
diagnostics agree on joint-pass classification but not exact P99.

The V8 jittered-service5%--6% bias crossing did not transfer to this periodic
service grid. See `q2_upgrade/NS3_FEEDBACK_RESULTS_V9.md` for this negative result,
priority/FQ-CoDel costs, and model limitations. No deployment certificate.

## Nonperiodic CSV service (V10)

Build separate `renewal-validation`; V9's code/binary stays unchanged. The
frozen configuration is `q2_upgrade/ns3_renewal_confirmation_v10.json`. Replay
commands and completion details are in `q2_upgrade/README.md` and
`q2_upgrade/NS3_RENEWAL_RESULTS_V10.md`.70 service CSVs are generated before
endpoints from the frozen balanced random-duration generator and shared across
three settings. Every CSV/source/executable is bound by retained receipts.

210 full runs and70 post-hoc periodic counterparts complete, both raw audits
PASS. Source-clock replay and actual occupancy checks use declared nanosecond
semantics. Primary reliability family has3 cells,70 fresh runs per cell; it is
not pooled with discovery or the post-hoc counterpart. Synthetic mean-matched
service is not measured radio capacity, and telemetry remains privileged exact
delayed capacity plus constant bias. Stochastic estimator validation is pending.

## Matched dwell-order exploration (V11)

The separate `order_cli.py` uses the unchanged V10 CSV-service executable.
`q2_upgrade/SERVICE_ORDER_PROTOCOL_V11.md` freezes the three orderings and ten
fresh seeds. Low/high service levels, each window's mean and actual contiguous
dwell multisets are matched; cycle-pair sorting changes order and source alignment.
No stationary-radio or reliability-confirmation claim is implied.

```powershell
python -m ns3_validation.order_cli sweep --config q2_upgrade/ns3_order_exploration_v11.json --out results/ns3_order_exploration_v11 --workers 4
python -m ns3_validation.order_cli audit --input results/ns3_order_exploration_v11 --out results/ns3_order_exploration_v11_analysis
python -m converged_sim.service_order_figure --input results/ns3_order_exploration_v11_analysis --out results/ns3_order_exploration_v11_analysis/service_order.svg
```

The audit verifies full packet endpoints using V10's raw/source-clock replay,
regenerates the declared traces and checks generated-input pairing across orders.
Only audited outcomes should be interpreted; the manifest reports run completion.

## Paired elementary-half orientation intervention (V12)

`orientation_cli.py` is a separate implementation; V11 remains unchanged.
Protocol: `q2_upgrade/ORIENTATION_PROTOCOL_V12.md`; results and scope:
`q2_upgrade/ORIENTATION_RESULTS_V12.md`. Elementary durations/boundaries and
generated sources match across LOWFIRST/HIGHFIRST/COINFLIP. Merged contiguous
dwells intentionally change.90 runs completed, all-flow audit PASS,9 selected
replays byte-identical in packets/traces. Ten-seed exploration, not certification.

```powershell
python -m ns3_validation.orientation_cli sweep --config q2_upgrade/ns3_orientation_v12.json --out results/ns3_orientation_v12 --workers 4
python -m ns3_validation.orientation_cli audit --input results/ns3_orientation_v12 --out results/ns3_orientation_v12_analysis
python -m converged_sim.orientation_figure --input results/ns3_orientation_v12_analysis --out results/ns3_orientation_v12_analysis/orientation.svg
python -m converged_sim.orientation_mechanism --raw results/ns3_orientation_v12 --analysis results/ns3_orientation_v12_analysis --out results/ns3_orientation_mechanism_v12
```

Use fresh output names for replays; no overwrite. The secondary interaction
contrast is post-hoc; the primary orientation intervention was frozen. These
outputs do not confirm literature novelty or physical deployment suitability.

## Scope limits

This model validates packetization, IP forwarding, finite qdisc loss, dynamic
link serialization, and a scheduler baseline. It does **not** model a wireless
MAC, channel errors, retransmissions, TCP congestion control, clock error, or
real device processing. Claims based on it must remain within those limits.

