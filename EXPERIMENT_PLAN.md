# Experiment plan: burstiness × service variability

## Material Passport

- Origin Skill: ARS-Codex experiment-agent
- Origin Mode: plan and exploratory run
- Origin Date: 2026-09-17
- Verification Status: exploratory and held-out 30-seed confirmation raw-audited; mechanism_v1 raw-audited on 2026-09-20
- Version Label: interaction_plan_v1

## Execution status (2026-09-20)

The 10-seed, three-regime coarse sweep and shared 0.01 refinement have completed. All six source sweeps passed per-packet audit (3,840 runs; 38,407,680 measured control-packet records); `results/factorial_refined_analysis/source_audit_receipts.json` records source hashes and fresh PASS receipts. The paired merged-summary analysis and main P99 figure are in `results/factorial_refined_analysis/`. The interpretation in `REFINED_REPORT.md` is exploratory: the constant-service PMR 1/1.5/2 boundaries remain right-censored at 0.95, so a positive boundary interaction is not established.

Before the 30-seed confirmation, a method audit found that the exploratory full-interval normalization left a cross-regime measured-window mean-service spread of 0.002611. The confirmatory design therefore uses a separate, opt-in exact-window-balanced trace mode with 1,020T warmup and 10,020T measurement. Each window contains an even number of 5T blocks and exactly equal high/low counts, giving service mean 1 in both windows for every regime and seed. The 36-load grid, seeds 1000–1029, model version, and paired whole-curve bootstrap are frozen in `confirmatory_configs/FROZEN_PLAN.md`. These outcomes are not pooled numerically with the earlier trace version.

The held-out confirmation is complete: all three sources passed raw audit (12,960 runs; 129,859,200 control-packet rows), cross-regime measured service/load spreads are exactly zero, and 10,000 paired whole-curve bootstrap replicates completed. PMR-3 boundaries are 0.73, 0.61, and 0.50 for constant, moderate, and strong service. The interaction relative to constant service remains unresolved because the constant PMR-1/1.5/2 boundaries are right-censored in every bootstrap replicate. Deadline sensitivity at 0.5T and 2T is complete.

The separately frozen `mechanism_v1` follow-up is also complete and raw-audited (180 runs; 1,803,600 control rows). At rho=0.60, the PMR-3 tail-latency increase is carried by queue work and waiting time while P99 service time is unchanged. Full results and integrity receipts are in `results/factorial_confirmatory_analysis/CONFIRMATORY_REPORT.md`.

## Research question and estimands

**Question.** Under controlled mean offered load, how do bursty bulk arrivals and time-varying bottleneck service jointly change the admissible offered-load region in which periodic control traffic satisfies tail-latency and deadline-miss requirements?

For PMR `p` and service regime `v`, let `Lcrit(p,v)` be the highest load in the contiguous passing prefix of the measured grid. A load passes only when the median across independent runs of delivered-control P99 is strictly below one control period and the median deadline-miss fraction is strictly below 1%. Dropped or unfinished control packets count as misses, not as delivered-packet latencies. Report left/right censoring and later recovery instead of forcing a boundary.

- **Burstiness-induced erosion:** `E(p,v) = Lcrit(1,v) - Lcrit(p,v)`.
- **Interaction contrast:** `I(p) = E(p,variable) - E(p,constant)`.
- **Primary descriptive display:** P99 / control period versus target offered load, stratified by PMR and service regime; show the full dynamic range and a clearly labeled zoom around the deadline so very large high-load tails do not visually flatten the crossing. A companion table gives `Lcrit`, `E`, and `I` only where the boundaries are observed.

These are operational definitions, not expected results. A zero, reversed, censored, or non-monotone effect is a valid finding.

In the present envelope, ON lasts one control period and OFF lasts `(PMR − 1)` periods. Thus changing PMR also changes the burst-cycle duration; a measured PMR contrast is a contrast between these specified traffic processes, not proof of a universal PMR-only law.

## Design and controls

