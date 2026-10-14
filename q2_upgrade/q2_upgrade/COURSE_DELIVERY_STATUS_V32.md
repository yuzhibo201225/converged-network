# Course delivery checkpoint V32

## Material Passport

ARS-Codex continuation, 2026-10-13. Author details supplied by user:
Zhenyu Ding, student212524010003, University of Limerick. Target format:
English IEEE two-column conference paper, maximum5pages, course deadline16Oct.
No external uploads, teacher messages or changes to Overleaf access settings.

## What this phase contributes

The V32 protocol adds five paired bulk phase repetitions to ten core replay
configurations:50 runs, each10000 measured control packets. It is a sensitivity
followup on already opened T-Mobile and Verizon prefixes, not five independent
radio trials. Frozen source/configuration and all raw outcomes are retained.

The new audit implementation reconstructs every published run metric directly
from raw packet outcomes without calling the simulation's summarize function.
It separately verifies native release parity, paired full-interval source volumes,
event identities, delivered timestamps, final accounting invariants and evictions.
Its output carries the script and result hashes. Queue simulation is not rerun
by that audit; do not call it an independently implemented queue validation.

Commands from repository root:

```powershell
python -m converged_sim.course_repeats --out results/course_repeats_v32_fresh
python -m converged_sim.audit_course_repeats --input results/course_repeats_v32 --out results/course_repeats_audit_v32_fresh
python -m converged_sim.plot_course_repeats --input results/course_repeats_audit_v32 --raw results/course_repeats_v32 --out results/course_repeats_figures_v32_fresh
```

Prior V20/V23b/V25/V31 data/native prerequisites must be present. Every output
directory must be fresh. Read the actual audit/figure receipts before accepting
completion; a protocol or this note alone is not a PASS certificate.

## Contribution scope and remaining decisions

The strongest source-bound candidate is a loss-triggered absorbing bypass
suppression path in the pinned CellReplay finite-DropTail implementation.
The conservation identity C-R=D and selected native counter/service fixtures
support its mechanism. The held-out operator input supports transfer of that
mechanism, not successful SLO restoration. Generic priority and push-out remain
known baselines. No new scheduler, new mathematical theorem, universal failure
boundary, confirmed global novelty or JCR Q2 readiness is claimed.

This reliability subclaim is related to, but narrower than, the original PMR /
maximum admissible load question. V32 tests only rho0.60. It cannot independently
establish a collapse threshold or a shifted maximum offered load.

## Actual document delivery constraints

- Overleaf project opened as Restricted; no private project contents were read
  or edited. A local import-ready source package is the available route.
- Bundled Tectonic has passed a real smoke compile. No full manuscript has yet
  been compiled or visually checked in this checkpoint.
- The course brief forbids an AI-generated literature review and requires8
  personally read peer-reviewed sources. The user has requested AI generation;
  an explicitly disclosed study draft can be produced, but it cannot truthfully
  be labeled course-compliant on this point. Human reading is not attested.
- Word/PDF final paper,10-minute presentation and packaged submission materials
  are still pending. Do not label experiment completion as delivery completion.

## Additional verified source metadata

Primary publisher page checked2026-10-13:
Qianru Lv, Xuyan Jiang and Xiangrui Yang, "Making programmable packet scheduling
time-sensitive with a FIFO queue," Journal of Cloud Computing, vol12,
article141,2023, DOI10.1186/s13677-023-00518-3.
https://link.springer.com/article/10.1186/s13677-023-00518-3

This is verified reference metadata and source discovery, not a statement that
the student personally read it. Its AIAO scheduling contribution is prior work;
do not label ingress/egress admission or time-sensitive FIFO scheduling as ours.
