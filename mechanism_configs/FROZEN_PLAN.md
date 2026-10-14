# Frozen post-confirmatory queue mechanism follow-up

## Material Passport

- Origin Skill: ARS-Codex experiment-agent
- Origin Mode: mechanism / prospective freeze
- Freeze Date: 2026-09-20 Asia/Shanghai
- Version Label: mechanism_v1
- Verification Status: FROZEN BEFORE INSPECTION OF SEEDS 10000–10029

## Purpose and status

This is a post-confirmatory explanation experiment, not a replacement for the frozen 30-seed boundary analysis. The fixed load `rho = 0.60` was selected after the confirmatory curves were available: it is below the constant-service PMR-3 boundary, close to the moderate-service PMR-3 boundary, and above the strong-service PMR-3 boundary. Therefore all mechanism results are explicitly post hoc and model-internal.

## Frozen design

- Service regimes: constant `1/1`, moderate `0.85/1.15`, and strong `0.7/1.3`, with the exact balanced-window construction used in `confirmatory_v1`.
- Load: one fixed target offered load, `rho = 0.60`.
- Bulk PMR: `1` and `3`.
- Seeds: 30 new paired seeds, `10000–10029`; no confirmatory or exploratory seed is reused.
- Sampling: `1,020T` warmup and `10,020` measured control packets per run.
- Runs: `3 regimes × 2 PMRs × 30 seeds = 180`; measured control rows: `1,803,600`.

## Instrumentation and estimands

Instrumentation is observational and must be outcome-neutral. For every measured control arrival, queue work ahead equals all waiting work plus the exact residual work of the packet currently in service. For delivered control packets, waiting time is service-start minus arrival and service time is completion minus service-start; their sum must equal the original latency. The preceding `1T` window is exactly partitioned to measure bulk-ON exposure, low-service exposure, and their overlap.

Primary mechanism contrasts are paired seed-level PMR-3 minus PMR-1 differences in run-level P99 queue work ahead, P99 waiting time, and P99 service time. The prespecified explanatory pattern is a positive queue/wait contrast with little service-time contrast. The ON/low-service overlap summaries are descriptive alignment evidence, not causal mediation estimates. A null, reversed, or heterogeneous pattern is reportable.

## Integrity gates

1. Unit tests must prove packet outcomes are exactly unchanged when instrumentation is enabled.
2. Each output source must pass a raw mechanism-row audit before cross-regime analysis.
3. PMR arms retain the exact trace, packet counts, offered work, and periodic arrivals within every seed/regime pair.
4. No load, seed, metric, or regime is changed after new-seed outcomes are inspected.
5. Conclusions remain limited to the synthetic finite-FIFO model.
