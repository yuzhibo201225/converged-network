# Frozen 30-seed confirmatory simulation

## Material Passport

- Origin Skill: ARS-Codex experiment-agent
- Origin Mode: run / prospective freeze
- Freeze Date: 2026-09-19 Asia/Shanghai
- Version Label: confirmatory_v1
- Verification Status: FROZEN BEFORE INSPECTION OF CONFIRMATORY OUTCOMES

## Purpose and status

This is an independent-seed confirmation of the effect pattern identified in the completed 10-seed exploratory factorial experiment. The load grid and primary rule were informed by the exploratory stage, so this is not a claim of preregistration before all study data. It is prospectively frozen before any outcomes from seeds 1000–1029 are generated or inspected. Exploratory seeds 0–9 will not be pooled into the primary confirmatory estimates. The confirmation deliberately strengthens service-mean control and therefore is not pooled with the earlier trace version.

## Frozen design

- Model: the same finite-buffer FIFO packet/event rules used for the audited exploratory experiment, with an opt-in exact-window-balanced service-trace construction.
- Service regimes: constant 1.0/1.0, moderate 0.85/1.15, and strong 0.7/1.3. Warmup and measurement each contain an even integer number of 5T service blocks. Within each window, exactly half of the blocks use each state; the state ordering is deterministically shuffled per seed and reused across regimes. Thus both windows have service mean exactly 1 without post-hoc scale drift.
- PMR levels: 1, 1.5, 2, 3, with the existing ON = 1T and OFF = (PMR − 1)T construction.
- Seeds: the 30 new paired seed blocks 1000–1029.
- Loads: the complete 32-point exploratory analysis grid plus 0.96, 0.97, 0.98, 0.99. Every seed × PMR × service-regime arm uses the same 36-point grid. The four added near-capacity points tighten upper censoring; they do not authorize loads at or above 1.
- Sampling: 1,020 control periods of warmup (204 service blocks) and 10,020 measured control packets (2,004 service blocks) per run. Both windows also contain whole PMR 1.5/2/3 cycles.
- Primary deadline: 1T. Sensitivity deadlines: 0.5T and 2T, reclassified from the same packet outcomes.
- No adaptive load selection, seed replacement, arm deletion, or model change is allowed after outcomes are inspected. `refine_step = 0.1` is set only to suppress additional between-grid points because every adjacent gap is at most 0.05.

## Frozen primary analysis

A load qualifies when the median across the 30 run-level delivered-control P99 values is strictly below 1T and the median deadline-miss fraction is strictly below 1%. Dropped or unfinished control packets count as misses and do not enter delivered-packet P99. For each PMR × service regime, `Lcrit` is the highest point in the contiguous qualifying prefix. Later recovery and left/right censoring must be reported; no continuous threshold will be interpolated between grid points.

The primary contrasts are PMR-induced boundary erosion, `E(p,v) = Lcrit(1,v) − Lcrit(p,v)`, and the difference in erosion relative to constant service. Any contrast requiring a censored boundary remains a bound or a within-grid descriptor rather than a point estimate. A zero, reversed, or unresolved interaction is a valid confirmatory result.

Uncertainty will use a paired seed-block bootstrap of the entire 36-load curve: one common resampled seed vector is applied to every load, PMR, and service regime; each bootstrap replicate recomputes qualification, boundaries, erosion, and interactions. The frozen bootstrap settings are 10,000 replicates, bootstrap seed 20260919, and 95% percentile intervals on observed grid endpoints. Censoring frequencies and the fraction of estimable replicates are reported separately; if fewer than 90% of replicates yield an uncensored contrast, no directional confirmation is made. Censored replicates are not silently converted to numeric thresholds.

## Integrity gates

1. All three sweep processes must exit 0 and write into previously nonexistent directories.
2. Each source sweep must pass the raw-packet audit before cross-regime analysis.
3. Configuration, simulation-critical source files, and outputs receive SHA-256 receipts.
4. Cross-regime pairing, offered work, full-trace service mean, and realized measured-window residuals are reported.
5. Confirmatory conclusions use only seeds 1000–1029. Exploratory results remain contextual and visibly separate.
6. Mechanism instrumentation and timescale/phase experiments use separate outputs and cannot replace this confirmatory run.

## Scope

The evidence remains limited to this synthetic FIFO queue, the specified ON/OFF family, finite buffer, service-block timescale, and normalized deadline. It does not establish performance of a wireless MAC/PHY, TCP, retransmissions, or a physical robot.
