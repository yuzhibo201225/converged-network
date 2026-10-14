"""Exact-event synthetic bottleneck model with paired ON/OFF bulk arrivals.

Work units are normalized packet transmission work (not physical bytes).  A
service rate is work per time unit.  PMR controls an ON/OFF *fluid emission
envelope*: the ON interval lasts one control period and emits at ``pmr`` times
the target bulk mean rate; its OFF interval lasts ``(pmr - 1)`` periods.  Fixed
size packets are emitted whenever the envelope accumulates another packet's
worth of work.  Whole envelope cycles over the horizon guarantee that paired
PMR arms generate exactly the same number of bulk packets.

The finite FIFO capacity counts full packet sizes of both waiting and currently
transmitting packets.  A packet's service is nonpreemptive; changes in link rate
can occur during service.  At an equal timestamp, departures happen before
arrivals, and simultaneous arrivals are control, sensor, then bulk.
"""

from __future__ import annotations

from collections import deque
import hashlib
import json
import math
import random
from typing import Any, Mapping

from .config import normalize_config


_EPS = 1e-10


def _canonical_digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _trace(
    cfg: Mapping[str, int | float | bool], duration: float, drain_horizon: float, seed: int
) -> tuple[list[float], float, str, str, float, float]:
    block = float(cfg["trace_block_period"])
    low = float(cfg["trace_low_rate"])
    high = float(cfg["trace_high_rate"])
    generation_blocks = (
        int(round(duration / block))
        if cfg["trace_balance_windows"] else math.ceil(duration / block)
    )
    if cfg["trace_balance_windows"]:
        warmup_duration = int(cfg["warmup_control_packets"]) * float(cfg["control_period"])
        warmup_blocks = int(round(warmup_duration / block))
        measurement_blocks = generation_blocks - warmup_blocks
        rng = random.Random(f"converged-trace-balanced-v1:{seed}")

        def shuffled_balanced_states(count: int) -> list[int]:
            states = [0] * (count // 2) + [1] * (count // 2)
            rng.shuffle(states)
            return states

        generation_states = (
            shuffled_balanced_states(warmup_blocks)
            + shuffled_balanced_states(measurement_blocks)
        )
    else:
        rng = random.Random(f"converged-trace-v1:{seed}")
        generation_states = [rng.getrandbits(1) for _ in range(generation_blocks)]
    raw_generation_rates = [high if state else low for state in generation_states]
    raw_work_terms = [
        rate * max(0.0, min(duration, (i + 1) * block) - i * block)
        for i, rate in enumerate(raw_generation_rates)
    ]
    raw_work = math.fsum(raw_work_terms) if cfg["trace_balance_windows"] else sum(raw_work_terms)
    if cfg["trace_balance_windows"]:
        # Equal high/low counts in each complete window plus rate levels centered
        # on one give unit means without a seed-specific scale factor.
        scale = 1.0
        if not math.isclose(raw_work, duration, rel_tol=0, abs_tol=1e-10):
            raise RuntimeError("balanced service trace does not have unit mean")
    elif cfg["trace_normalize_mean"]:
        # Normalize the realized trace, not the nominal high/low average.  Every
        # service regime therefore has identical integrated offered-interval
        # capacity for this seed, including a truncated final block.
        scale = duration / raw_work
        drain_horizon = duration + float(cfg["buffer_work"]) / (min(low, high) * scale) + block
    else:
        scale = 1.0
    count = math.ceil(drain_horizon / block)
    states = generation_states + [rng.getrandbits(1) for _ in range(count - generation_blocks)]
    rates = [(high if state else low) * scale for state in states]
    served_work = sum(
        rate * max(0.0, min(duration, (i + 1) * block) - i * block)
        for i, rate in enumerate(rates)
    )
    integrated_mean = served_work / duration
    unit_mean_mode = cfg["trace_normalize_mean"] or cfg["trace_balance_windows"]
    if unit_mean_mode and not math.isclose(integrated_mean, 1.0, rel_tol=0, abs_tol=1e-12):
        raise RuntimeError("normalized service trace does not have unit mean")
    # Use an exact target denominator in normalized mode so fixed-size packet
    # quantization cannot differ between regimes from floating-point drift.
    mean_rate = 1.0 if unit_mean_mode else integrated_mean
    variance = sum(
        (rate - integrated_mean) ** 2
        * max(0.0, min(duration, (i + 1) * block) - i * block)
        for i, rate in enumerate(rates)
    ) / duration
    cv = math.sqrt(max(0.0, variance)) / integrated_mean
    digest = _canonical_digest({
        "block_period": block, "observation_duration": duration,
        "drain_horizon": drain_horizon, "rates": rates,
    })
    pattern_digest = _canonical_digest({
        "block_period": block, "observation_duration": duration,
        "generation_states": generation_states,
    })
    return rates, mean_rate, digest, pattern_digest, cv, drain_horizon


def _trace_work(rates: list[float], block: float, start: float, end: float) -> float:
    """Integrate available service over a bounded interval."""
    first = max(0, math.floor(start / block))
    stop = min(len(rates), math.ceil(end / block))
    return sum(
        rates[index] * max(
            0.0, min(end, (index + 1) * block) - max(start, index * block)
        )
        for index in range(first, stop)
    )


def _bulk_on_at(at: float, control_period: float, pmr: float, phase: float) -> bool:
    """Return the half-open ON/OFF-envelope state at one timestamp."""
    position = (at + phase) % (pmr * control_period)
    return position < control_period


def _preceding_overlap_fractions(
    start: float, end: float, control_period: float, pmr: float, phase: float,
    rates: list[float], block_period: float, mean_rate: float,
) -> tuple[float, float, float]:
    """Integrate bulk-ON, low-service, and joint exposure over an interval."""
    if end <= start:
        raise ValueError("mechanism interval must have positive duration")
    cuts = {start, end}
    first_block = math.floor(start / block_period) + 1
    last_block = math.ceil(end / block_period)
    for index in range(first_block, last_block + 1):
        boundary = index * block_period
        if start < boundary < end:
            cuts.add(boundary)
    cycle = pmr * control_period
    first_cycle = math.floor((start + phase) / cycle) - 1
    last_cycle = math.ceil((end + phase) / cycle) + 1
    for index in range(first_cycle, last_cycle + 1):
        on_start = index * cycle - phase
        on_end = on_start + control_period
        if start < on_start < end:
            cuts.add(on_start)
        if start < on_end < end:
            cuts.add(on_end)
    ordered = sorted(cuts)
    on_duration = low_duration = overlap_duration = 0.0
    for left, right in zip(ordered, ordered[1:]):
        midpoint = (left + right) / 2
        on = _bulk_on_at(midpoint, control_period, pmr, phase)
        rate = rates[min(int(midpoint / block_period), len(rates) - 1)]
        low_service = rate < mean_rate - _EPS
        width = right - left
        on_duration += width if on else 0.0
        low_duration += width if low_service else 0.0
        overlap_duration += width if on and low_service else 0.0
    width = end - start
    return on_duration / width, low_duration / width, overlap_duration / width


def _bulk_arrivals(
    duration: float,
    control_period: float,
    bulk_mean_rate: float,
    packet_work: float,
    pmr: float,
    seed: int,
) -> tuple[list[float], float]:
    """Invert cumulative ON-envelope work at fixed-size packet midpoints."""

    cycle = pmr * control_period
    turns = duration / cycle
    if not math.isclose(turns, round(turns), rel_tol=0, abs_tol=1e-8):
        raise ValueError(
            "observation duration must contain an integer number of ON/OFF cycles "
            "for every requested PMR; change warmup/measured packet counts"
        )
    if bulk_mean_rate <= 0:
        raise ValueError("requested rho leaves no positive mean rate for bulk traffic")

    phase_fraction = random.Random(f"converged-bulk-phase-v1:{seed}").random()
    phase = phase_fraction * cycle
    on_rate = pmr * bulk_mean_rate
    target_count = math.floor(bulk_mean_rate * duration / packet_work + _EPS)
    arrivals: list[float] = []
    emitted_work = 0.0
    cycle_start = -phase
    next_packet = 0
    while cycle_start < duration - _EPS and next_packet < target_count:
        begin = max(0.0, cycle_start)
        end = min(duration, cycle_start + control_period)
        if end > begin:
            interval_work = (end - begin) * on_rate
            interval_end_work = emitted_work + interval_work
            while next_packet < target_count:
                threshold = (next_packet + 0.5) * packet_work
                if threshold > interval_end_work + _EPS:
                    break
                timestamp = begin + (threshold - emitted_work) / on_rate
                # A tolerance-limited clamp handles floating-point boundary ties.
                arrivals.append(min(max(timestamp, begin), end))
                next_packet += 1
            emitted_work = interval_end_work
        cycle_start += cycle

    if len(arrivals) != target_count:
        raise RuntimeError("bulk envelope generated a non-matching packet count")
    return arrivals, phase


def _finish_time(
    start: float, work: float, rates: list[float], block_period: float, drain_horizon: float
) -> float:
    """Integrate the service trace, including the no-new-arrivals drain."""

    remaining = work
    current = start
    while current < drain_horizon - _EPS:
        index = min(int(current / block_period), len(rates) - 1)
        next_boundary = min(drain_horizon, (index + 1) * block_period)
        if next_boundary <= current + _EPS:
            current = next_boundary
            continue
        capacity = (next_boundary - current) * rates[index]
        if remaining <= capacity + _EPS:
            completion = current + remaining / rates[index]
            return min(completion, drain_horizon)
        remaining -= capacity
        current = next_boundary
    return math.inf


def run_one(
    config: Mapping[str, Any], rho: float, pmr: float, seed: int, *,
    collect_mechanism: bool = False,
) -> dict[str, Any]:
    """Run one synthetic FIFO experiment and return raw measured-control rows.

    ``rho`` is desired aggregate offered work divided by this seed's *realized*
    mean service rate.  The fixed periodic flows contribute first; only the
    bulk mean emission envelope changes across rho.  For a fixed rho and seed,
    changing PMR keeps packet counts, sizes, mean offered load, periodic arrivals,
    and the wireless trace identical.  The achieved rho can differ slightly
    from the target due to fixed-size bulk packet quantization and is reported.
    """

    cfg = normalize_config(config)
    if isinstance(rho, bool) or not isinstance(rho, (float, int)) or not math.isfinite(rho) or rho <= 0:
        raise ValueError("rho must be a positive finite number")
    if isinstance(pmr, bool) or not isinstance(pmr, (float, int)) or not math.isfinite(pmr) or pmr < 1:
        raise ValueError("pmr must be finite and at least 1")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")
    rho = float(rho)
    pmr = float(pmr)

    period = float(cfg["control_period"])
    warmup = int(cfg["warmup_control_packets"])
    measured = int(cfg["measured_control_packets"])
    duration = (warmup + measured) * period
    measurement_start = warmup * period
    for count, label in ((warmup, "warmup"), (measured, "measurement")):
        if not math.isclose(count / pmr, round(count / pmr), rel_tol=0, abs_tol=1e-8):
            raise ValueError(f"{label} interval must contain whole PMR cycles")
    sensor_period = float(cfg["sensor_period"])
    control_work = float(cfg["control_packet_work"])
    sensor_work = float(cfg["sensor_packet_work"])
    bulk_work = float(cfg["bulk_packet_work"])
    block_period = float(cfg["trace_block_period"])
    buffer_work = float(cfg["buffer_work"])
    deadline = float(cfg["deadline_periods"]) * period

    # No packet arrives after duration.  Since the buffer includes the packet in
    # service, every admitted packet must finish within this conservative bound.
    drain_horizon = duration + buffer_work / min(
        float(cfg["trace_low_rate"]), float(cfg["trace_high_rate"])
    ) + block_period
    rates, mean_rate, trace_digest, pattern_digest, trace_cv, drain_horizon = _trace(
        cfg, duration, drain_horizon, seed
    )
    control_count = warmup + measured
    sensor_count = math.ceil(duration / sensor_period - _EPS)
    control_offered = control_count * control_work
    sensor_offered = sensor_count * sensor_work
    bulk_mean_rate = rho * mean_rate - (control_offered + sensor_offered) / duration
    bulk_times, bulk_phase = _bulk_arrivals(
        duration, period, bulk_mean_rate, bulk_work, pmr, seed
    )
    bulk_count = len(bulk_times)
    bulk_offered = bulk_count * bulk_work
    bulk_measured_count = sum(t >= measurement_start for t in bulk_times)
    control_measured_work = measured * control_work
    sensor_measured_count = sum(
        i * sensor_period >= measurement_start for i in range(sensor_count)
    )
    sensor_measured_work = sensor_measured_count * sensor_work
    total_measured_work = (
        control_measured_work + sensor_measured_work + bulk_measured_count * bulk_work
    )
    trace_measured_work = _trace_work(rates, block_period, measurement_start, duration)
    if cfg["trace_balance_windows"]:
        if not math.isclose(
            trace_measured_work, duration - measurement_start,
            rel_tol=0, abs_tol=1e-10,
        ):
            raise RuntimeError("balanced measurement window does not have unit mean")
        # Retain the mathematically exact design denominator in metadata rather
        # than floating-point accumulation noise from summing many blocks.
        trace_measured_work = duration - measurement_start

    rows: list[dict[str, Any]] = [
        {
            "packet_id": i,
            "arrival": (warmup + i) * period,
            "completion": None,
            "status": "unfinished",
            "latency": None,
            "deadline_miss": True,
        }
        for i in range(measured)
    ]
    mechanism_rows: list[dict[str, Any]] = [
        {
            "packet_id": i,
            "arrival": (warmup + i) * period,
            "queue_work_ahead": None,
            "service_start": None,
            "waiting_time": None,
            "service_time": None,
            "bulk_on_at_arrival": None,
            "low_service_at_arrival": None,
            "bulk_on_low_at_arrival": None,
            "bulk_on_fraction_preceding_T": None,
            "low_service_fraction_preceding_T": None,
            "bulk_on_low_fraction_preceding_T": None,
        }
        for i in range(measured)
    ] if collect_mechanism else []

    # A queue entry is (kind, size, measured control packet ID or None).
    waiting: deque[tuple[str, float, int | None]] = deque()
    in_service: tuple[str, float, int | None] | None = None
    service_started_at: float | None = None
    departure = math.inf
    occupied_work = 0.0
    control_index = sensor_index = bulk_index = 0
    max_occupied_work = 0.0
    dropped_control = dropped_sensor = dropped_bulk = 0

    def start_next(at: float) -> None:
        nonlocal in_service, departure, service_started_at
        if waiting:
            in_service = waiting.popleft()
            service_started_at = at
            departure = _finish_time(at, in_service[1], rates, block_period, drain_horizon)
            if collect_mechanism and in_service[0] == "control" and in_service[2] is not None:
                mechanism = mechanism_rows[in_service[2]]
                mechanism["service_start"] = at
                mechanism["waiting_time"] = max(0.0, at - float(mechanism["arrival"]))
        else:
            in_service = None
            service_started_at = None
            departure = math.inf

    def queue_work_ahead(at: float) -> float:
        if in_service is None:
            return 0.0
        assert service_started_at is not None
        served = _trace_work(rates, block_period, service_started_at, at)
        residual = max(0.0, in_service[1] - served)
        return max(0.0, occupied_work - in_service[1] + residual)

    def record_control_arrival(packet_id: int, at: float) -> None:
        mechanism = mechanism_rows[packet_id]
        mechanism["queue_work_ahead"] = queue_work_ahead(at)
        bulk_on = _bulk_on_at(at, period, pmr, bulk_phase)
        rate = rates[min(int(at / block_period), len(rates) - 1)]
        low_service = rate < mean_rate - _EPS
        mechanism["bulk_on_at_arrival"] = bulk_on
        mechanism["low_service_at_arrival"] = low_service
        mechanism["bulk_on_low_at_arrival"] = bulk_on and low_service
        on_fraction, low_fraction, overlap_fraction = _preceding_overlap_fractions(
            at - period, at, period, pmr, bulk_phase, rates, block_period, mean_rate
        )
        mechanism["bulk_on_fraction_preceding_T"] = on_fraction
        mechanism["low_service_fraction_preceding_T"] = low_fraction
        mechanism["bulk_on_low_fraction_preceding_T"] = overlap_fraction

    def admit(kind: str, size: float, packet_id: int | None, at: float) -> None:
        nonlocal occupied_work, max_occupied_work
        nonlocal dropped_control, dropped_sensor, dropped_bulk
        if collect_mechanism and kind == "control" and packet_id is not None:
            record_control_arrival(packet_id, at)
        if occupied_work + size > buffer_work + _EPS:
            if kind == "control":
                dropped_control += 1
                if packet_id is not None:
                    rows[packet_id]["status"] = "dropped"
            elif kind == "sensor":
                dropped_sensor += 1
            else:
                dropped_bulk += 1
            return
        occupied_work += size
        max_occupied_work = max(max_occupied_work, occupied_work)
        item = (kind, size, packet_id)
        if in_service is None:
            waiting.append(item)
            start_next(at)
        else:
            waiting.append(item)

    while control_index < control_count or sensor_index < sensor_count or bulk_index < bulk_count:
        control_t = control_index * period if control_index < control_count else math.inf
        sensor_t = sensor_index * sensor_period if sensor_index < sensor_count else math.inf
        bulk_t = bulk_times[bulk_index] if bulk_index < bulk_count else math.inf
        arrival_t = min(control_t, sensor_t, bulk_t)
        if arrival_t >= duration:
            break

        # Departures have priority at a timestamp; this also starts queued work.
        while departure <= arrival_t + _EPS:
            assert in_service is not None
            kind, size, packet_id = in_service
            occupied_work -= size
            if kind == "control" and packet_id is not None:
                arrival = float(rows[packet_id]["arrival"])
                latency = max(0.0, departure - arrival)
                rows[packet_id]["completion"] = departure
                rows[packet_id]["status"] = "delivered"
                rows[packet_id]["latency"] = latency
                rows[packet_id]["deadline_miss"] = latency >= deadline
                if collect_mechanism:
                    assert service_started_at is not None
                    mechanism_rows[packet_id]["service_time"] = departure - service_started_at
            finished_at = departure
            start_next(finished_at)

        if control_t <= arrival_t + _EPS:
            measured_id = control_index - warmup if control_index >= warmup else None
            admit("control", control_work, measured_id, arrival_t)
            control_index += 1
        if sensor_t <= arrival_t + _EPS:
            admit("sensor", sensor_work, None, arrival_t)
            sensor_index += 1
        while bulk_index < bulk_count and bulk_times[bulk_index] <= arrival_t + _EPS:
            admit("bulk", bulk_work, None, arrival_t)
            bulk_index += 1

    while departure <= drain_horizon + _EPS:
        assert in_service is not None
        kind, size, packet_id = in_service
        occupied_work -= size
        if kind == "control" and packet_id is not None:
            arrival = float(rows[packet_id]["arrival"])
            latency = max(0.0, departure - arrival)
            rows[packet_id]["completion"] = departure
            rows[packet_id]["status"] = "delivered"
            rows[packet_id]["latency"] = latency
            rows[packet_id]["deadline_miss"] = latency >= deadline
            if collect_mechanism:
                assert service_started_at is not None
                mechanism_rows[packet_id]["service_time"] = departure - service_started_at
        finished_at = departure
        start_next(finished_at)

    if any(row["status"] == "unfinished" for row in rows):
        raise RuntimeError("a control packet did not drain within the proven safety horizon")

    total_offered = control_offered + sensor_offered + bulk_offered
    result = {
        "packets": rows,
        "trace_digest": trace_digest,
        "trace_pattern_digest": pattern_digest,
        "config_digest": _canonical_digest({
            key: value for key, value in cfg.items()
            if value is not False or key not in ("trace_normalize_mean", "trace_balance_windows")
        }),
        "offered_control_work": control_offered,
        "offered_sensor_work": sensor_offered,
        "offered_bulk_work": bulk_offered,
        "offered_total_work": total_offered,
        "bulk_packet_count": bulk_count,
        "bulk_packet_count_measured": bulk_measured_count,
        "offered_control_work_measured": control_measured_work,
        "offered_sensor_work_measured": sensor_measured_work,
        "offered_bulk_work_measured": bulk_measured_count * bulk_work,
        "offered_total_work_measured": total_measured_work,
        "offered_load_actual": total_offered / (mean_rate * duration),
        "offered_load_measured_actual": total_measured_work / trace_measured_work,
        "trace_mean_rate": mean_rate,
        "trace_cv": trace_cv,
        "trace_mean_rate_measured": trace_measured_work / (duration - measurement_start),
        "target_rho": rho,
        "pmr": pmr,
        "seed": seed,
        "observation_duration": duration,
        "drain_horizon": drain_horizon,
        "measurement_start": measurement_start,
        "measurement_duration": measured * period,
        "bulk_phase": bulk_phase,
        "max_occupied_work": max_occupied_work,
        "dropped_control_all": dropped_control,
        "dropped_sensor_all": dropped_sensor,
        "dropped_bulk_all": dropped_bulk,
    }
    if collect_mechanism:
        result["mechanism_rows"] = mechanism_rows
    return result
