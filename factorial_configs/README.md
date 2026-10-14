# Mean-matched service-variability screening configs

All three `*_coarse.json` files use the same control/sensor/bulk packet settings, 16 target offered loads, PMR arms 1/1.5/2/3, 10 paired seeds, and 10,002 measured control packets after warmup. Only the nominal service-rate variation differs: constant 1/1, moderate 0.85/1.15, or strong 0.7/1.3 work per control period.

`trace_normalize_mean: true` means the generated service trace for each seed is scaled to realized mean 1 over the offered interval. The same seed is intended to retain the same underlying high/low draw sequence across regimes. The `refine_step` value of 0.1 exceeds the 0.05 coarse spacing, so the existing sweep code adds no adaptive points in this screening run; all three regimes therefore use exactly the same grid. Any refined follow-up must use the union of crossing intervals across *all* regimes and PMR arms.

These are synthetic normalized capacity scenarios, not calibrated wireless-device traces. Their 10-seed boundaries are exploratory and their seed ranges are descriptive, not confidence intervals. The separate 30-seed confirmatory design in `../EXPERIMENT_PLAN.md` remains unrun.
