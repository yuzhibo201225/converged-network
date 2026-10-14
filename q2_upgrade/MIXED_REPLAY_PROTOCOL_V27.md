# V27 development mixed-flow semantic and feasibility gate

## Material Passport

ARS-Codex assistant-authored prospective experiment,2026-10-13. Development
replay only, not new hardware data, independent sessions or novelty evidence.
Previous turn was progress: native source parity, finite-queue counterexample,
and development heavy-service input audit were completed and committed.

Use T-Mobile weak-signal uplink first as a computational development gate,
not because of a policy result. Other development channels and reserved inputs
remain future replication requirements. All service inputs are already opened
development data. Do not present this single prefix as independent trials.

Original208000ms service prefix; absolute times and every same-time1400B PDO
preserved. Control150B every20ms, sensor256B every200ms, bulk1400B, starting0,
ending before208000ms. Warmup8000ms, exactly10000 measured control packets.
Observation ends208000ms; unfinished/control admission refusals count as misses.
P99 includes delivered packets only. Deadlines10,20,40ms;20ms is primary.

Load targets0.2,0.6,0.9 use total byte arrivals divided by prefix total PDO byte
budget. This is a replay offered-work normalization, not wireless PHY capacity.
Across loads only bulk average rises. Within each load, bulk counts per300ms
cycle are identical across nominal PMR1 and3. All packets are placed uniformly
within the cycle's ON fraction, with integer-ms quantization. Last partial
cycle has its own proportional ON fraction. Preserve actual offered-load and
per-cycle counts; do not claim exact sub-ms PMR after timestamp quantization.

Generate plans with the V23-verified translation at timer0. Before queue policy
outcomes, compare EVERY planned field of EVERY mixed packet to the existing
native exact-method fixture using identical ordered time/size inputs. Packet
ties: control,sensor,bulk then local ID; release ties retain global source ID.
All policy/accounting variants share those identical planned releases and
source arrivals. If native parity fails, stop and retain the failure.

Queue variants: FIFO and nonpreemptive control-first priority; finite waiting
limit16 packets excludes in-transit packets. Accounting variants: original
attempt increment and accepted-only increment. No source shaping, new adaptive
method, transport feedback or fitted deadline. Never interpret counter repair
or standard priority as our innovation.

Ideal event polling, no OS jitter: PDOs strictly before a release batch drain
at their own event times. Same-time PDO completion is held in the output buffer
through that release batch, matching the original order of release processing
before write_packets_from_link_queue. Light bypass requires the maintained
counter to be0. Idle service opportunities expire, with no stored credit.
Complete each nonpreemptive packet using successive1400B PDO budgets; retain
same-time multiple opportunities. Priority affects only waiting selection.

Save each planned mixed input, each native differential output, all per-packet
queue outcomes, summaries, config and source/model hashes. Reconstruct counts,
P99, misses, deadlines, native parity and pairing from saved raw records. Retain
negative feasibility and throughput/loss tradeoffs. Native release parity does
not establish full queue/emulator equivalence; synthetic queue semantic tests
and subsequent independent native queue coupling remain distinct gates.
