"""Timescale-separated synthetic bottleneck simulator.

This module is deliberately independent of :mod:`converged_sim.model`.  It is
the publication-upgrade model, while the original simulator remains frozen for
reproducibility of the completed experiments.

The two exogenous waveforms are orthogonal by construction:

* bulk traffic has mean ``lambda_b``, peak-to-mean ratio ``pmr`` and cycle
  ``tau_b``.  Its ON and OFF durations are ``tau_b / pmr`` and
  ``tau_b * (1 - 1 / pmr)``; the OFF rate is exactly zero;
* service alternates between two rates, each for dwell ``tau_s``.  The initial
  state and within-dwell phase are randomized from the seed and shared by all
  paired traffic arms.

Warm-up and measurement windows must contain complete bulk and service cycles.
That restriction is intentional: it makes the emitted packet work and the
integrated service mean exact in each window, rather than relying on a
seed-specific correction that would confound a timescale comparison.

Packetization uses one seed-randomized cumulative-work lattice continuously
across warm-up and measurement.  The lattice is shared by all paired burst
arms, so a smooth arm is not locked to a privileged phase and packetization
residual is never reset at the measurement boundary.  After measurement ends,
background traffic continues for a declared guard interval.  A run fails
closed if any tagged measurement packet is still unresolved when that live-
traffic guard ends; only then may the simulator stop arrivals and drain its
untagged background packets.

Packets share a finite drop-tail work buffer.  Service is nonpreemptive under
FIFO, strict priority (control > sensor > bulk), or work-conserving deficit
round robin (DRR).  At equal timestamps, departures precede arrivals, and
arrivals are processed control, sensor, then bulk.
"""

from __future__ import annotations

from bisect import bisect_right
from collections import deque
from dataclasses import dataclass
import hashlib
import json
import math
import random
from typing import Any, Mapping

from .config import normalize_config


_EPS = 1e-10
_CLASSES = ("control", "sensor", "bulk")


