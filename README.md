# Converged Networks: control-flow tail latency and CellReplay queue-accounting audit

Reproducible **research-code repository** for a Converged Networks course project (October 2026). This repository intentionally contains **code, configuration, automated tests, and reproducibility notes only**. It does **not** contain the paper, slides, LaTeX source, or large raw packet-level experimental archives.

## Scope and limitations

The frozen replay investigation studies loss-triggered queue-state/accounting discrepancies and the resulting bias in mixed-traffic control deadline metrics. Analyses distinguish the native replay accounting behavior from corrected counter semantics and policy controls. This is a simulation and replay-source audit, **not** evidence of a production-network guarantee, a new scheduling algorithm, or generalizable wireless performance.

The original 20 ms deadline condition was **not met** in the examined runs. The 40 ms deadline is a sensitivity analysis. Repeated flow-phase tests reuse an underlying radio-service trace; they are **not independent field captures**.

## Environment and quick checks

- Python 3.11+; core Python simulation/tests use the standard library.
- C++ compiler and a compatible ns-3 installation are required for native validation programs (see `ns3_validation/README.md`).
- Run commands from the repository root:

```bash
python -m unittest discover -s tests -q
python -m converged_sim --help
```

To run the small self-contained example (select a *fresh* output directory):

```bash
python -m converged_sim sweep --config example_config.json --out results/example
python -m converged_sim audit --input results/example
```

Some data-audit and figure commands require original experiment artifacts, which are deliberately distributed **outside this repository**. Failing to find a raw input is not equivalent to a failed built-in unit test.

## Where to look

- `converged_sim/`: model, queue accounting, audit, plots and CLIs.
- `ns3_validation/`: ns-3/C++ validation scenarios, fixtures and replay helpers.
- `tests/`: automated Python regression tests.
- `factorial_configs/`, `confirmatory_configs/`, `mechanism_configs/`: frozen simulation designs.
- `q2_upgrade/*.json`: immutable experimental configuration, admission and audit metadata; selected research evidence notes retained.
- `EXPERIMENT_PLAN.md`: earlier bottleneck experimental protocol (background, not a substitute for the current replay-focused research question).

## Reproducibility caveat

The full historical **raw packet logs, trace inputs, and generated results are not checked into Git** due to size and dataset/provenance constraints. To regenerate every published analysis, obtain the separate original research-data archive, place it at the paths described by the audit tools, and run the relevant CLI against those files. Without those external inputs, the repository supports source inspection, unit tests, and independently generated synthetic experiments—but not a full replay of every reported raw-data statistic.

No secret keys, credentials, or proprietary access tokens are intended to be included. Preserve third-party notices and verify upstream licenses when importing external code or traces.