| Factor | First-stage levels | Control requirement |
| --- | --- | --- |
| Target offered load | 0.20–0.95 in 0.05 steps; first observed crossing refined by 0.01 | Use the union of refinement loads across all PMR × service-regime arms, and run every arm on that common grid. Within a seed, load, and service regime, all PMRs have exactly the same offered packet count/work and service trace. Across loads, only bulk mean work increases. |
| Bulk PMR | 1, 1.5, 2, 3 | ON/OFF envelope, fixed bulk packet size; same control/sensor arrivals and packet sizes. |
| Service variability | Constant rate, moderate variation (nominal 0.85/1.15), and strong variation (nominal 0.7/1.3) | Normalize each seed's realized service trace to mean rate 1 over the offered interval. Use the same underlying high/low draws across regimes and report the 5T service-block timescale. |
| Seeds | 10 for screening; a separately frozen 30-seed confirmatory run regardless of the screening direction | Preserve seed pairing across every load, PMR, and service regime. Do not call the current seed-range a confidence interval. If the confirmatory run is not executed, keep all findings labelled exploratory. |
| Deadline | 1 control period primary; 0.5 and 2 periods sensitivity | Reclassify misses from the same packet outcomes. |

The current simulator already supports the PMR/load sweep and a variable-rate service trace. The initial `example_config.json` run is **exploratory**: it tests that branch and its data pipeline, not the two-factor interaction. Its independently sampled low/high service blocks do not guarantee an identical realized mean to a constant-rate comparison. Before the confirmatory factorial sweep, freeze a mean-matched service-regime implementation and tests; do not merge different model versions as if they were one experiment.

The exploratory implementation normalizes the **full offered interval** to unit mean. With its 5T service blocks and 204T/10,002T warmup/measurement split, the measured window is not separately normalized: across the first ten seeds, its same-seed service-mean spread between regimes reaches 0.002612 (0.261% of capacity). Every exploratory factorial report must publish this residual and the realized measured-window load. The confirmatory implementation does not silently reuse this approximation: it uses separately balanced warmup and measurement windows, and its tests require exact means and a common underlying state pattern across regimes.

## Mechanism and robustness follow-up

1. Record queue work ahead of each control arrival and whether bulk ON overlaps a low-service interval. This distinguishes backlog accumulation from simple average-load explanations.
2. Test at least one shorter and one longer service-block duration, with all regimes mean-matched. PMR alone may not capture the arrival–service timescale interaction.
3. In a separate alignment experiment, hold PMR, bulk count, mean service, and service trace fixed while shifting the relative burst/service phase. Treat this as a different intervention, not as a PMR effect.
4. Vary buffer capacity and normalized deadline only after the primary design is frozen. Keep wireless MAC, retransmissions, TCP, and real-device claims outside the model's scope.

For uncertainty, use a paired seed-block bootstrap of the *entire load curve* when enough independent seeds are available; recompute boundaries and contrasts in each resample, preserving within-seed pairing. Report the bootstrap interval and censoring frequency, not a made-up continuous threshold between grid points. This analysis is implemented in `converged_sim/bootstrap_analysis.py` and completed for the frozen confirmation.

## Execution stages and acceptance gates

1. **Existing-code check:** run the unit suite. This is a software check, not research evidence.
2. **Exploratory variable-service sweep:** run the frozen `example_config.json` into a new output directory. Keep raw packets, run summaries, configuration, and code version. Audit raw-versus-summary agreement, PMR pairing, and plot regeneration before reading boundary values.
3. **Mean-matched factorial implementation:** add constant and variable service regimes plus tests for exactly equal realized mean, common trace draws, PMR pairing, event ordering, and deterministic replay. Freeze the code/config and rerun all arms; the exploratory run cannot substitute for this.
4. **Confirmatory analysis — complete:** calculate `Lcrit`, erosion, interaction, seed-level spread and paired bootstrap uncertainty. Examine load-grid censoring and non-monotone recovery. Report negative findings without selecting a favorable subset.
5. **Mechanism check — core measurement complete:** per-control exact backlog, waiting/service decomposition, and preceding ON/low-service overlap have been measured with new paired seeds. Separate block-timescale and forced-phase interventions remain optional robustness extensions and are not part of the completed primary claim.

The user requested a one-page Word proposal on 2026-09-18. The new interaction-study proposal is retained as a deliverable, not an experimental input. The earlier PMR-only proposal remains historical work. The pasted venue and literature claims are search leads, not verified evidence or a basis for asserting novelty.
