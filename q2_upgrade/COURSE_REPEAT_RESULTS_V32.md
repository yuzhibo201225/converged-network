# Five-phase course evidence V32

## Material Passport

ARS-Codex saved-data validation, 2026-10-13. Status: ANALYZED with raw
metric reconstruction and source-native release parity. This does not
claim a fresh independent simulation rerun, external reviewer approval,
complete course compliance, global novelty, or JCR Q2 readiness.

## Verified population

50 runs / 10 configurations / 5 paired bulk phases each;
12,196,690 all-flow raw records; 500,000 measured controls;
4,929,935 source release records compared against the native fixture.

Each run has 10,000 measured controls after 8s warmup, over a fixed 208s
horizon. Same service prefix and critical arrivals are reused. Five phase
ranges do not estimate population uncertainty or independent radio days.

Mean offered bytes and traffic mix are exactly paired over the whole 208s
interval, including each 300ms cycle. Post-warmup bulk volumes can differ
because the 8s warmup cuts a cycle; exact window bytes are disclosed in
`volume_pairing.json`, rather than asserted equal.

## Results (median [min, max], five runs)

| Prefix / PMR / variant | P99 ms | Miss20 % | Miss40 % | Bulk delivered % | Pass40 runs |
|---|---:|---:|---:|---:|---:|
| T-Mobile / 1 / O | 31 [31, 31] | 99.97 [99.97, 99.97] | 0.01 [0.01, 0.01] | 99.99 [99.99, 99.99] | 5/5 |
| T-Mobile / 1 / F | 31 [31, 31] | 99.97 [99.97, 99.97] | 0.01 [0.01, 0.01] | 99.99 [99.99, 99.99] | 5/5 |
| T-Mobile / 1 / P | 31 [31, 31] | 99.97 [99.97, 99.97] | 0.01 [0.01, 0.01] | 99.99 [99.99, 99.99] | 5/5 |
| T-Mobile / 1 / X | 31 [31, 31] | 99.97 [99.97, 99.97] | 0.01 [0.01, 0.01] | 99.99 [99.99, 99.99] | 5/5 |
| T-Mobile / 3 / O | 53 [53, 53] | 100 [100, 100] | 29.58 [28.96, 30.57] | 62.71 [62.61, 62.96] | 0/5 |
| T-Mobile / 3 / F | 47 [45, 47] | 99.97 [99.97, 99.97] | 4.08 [3.67, 4.8] | 95.12 [94.57, 95.81] | 0/5 |
| T-Mobile / 3 / P | 36 [36, 38] | 99.97 [99.97, 99.97] | 2.56 [2.25, 2.96] | 95.15 [94.62, 95.86] | 0/5 |
| T-Mobile / 3 / X | 37 [36, 39] | 99.97 [99.97, 99.97] | 0.62 [0.56, 0.96] | 95.08 [94.56, 95.82] | 5/5 |
| Verizon / 3 / O | 39 [39, 40] | 66.07 [65.6, 68.04] | 18.37 [18.03, 18.8] | 45.21 [45.04, 45.58] | 0/5 |
| Verizon / 3 / F | 39 [39, 39] | 50.15 [49.52, 52.78] | 18.1 [17.74, 18.47] | 46.19 [46.02, 46.54] | 0/5 |

## Interpretation boundary

The entire primary 20ms population fails. An accounting correction does
not establish SLO restoration. The tested grid is only rho0.60; it does
not identify the maximum admissible load or a shifted collapse boundary.
Priority and push-out are established component baselines, not a newly
invented scheduler. The independently source-tested absorbing-counter
mechanism is a candidate reliability contribution, not global priority.

## Statistical fallacy scan: 11/11 checked

1. Simpson: prefix/PMR/variant strata retained; no pooled causal summary.
2. Ecological: phase outcomes are not inferred as per-device reliability.
3. Berkson: two deliberately selected prefixes; external generalization cautioned.
4. Collider: no fitted adjustment model; delivered-only P99 is conditional.
5. Base rate: misses use all 10,000 controls, not completed controls.
6. Regression to mean: matched phases retained, not favorable before/after selection.
7. Survivorship: drops/unfinished counted as misses; P99 explicitly delivered-only.
8. Look elsewhere: all 50 frozen cases and all failed primary outcomes retained.
9. Forking paths: V32 is a prospective followup to exploratory V27-V31,
   not a retrospectively preregistered discovery; protocol is byte-frozen.
10. Causality: intervention contrasts apply within the replay model only.
11. Reverse causality: source-code invariant plus timed intervention,
    not an observational directional inference about real radio.

No hypothesis tests, p-values, population confidence intervals or numerical
publication-readiness score are computed from these five phase runs.

## Reproduce

```powershell
python -m converged_sim.course_repeats --out results/course_repeats_v32_fresh
python -m converged_sim.audit_course_repeats --input results/course_repeats_v32 --out results/course_repeats_audit_v32_fresh
python -m converged_sim.plot_course_repeats --input results/course_repeats_audit_v32 --raw results/course_repeats_v32 --out results/course_repeats_figures_v32_fresh
```

Run from the repository root. Fresh output directories are required.
Source/native prerequisites remain the saved V20/V23b/V25/V31 artifacts.
The raw data are local and are not uploaded by these commands.
