# V18 coarse-observation ambiguity diagnostic

## Material Passport

ARS-Codex experiment execution under the user's autonomous implementation
request, 2026-10-12. Assistant-authored protocol, written before outcomes.
Status: exploratory mechanism diagnostic, not an innovation certificate.

## Question and predeclared experiment

Can identical one-second integrated exogenous service observations yield
different control SLO classifications in the declared integrated-service model?
This is a synthetic information-loss test, not a new wireless measurement.

Control period T=20ms, nominal capacity=6Mbps; use the existing generated-arrival
contract: control150B every T, sensor600B every2T, bulk1500B, PMR3, cycle8T.
No source shaping in this diagnostic. Load grid .20,.40,.60,.70,.80,.85,.90,.95;
five traffic/service seeds1--5, traffic phase seed20261020. Warm400T,
measure10000T, live background guard400T. Total10800T contains whole50T bins
and whole8T bulk cycles. All profiles within each seed/load use identical
packet IDs, arrival times, sizes and traffic mix. Across load points only bulk
mean increases. No trace-wise retrospective capacity normalization.

Three prescribed profiles, each with exactly50 work units per50T bin:
constant rate1; fine coinflip(.7/1.3) with .5T halves in each1T pair;
coarse coinflip(.7/1.3) with25T halves in each50T bin. Orientations use separate
deterministic random streams, not outcome selection. Both variable profiles
have identical time-weighted marginal rates; constant only matches bin totals.
The observations here are service integrals, NOT UCC's logged client goodput.

FIFO and nonpreemptive control>sensor>bulk strict priority; integrated service
continues through rate changes (unlike frozen ns3 frame-start-rate semantics).
Finite waiting-work capacity16, excluding in-service packet. Departures precede
arrivals at ties; arrivals control,sensor,bulk. All measurement packets retained
in raw output, including drops/unresolved. Control P99 from completed packets
only, miss includes delay>=T, drops and unresolved. Require P99<1T, miss<.01,
and full measured bulk delivery. Final arrivals end at10800T; constant-rate1
tail to11000T permits resolution. Separately report any measurement completion
after the live guard; this cannot be silently labeled live-traffic validation.

240 runs, 120 paired FIFO/priority settings, five seeds (NOT radio sessions).
No reliability confidence intervals or unseen-data certification planned.
Summary reports sample medians and per-seed pass counts. The maximum tested
load is only the highest point in the contiguous tested passing prefix; coarse
gaps mean this is NOT a finely resolved capacity boundary.

## Audit and disposition gates

Freeze script hashes and config before first simulation; retain compressed
all-flow measurement packet records. Audit identical arrival digests and
50T service integrals, raw row counts, record hashes, summary reconstruction;
tests cover rate-change integration, ties, priority nonpreemption and finite
queue drops. Rerun into a new directory and compare logical uncompressed raw
records and summaries; gzip headers are not scientific differences.

Any observed ambiguity demonstrates insufficiency of these observations in
this model; it does NOT establish original sampling theory, a novel admission
algorithm, deployable radio guarantees, or JCR Q2 readiness. Priority is an
existing intervention, not our contribution. Compare any later uncertainty
method with established service-curve/network-calculus estimators first.
