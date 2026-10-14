# V32 test execution receipt

## Material Passport

ARS-Codex local software verification, 2026-10-13. This is an execution receipt,
not an independent scientific review or a publication-readiness assessment.

Command executed from the repository root using bundled Python:

```powershell
python -m unittest discover -s tests -q
```

Observed process exit code0, `Ran 194 tests in 250.306s`, `OK`.
Earlier full run before the two plot gate tests:192 tests in30.334s, exit0.
The later duration includes competing local full-data audit workload and must
not be treated as a simulator-performance or network-latency measurement.

New eight test cases cover:

- phase0 exact preservation of the earlier source arrivals;
- paired per-cycle volumes, critical arrivals and interval bounds;
- deterministic five-seed phase generation;
- streaming canonical source hash equivalence;
- nearest-rank quantile reconstruction;
- losses, unfinished controls, warmup exclusion and equality-at-deadline misses;
- rejection of a non-PASS plot input without creating a output directory;
- refusal to overwrite a plot directory.

Full-data saved-output audit, figure regeneration and visual inspection have
separate receipts. Passing unit tests does not substitute for those checks.