def _canonical_digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _positive_finite(value: Any, name: str, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number greater than {minimum}")
    result = float(value)
    if not math.isfinite(result) or result <= minimum:
        raise ValueError(f"{name} must be a finite number greater than {minimum}")
    return result


def _whole_cycles(width: float, cycle: float, label: str) -> None:
    if width == 0:
        return
    turns = width / cycle
    if not math.isclose(turns, round(turns), rel_tol=0.0, abs_tol=1e-8):
        raise ValueError(f"{label} must contain an integer number of {cycle:g}-unit cycles")


@dataclass(slots=True)
class _Packet:
    kind: str
    packet_id: int
    arrival: float
    work: float
    row_index: int | None


class _FifoScheduler:
    def __init__(self) -> None:
        self.queue: deque[_Packet] = deque()

    def push(self, packet: _Packet) -> None:
        self.queue.append(packet)

    def pop_next(self) -> _Packet | None:
        return self.queue.popleft() if self.queue else None

    def __len__(self) -> int:
        return len(self.queue)


class _PriorityScheduler:
    def __init__(self) -> None:
        self.queues = {kind: deque() for kind in _CLASSES}
        self.count = 0

    def push(self, packet: _Packet) -> None:
        self.queues[packet.kind].append(packet)
        self.count += 1

    def pop_next(self) -> _Packet | None:
        for kind in _CLASSES:
            if self.queues[kind]:
                self.count -= 1
                return self.queues[kind].popleft()
        return None

    def __len__(self) -> int:
        return self.count


class _DrrScheduler:
    """Three-class DRR with persistent deficits and no artificial idle time."""

    def __init__(self, quanta: Mapping[str, float]) -> None:
        self.queues = {kind: deque() for kind in _CLASSES}
        self.quanta = dict(quanta)
        self.deficits = {kind: 0.0 for kind in _CLASSES}
        self.cursor = 0
        self.credit_added = False
        self.count = 0

    def push(self, packet: _Packet) -> None:
        self.queues[packet.kind].append(packet)
        self.count += 1

    def _advance(self) -> None:
        self.cursor = (self.cursor + 1) % len(_CLASSES)
        self.credit_added = False

    def pop_next(self) -> _Packet | None:
        if not self.count:
            return None
        # Virtual DRR rounds take no simulated time.  Every positive quantum
        # therefore eventually makes a queued head packet eligible, ensuring
        # the link never idles while work is queued.
        visits = 0
        while self.count:
            kind = _CLASSES[self.cursor]
            queue = self.queues[kind]
            if not queue:
                self.deficits[kind] = 0.0
                self._advance()
                continue
            if not self.credit_added:
                self.deficits[kind] += self.quanta[kind]
                self.credit_added = True
            if queue[0].work <= self.deficits[kind] + _EPS:
                packet = queue.popleft()
                self.count -= 1
                self.deficits[kind] = max(0.0, self.deficits[kind] - packet.work)
                if not queue:
                    self.deficits[kind] = 0.0
                    self._advance()
                return packet
            self._advance()
            visits += 1
            if visits > 10_000_000:
                raise RuntimeError("DRR quantum is too small for numerically safe scheduling")
        return None

    def __len__(self) -> int:
        return self.count


@dataclass(slots=True)
class _ServiceTrace:
    starts: list[float]
    ends: list[float]
    rates: list[float]
    observation_duration: float
    drain_horizon: float
    initial_high: bool
    phase_fraction: float
    low_rate: float
    high_rate: float
    digest: str
    simulation_digest: str
    pattern_digest: str

    def integrate(self, start: float, end: float) -> float:
        if end <= start:
            return 0.0
        left = max(0.0, start)
        right = min(end, self.drain_horizon)
        if right <= left:
            return 0.0
        index = bisect_right(self.ends, left + _EPS)
        terms: list[float] = []
        while index < len(self.rates) and self.starts[index] < right - _EPS:
            overlap = max(
                0.0,
                min(right, self.ends[index]) - max(left, self.starts[index]),
            )
            if overlap:
                terms.append(overlap * self.rates[index])
            index += 1
        return math.fsum(terms)

    def finish_time(self, start: float, work: float) -> float:
        remaining = work
        current = start
        index = bisect_right(self.ends, current + _EPS)
        while index < len(self.rates) and current < self.drain_horizon - _EPS:
            left = max(current, self.starts[index])
            right = self.ends[index]
            if right <= left + _EPS:
                index += 1
                continue
            capacity = (right - left) * self.rates[index]
            if remaining <= capacity + _EPS:
                return min(left + remaining / self.rates[index], self.drain_horizon)
            remaining -= capacity
            current = right
            index += 1
        return math.inf


def _build_service_trace(
    *, duration: float, drain_horizon: float, tau_s: float,
    low_rate: float, high_rate: float, seed: int,
) -> _ServiceTrace:
    """Build a paired alternating trace with exact unit mean over ``duration``."""

    # The phase/state streams are separate from traffic generation and do not
    # depend on PMR or tau_b.
    phase_fraction = random.Random(f"timescale-service-phase-v2:{seed}").random()
    initial_high = bool(random.Random(f"timescale-service-state-v2:{seed}").getrandbits(1))

    # Center the two supplied levels once, independently of tau_s and seed.
    center_scale = 2.0 / (low_rate + high_rate)
    low = low_rate * center_scale
    high = high_rate * center_scale

    starts: list[float] = []
    ends: list[float] = []
    raw_rates: list[float] = []
    at = 0.0
    state_high = initial_high
    first_width = (1.0 - phase_fraction) * tau_s
    width = first_width
    while at < drain_horizon - _EPS:
        end = min(drain_horizon, at + width)
        starts.append(at)
        ends.append(end)
        raw_rates.append(high if state_high else low)
        at = end
        state_high = not state_high
        width = tau_s

    raw_work = math.fsum(
        rate * max(0.0, min(duration, end) - start)
        for start, end, rate in zip(starts, ends, raw_rates)
        if start < duration
    )
    if not math.isclose(raw_work, duration, rel_tol=0.0, abs_tol=1e-8):
        raise RuntimeError("complete service cycles did not integrate to unit mean")
    # Remove only floating-point accumulation error.  The mathematical scale is
    # one because each observation window contains complete two-dwell cycles.
    correction = duration / raw_work
    rates = [rate * correction for rate in raw_rates]
    effective_low = low * correction
    effective_high = high * correction

    pattern_payload = {
        "tau_s": tau_s,
        "initial_high": initial_high,
        "phase_fraction": phase_fraction,
        "observation_duration": duration,
    }
    observation_trace_payload = {
        **pattern_payload,
        "starts": [start for start in starts if start < duration],
        "ends": [min(end, duration) for start, end in zip(starts, ends) if start < duration],
        "rates": [rate for start, rate in zip(starts, rates) if start < duration],
    }
    simulation_trace_payload = {
        **pattern_payload,
        "drain_horizon": drain_horizon,
        "starts": starts,
        "ends": ends,
        "rates": rates,
    }
    return _ServiceTrace(
        starts=starts,
        ends=ends,
        rates=rates,
        observation_duration=duration,
        drain_horizon=drain_horizon,
        initial_high=initial_high,
        phase_fraction=phase_fraction,
        low_rate=effective_low,
        high_rate=effective_high,
        digest=_canonical_digest(observation_trace_payload),
        simulation_digest=_canonical_digest(simulation_trace_payload),
        pattern_digest=_canonical_digest(pattern_payload),
    )


def _on_intervals(start: float, end: float, tau_b: float, pmr: float, phase: float) -> list[tuple[float, float]]:
    on_width = tau_b / pmr
    first = math.floor((start + phase) / tau_b) - 1
    last = math.ceil((end + phase) / tau_b) + 1
    intervals: list[tuple[float, float]] = []
    for turn in range(first, last + 1):
        on_start = turn * tau_b - phase
        on_end = on_start + on_width
        left = max(start, on_start)
        right = min(end, on_end)
        if right > left + _EPS:
            intervals.append((left, right))
    intervals.sort()
    return intervals


def _bulk_arrivals(
    *, measurement_start: float, measurement_end: float, traffic_end: float,
    mean_rate: float, packet_work: float, pmr: float, tau_b: float, seed: int,
) -> tuple[list[float], float, float, int, int]:
    """Packetize one continuous fluid envelope using a paired random lattice.

    A packet is emitted whenever cumulative fluid work crosses
    ``(u + k) * packet_work``, with one ``u`` shared by every PMR/timescale arm
    for a seed.  Observation-window boundaries contain complete bulk cycles,
    hence cumulative work at those boundaries is identical across paired arms.
    """

    phase_fraction = random.Random(f"timescale-bulk-phase-v3:{seed}").random()
    phase = phase_fraction * tau_b
    # random() is in [0, 1), so this construction is in (0, 1].  PMR=1 now
    # receives the same seed-randomized packet-lattice treatment as burst arms.
    lattice_fraction = 1.0 - random.Random(
        f"timescale-bulk-lattice-v3:{seed}"
    ).random()
    peak_rate = pmr * mean_rate
    if math.isclose(pmr, 1.0, rel_tol=0.0, abs_tol=1e-14):
        intervals = [(0.0, traffic_end)]
    else:
        intervals = _on_intervals(0.0, traffic_end, tau_b, pmr, phase)

    arrivals: list[float] = []
    emitted_before = 0.0
    threshold = lattice_fraction * packet_work
    for left, right in intervals:
        interval_work = (right - left) * peak_rate
        emitted_after = emitted_before + interval_work
        while threshold <= emitted_after:
            timestamp = left + (threshold - emitted_before) / peak_rate
            if timestamp >= traffic_end:
                break
            arrivals.append(max(left, timestamp))
            threshold += packet_work
        emitted_before = emitted_after

    observed = sum(arrival < measurement_end for arrival in arrivals)
    measured = sum(
        measurement_start <= arrival < measurement_end for arrival in arrivals
    )
    return arrivals, phase_fraction, lattice_fraction, observed, measured


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[min(lower + 1, len(ordered) - 1)] * weight


def _class_summary(rows: list[dict[str, Any]], kind: str, measurement_duration: float) -> dict[str, Any]:
    cohort = [row for row in rows if row["class"] == kind]
    delivered = [row for row in cohort if row["status"] == "delivered"]
    dropped = sum(row["status"] == "dropped" for row in cohort)
    unfinished = sum(row["status"] == "unfinished" for row in cohort)
    latencies = [float(row["latency"]) for row in delivered]
    generated_work = math.fsum(float(row["work"]) for row in cohort)
    delivered_work = math.fsum(float(row["work"]) for row in delivered)
    summary: dict[str, Any] = {
        "generated": len(cohort),
        "delivered": len(delivered),
        "dropped": dropped,
        "unfinished": unfinished,
        "delivery_ratio": len(delivered) / len(cohort) if cohort else None,
        "generated_work": generated_work,
        "delivered_work": delivered_work,
        "goodput_work_per_time": delivered_work / measurement_duration,
        "p50_latency": _percentile(latencies, 0.50),
        "p95_latency": _percentile(latencies, 0.95),
        "p99_latency": _percentile(latencies, 0.99),
    }
    if kind == "control":
        misses = sum(bool(row["deadline_miss"]) for row in cohort)
        summary["deadline_miss_count"] = misses
        summary["deadline_miss_ratio"] = misses / len(cohort) if cohort else None
    else:
        summary["deadline_miss_count"] = None
        summary["deadline_miss_ratio"] = None
    return summary


def _validated_quanta(
    policy: str, quanta: Mapping[str, float] | None,
) -> dict[str, float] | None:
    if policy != "drr":
        return None
    if not isinstance(quanta, Mapping) or set(quanta) != set(_CLASSES):
        raise ValueError("drr_quanta must provide exactly control, sensor, and bulk")
    return {kind: _positive_finite(quanta[kind], f"drr_quanta[{kind}]") for kind in _CLASSES}


def run_one_timescale(
    config: Mapping[str, Any],
    rho: float,
    pmr: float,
    tau_b: float,
    tau_s: float,
    seed: int,
    *,
    policy: str = "fifo",
    drr_quanta: Mapping[str, float] | None = None,
    collect_instrumentation: bool = False,
    background_guard_periods: float | None = None,
) -> dict[str, Any]:
    """Run one paired, timescale-separated bottleneck experiment.

    ``rho`` is target aggregate offered work divided by the exact unit service
    mean.  Packet quantization can make achieved load slightly lower, and both
    target and achieved values are returned.  For fixed ``rho`` and ``seed``,
    all ``pmr``/``tau_b`` arms have identical class work and packet counts.

    ``background_guard_periods`` controls how long untagged stationary traffic
    continues after the measurement boundary.  The default is deliberately
    conservative.  The run fails rather than silently cooling the queue if any
    tagged measurement packet remains unresolved at the end of that guard.

    Token-bucket shaping is intentionally outside this core function.  A shaper
    adds a second source queue and requires a separately declared admission and
    loss accounting contract; keeping it separate prevents scheduler results
    from silently changing denominator semantics.
    """

    cfg = normalize_config(config)
    rho = _positive_finite(rho, "rho")
    pmr = _positive_finite(pmr, "pmr", minimum=1.0 - _EPS)
    if pmr < 1.0:
        raise ValueError("pmr must be at least 1")
    tau_b = _positive_finite(tau_b, "tau_b")
    tau_s = _positive_finite(tau_s, "tau_s")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")
    if policy not in ("fifo", "strict_priority", "drr"):
        raise ValueError("policy must be fifo, strict_priority, or drr")
    if not isinstance(collect_instrumentation, bool):
        raise ValueError("collect_instrumentation must be boolean")
    if background_guard_periods is not None:
        background_guard_periods = _positive_finite(
            background_guard_periods, "background_guard_periods"
        )
    quanta = _validated_quanta(policy, drr_quanta)

    control_period = float(cfg["control_period"])
    sensor_period = float(cfg["sensor_period"])
    control_work = float(cfg["control_packet_work"])
    sensor_work = float(cfg["sensor_packet_work"])
    bulk_work = float(cfg["bulk_packet_work"])
    buffer_work = float(cfg["buffer_work"])
    warmup_count = int(cfg["warmup_control_packets"])
    measured_count = int(cfg["measured_control_packets"])
    measurement_start = warmup_count * control_period
    measurement_duration = measured_count * control_period
    duration = measurement_start + measurement_duration
    deadline = float(cfg["deadline_periods"]) * control_period

    for width, label in (
        (measurement_start, "warm-up window"),
        (measurement_duration, "measurement window"),
    ):
        _whole_cycles(width, tau_b, f"{label} for the bulk waveform")
        _whole_cycles(width, 2.0 * tau_s, f"{label} for the service waveform")

    low_nominal = float(cfg["trace_low_rate"])
    high_nominal = float(cfg["trace_high_rate"])
    centered_low = 2.0 * low_nominal / (low_nominal + high_nominal)
    min_rate = min(centered_low, 2.0 * high_nominal / (low_nominal + high_nominal))
    if background_guard_periods is None:
        # This interval is not treated as proof of a deterministic delay bound:
        # the unresolved-tag check below is the fail-closed contract.  It is a
        # large, policy-independent default chosen to make failure exceptional.
        background_guard = max(
            64.0 * control_period,
            8.0 * tau_b,
            16.0 * tau_s,
            16.0 * buffer_work / min_rate,
            8.0 * deadline,
        )
    else:
        background_guard = background_guard_periods * control_period
    traffic_end = duration + background_guard
    drain_horizon = traffic_end + buffer_work / min_rate + 2.0 * tau_s
    trace = _build_service_trace(
        duration=duration,
        drain_horizon=drain_horizon,
        tau_s=tau_s,
        low_rate=low_nominal,
        high_rate=high_nominal,
        seed=seed,
    )
    service_work = trace.integrate(0.0, duration)
    measured_service_work = trace.integrate(measurement_start, duration)
    if not math.isclose(service_work, duration, rel_tol=0.0, abs_tol=1e-8):
        raise RuntimeError("service trace does not have exact unit observation mean")
    if not math.isclose(measured_service_work, measurement_duration, rel_tol=0.0, abs_tol=1e-8):
        raise RuntimeError("service trace does not have exact unit measurement mean")

    control_count = warmup_count + measured_count
    simulated_control_count = math.ceil(traffic_end / control_period - _EPS)
    control_times = [
        index * control_period for index in range(simulated_control_count)
    ]
    sensor_count = math.ceil(duration / sensor_period - _EPS)
    simulated_sensor_count = math.ceil(traffic_end / sensor_period - _EPS)
    sensor_times = [
        index * sensor_period for index in range(simulated_sensor_count)
    ]
    fixed_offered_work = control_count * control_work + sensor_count * sensor_work
    bulk_mean_rate = rho - fixed_offered_work / duration
    if bulk_mean_rate <= 0.0:
        raise ValueError("rho leaves no positive mean rate for bulk traffic")
    (
        bulk_times,
        bulk_phase_fraction,
        bulk_lattice_fraction,
        bulk_observation_count,
        bulk_measured_count,
    ) = _bulk_arrivals(
        measurement_start=measurement_start,
        measurement_end=duration,
        traffic_end=traffic_end,
        mean_rate=bulk_mean_rate,
        packet_work=bulk_work,
        pmr=pmr,
        tau_b=tau_b,
        seed=seed,
    )

    if policy == "fifo":
        scheduler: _FifoScheduler | _PriorityScheduler | _DrrScheduler = _FifoScheduler()
    elif policy == "strict_priority":
        scheduler = _PriorityScheduler()
    else:
        assert quanta is not None
        scheduler = _DrrScheduler(quanta)

    rows: list[dict[str, Any]] = []
    instrumentation_rows: list[dict[str, Any]] = []
    row_lookup: dict[tuple[str, int], int] = {}
    arrival_lists = {"control": control_times, "sensor": sensor_times, "bulk": bulk_times}
    works = {"control": control_work, "sensor": sensor_work, "bulk": bulk_work}
    for kind in _CLASSES:
        for packet_id, arrival in enumerate(arrival_lists[kind]):
            if arrival < measurement_start or arrival >= duration:
                continue
            row_index = len(rows)
            row_lookup[(kind, packet_id)] = row_index
            rows.append({
                "class": kind,
                "packet_id": packet_id,
                "arrival": arrival,
                "work": works[kind],
                "completion": None,
                "status": "unfinished",
                "latency": None,
                "deadline_miss": True if kind == "control" else None,
            })
            if collect_instrumentation:
                instrumentation_rows.append({
                    "class": kind,
                    "packet_id": packet_id,
                    "arrival": arrival,
                    "queue_work_at_arrival": None,
                    "queue_packets_at_arrival": None,
                    "service_start": None,
                    "waiting_time": None,
                    "service_time": None,
                })

    indexes = {kind: 0 for kind in _CLASSES}
    in_service: _Packet | None = None
    service_started_at: float | None = None
    departure = math.inf
    occupied_work = 0.0
    max_occupied_work = 0.0
    drop_counts = {kind: 0 for kind in _CLASSES}
    admitted_work = {kind: 0.0 for kind in _CLASSES}
    served_work = {kind: 0.0 for kind in _CLASSES}
    work_conserving_violations = 0
    service_sequence: list[dict[str, Any]] = []

    def start_next(at: float) -> None:
        nonlocal in_service, service_started_at, departure, work_conserving_violations
        packet = scheduler.pop_next()
        if packet is None:
            if len(scheduler):
                work_conserving_violations += 1
            in_service = None
            service_started_at = None
            departure = math.inf
            return
        in_service = packet
        service_started_at = at
        departure = trace.finish_time(at, packet.work)
        if not math.isfinite(departure):
            raise RuntimeError("an admitted packet did not fit in the proven drain horizon")
        if packet.row_index is not None and collect_instrumentation:
            mechanism = instrumentation_rows[packet.row_index]
            mechanism["service_start"] = at
            mechanism["waiting_time"] = max(0.0, at - packet.arrival)
        if collect_instrumentation:
            service_sequence.append({
                "class": packet.kind,
                "packet_id": packet.packet_id,
                "start": at,
                "completion": departure,
            })

    def queue_work_at(at: float) -> float:
        if in_service is None:
            return occupied_work
        assert service_started_at is not None
        served = trace.integrate(service_started_at, at)
        residual = max(0.0, in_service.work - served)
        return max(0.0, occupied_work - in_service.work + residual)

    def admit(kind: str, packet_id: int, at: float) -> None:
        nonlocal occupied_work, max_occupied_work
        size = works[kind]
        row_index = row_lookup.get((kind, packet_id))
        system_work_before = queue_work_at(at)
        if row_index is not None and collect_instrumentation:
            mechanism = instrumentation_rows[row_index]
            mechanism["queue_work_at_arrival"] = system_work_before
            mechanism["queue_packets_at_arrival"] = len(scheduler) + (in_service is not None)
        # buffer_work is a cap on waiting work plus the residual work of the
        # in-service packet, not a sum of original packet sizes held until
        # completion.  This definition matches the mechanism instrumentation.
        if system_work_before + size > buffer_work:
            drop_counts[kind] += 1
            if row_index is not None:
                rows[row_index]["status"] = "dropped"
            return
        packet = _Packet(kind, packet_id, at, size, row_index)
        occupied_work += size
        admitted_work[kind] += size
        max_occupied_work = max(max_occupied_work, system_work_before + size)
        scheduler.push(packet)
        if in_service is None:
            start_next(at)

    def complete(at: float) -> None:
        nonlocal occupied_work
        assert in_service is not None
        packet = in_service
        occupied_work = max(0.0, occupied_work - packet.work)
        served_work[packet.kind] += packet.work
        if packet.row_index is not None:
            row = rows[packet.row_index]
            latency = max(0.0, at - packet.arrival)
            row["completion"] = at
            row["status"] = "delivered"
            row["latency"] = latency
            if packet.kind == "control":
                row["deadline_miss"] = latency >= deadline
            if collect_instrumentation:
                assert service_started_at is not None
                instrumentation_rows[packet.row_index]["service_time"] = at - service_started_at
        start_next(at)

    while any(indexes[kind] < len(arrival_lists[kind]) for kind in _CLASSES):
        next_times = {
            kind: (
                arrival_lists[kind][indexes[kind]]
                if indexes[kind] < len(arrival_lists[kind]) else math.inf
            )
            for kind in _CLASSES
        }
        arrival_time = min(next_times.values())
        if arrival_time >= traffic_end:
            break

        while departure <= arrival_time:
            completion_time = departure
            complete(completion_time)

        # The loop order is the declared equal-time arrival order.
        for kind in _CLASSES:
            while (
                indexes[kind] < len(arrival_lists[kind])
                and arrival_lists[kind][indexes[kind]] <= arrival_time
            ):
                packet_id = indexes[kind]
                admit(kind, packet_id, arrival_time)
                indexes[kind] += 1

    # Arrival arrays are half-open at traffic_end, so finish any service event
    # in the final inter-arrival gap before applying the live-traffic guard
    # contract.
    while departure <= traffic_end:
        completion_time = departure
        complete(completion_time)

    unresolved_at_guard = sum(row["status"] == "unfinished" for row in rows)
    if unresolved_at_guard:
        raise RuntimeError(
            f"background guard ended with {unresolved_at_guard} tagged packets "
            "unresolved; increase background_guard_periods"
        )

    while departure <= drain_horizon:
        completion_time = departure
        complete(completion_time)

    if in_service is not None or len(scheduler):
        raise RuntimeError("admitted packets did not drain within the safety horizon")
    if any(row["status"] == "unfinished" for row in rows):
        raise RuntimeError("a measured packet remained unfinished after draining")

    class_summaries = {
        kind: _class_summary(rows, kind, measurement_duration) for kind in _CLASSES
    }
    bulk_total_count = bulk_observation_count
    offered = {
        "control": control_count * control_work,
        "sensor": sensor_count * sensor_work,
        "bulk": bulk_total_count * bulk_work,
    }
    measured_offered = {
        kind: math.fsum(float(row["work"]) for row in rows if row["class"] == kind)
        for kind in _CLASSES
    }
    total_offered = math.fsum(offered.values())
    total_measured_offered = math.fsum(measured_offered.values())
    mean = service_work / duration
    variance = math.fsum(
        (rate - mean) ** 2 * max(0.0, min(duration, end) - start)
        for start, end, rate in zip(trace.starts, trace.ends, trace.rates)
        if start < duration
    ) / duration

    result: dict[str, Any] = {
        "packets": rows,
        "control_packets": [row for row in rows if row["class"] == "control"],
        "class_summaries": class_summaries,
        "target_rho": rho,
        "offered_load_actual": total_offered / service_work,
        "offered_load_measured_actual": total_measured_offered / measured_service_work,
        "pmr": pmr,
        "tau_b": tau_b,
        "tau_s": tau_s,
        "bulk_on_duration": tau_b / pmr,
        "bulk_off_duration": tau_b * (1.0 - 1.0 / pmr),
        "bulk_mean_rate_requested": bulk_mean_rate,
        "bulk_peak_rate_requested": pmr * bulk_mean_rate,
        "bulk_phase_fraction": bulk_phase_fraction,
        "bulk_packet_lattice_fraction": bulk_lattice_fraction,
        "bulk_arrival_digest": _canonical_digest([
            arrival for arrival in bulk_times if arrival < duration
        ]),
        "bulk_simulated_arrival_digest": _canonical_digest(bulk_times),
        "bulk_packet_count": bulk_total_count,
        "bulk_packet_count_measured": bulk_measured_count,
        "bulk_packet_count_simulated": len(bulk_times),
        "offered_control_work": offered["control"],
        "offered_sensor_work": offered["sensor"],
        "offered_bulk_work": offered["bulk"],
        "offered_total_work": total_offered,
        "offered_control_work_measured": measured_offered["control"],
        "offered_sensor_work_measured": measured_offered["sensor"],
        "offered_bulk_work_measured": measured_offered["bulk"],
        "offered_total_work_measured": total_measured_offered,
        "service_trace_digest": trace.digest,
        "service_simulation_trace_digest": trace.simulation_digest,
        "service_pattern_digest": trace.pattern_digest,
        # Compatibility aliases ease use by the existing audit code without
        # changing the frozen legacy module.
        "trace_digest": trace.digest,
        "trace_pattern_digest": trace.pattern_digest,
        "service_initial_high": trace.initial_high,
        "service_phase_fraction": trace.phase_fraction,
        "service_low_rate_effective": trace.low_rate,
        "service_high_rate_effective": trace.high_rate,
        "service_mean_rate": mean,
        "service_mean_rate_measured": measured_service_work / measurement_duration,
        "service_cv": math.sqrt(max(0.0, variance)) / mean,
        "policy": policy,
        "drr_quanta": quanta,
        "seed": seed,
        "observation_duration": duration,
        "measurement_start": measurement_start,
        "measurement_duration": measurement_duration,
        "background_guard_duration": background_guard,
        "traffic_end": traffic_end,
        "drain_horizon": drain_horizon,
        "max_occupied_work": max_occupied_work,
        "dropped_control_all": drop_counts["control"],
        "dropped_sensor_all": drop_counts["sensor"],
        "dropped_bulk_all": drop_counts["bulk"],
        "admitted_work_all": admitted_work,
        "served_work_all": served_work,
        "work_conserving_violations": work_conserving_violations,
        "config_digest": _canonical_digest({
            "base": cfg,
            "rho": rho,
            "pmr": pmr,
            "tau_b": tau_b,
            "tau_s": tau_s,
            "policy": policy,
            "drr_quanta": quanta,
            "background_guard_periods": (
                None if background_guard_periods is None
                else background_guard_periods
            ),
        }),
    }
    if collect_instrumentation:
        result["instrumentation_rows"] = instrumentation_rows
        result["service_sequence"] = service_sequence
    return result


__all__ = ["run_one_timescale"]
