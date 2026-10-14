# V29: strong existing-component admission baseline

## Material Passport

ARS-Codex assistant prospective development experiment,2026-10-13. User has
authorized resuming research and requested final IEEE conference formatting.
The prior pause record remains historical; no novel-method claim is authorized.

Use all six saved V27 input plans and the exact same development service
prefix,16 waiting slots,208000ms observation,8000ms warmup,three deadlines and
metrics. No new trace member, input tuning or change of primary20ms deadline.

Compare corrected strict-priority/drop-tail from V27 with corrected
strict-priority/push-out admission. On full waiting buffer, an arriving packet
may evict the newest waiting packet in the lowest-priority class STRICTLY
below the arrival's class. Control1,sensor2,bulk3. Equal-priority arrivals are
dropped; in-transit packets cannot be evicted. Replacement preserves resident
count and accepted-only counter. Report every eviction as a loss of its victim,
not as successful delivery or source shaping. Queue service and bypass retain
V27 polling/tie semantics. All policy outcomes share identical release plans.

Primary pFabric paper, author-hosted
https://yuba.stanford.edu/~nickm/papers/pfabric.pdf, introduction pp435-436,
describes combined priority scheduling and low-priority buffered replacement.
This is only a class-based implementation of an established component idea:
NOT a full pFabric replication, which includes per-flow priorities and endpoint
rate control. Our explicitly strict equal-class drop policy differs from
unqualified equal-priority replacement. Do not call this baseline our novelty.

Hypothesis is descriptive and falsifiable: protecting admission may remove the
apparent40ms headroom left by plain priority; if so, that is evidence AGAINST
claiming a new scheduler is required on this grid. Primary20ms may remain
infeasible. Preserve bulk/sensor loss, tail and delivery costs, and do not use
success on this reused single prefix as independent or reserved validation.

Retain raw packet records with evicted_by, evictions, fixed source hashes,
summaries and exact prior-baseline pairing. Test no eviction of equal/higher
classes, no transit eviction, replacement accounting, unchanged non-full cases,
and replay determinism. Audit all raw rows and metrics before conclusions.
