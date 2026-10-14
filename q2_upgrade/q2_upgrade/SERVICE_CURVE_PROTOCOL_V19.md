# V19 existing-theory baseline under coarse service contracts

## Material Passport

ARS-Codex autonomous implementation support, 2026-10-12. Written before new
bound calculations/comparisons. Reanalysis of completed V18, not fresh heldout
trials. No novelty or external mathematical-validation claim.

## Inputs and information scope

Use the frozen V18 traffic/queue contract only; forbid importing actual service
realizations, packet arrivals/releases/completions or measured latency to make
decisions. One bin has width Delta=50T, service integral Delta, instantaneous
rate in [.7,1.3]. These are a priori synthetic constraints that hold in EVERY
bin, not parameters learned from future real observations. Uniform/fine/coarse
profiles must receive identical predictions at each load/scheduler. No real
client-goodput records are substituted for this exogenous service contract.

## Baselines and prospective checks

Implement established network-calculus aggregate backlog and horizontal delay
bounds with (i) optimistic mean-rate curve beta(t)=t, explicitly INVALID as a
universal guarantee for this uncertainty set; (ii) valid minimum-rate .7t;
(iii) bin-budget-aware lower service curve, derived from partial-bin rate bounds.
Use a phase-independent periodic/burst packet arrival envelope, not just an
affine bucket when its richer structure is available. Check all piecewise
breakpoints and inverse-service crossings, with an analytic infinite-tail
cutoff; no finite numerical time grid masquerading as a global supremum.

FIFO control qualification uses an upper bound for ALL packets' last-bit delay.
Priority uses a separate highest-class nonpreemptive blocking bound .11/.7T,
conditional on control admission. Both require a sufficient aggregate backlog
bound strictly below waiting capacity16. Qualification also requires a declared
live guard sufficient to finish measurement packets while background continues.
Do not interpret failure of these sufficient conditions as actual failure.
Do not conflate deterministic worst-case guarantees with measured P99.

Freeze algorithm/protocol hashes and input hashes before analysis. Reconstruct
predictions directly from allowed config, then compare against all240 previously
audited V18 outcomes. Report false qualifications, qualified successes, passing
abstentions and failing abstentions separately. Same three rules applied to
the same240 outcomes are NOT720 independent experimental trials.

Tests cover elementary partial-bin minimization, closed-form curve inversion,
supremum vs dense numerical diagnostic, arrival envelope coverage, unbounded
minimum-rate overload, profile-blind decisions, input/outcome separation and
failure-closed audit inputs. This small Python baseline is not a reproduction
of the DNC/Nancy software or of stochastic bandwidth-estimation algorithms.

## Claim gate

If valid existing-theory qualification already protects the observed region,
record that negative novelty evidence. Any improved candidate must compare with
this richer baseline, NOT only the mean heuristic/minimum-rate bound. Sharper
aggregation, optimization, sampling or service-curve methods in the literature
remain potential stronger comparators. No algorithm advantage, universal
optimality, practical radio certificate, JCR Q2 readiness or publication claim
follows merely from passing these model tests.
