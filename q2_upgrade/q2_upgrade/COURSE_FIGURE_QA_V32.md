# V32 figure QA receipt

## Material Passport

ARS-Codex local scientific figure verification, 2026-10-13. Figure scope:
five traffic phases per configuration on two reused service prefixes.

Inputs: `results/course_repeats_audit_v32/audit.json`, status
PASS_SAVED_RAW_AND_NATIVE_RELEASE_RECONSTRUCTION. All raw summary/derived CSV
hashes were checked before plotting.50 runs /10 configurations /500000 measured
controls /12196690 all-flow raw records.

Two successful separate calls wrote:

- results/course_repeats_figures_v32b
- results/course_repeats_figures_replot_v32b

Both generated SVG SHA256:
604bea274d7d3ecc52cf4398347550f36aa00272a82cb67deddffe7d5dac7934

The first SVG was rasterized through bundled Node/sharp to2250x855 PNG.
The image was opened and visually inspected: all three panels, ten configuration
positions per panel, five-run dots, median/range markers, axes, legend and
deadline/scope captions visible without cropping or overlap. The ranges are not
confidence intervals. The primary20ms failures are prominently retained.

This verifies the generated figure, not an IEEE manuscript's page layout.
No complete paper or Word/PDF layout has been checked by this receipt.
Earlier pre-output assertion failures are preserved in V32_PLOT_FAILURE_RECORD.md.
