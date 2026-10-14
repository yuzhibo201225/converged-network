import math
import random
import unittest

from converged_sim.config import DEFAULT_CONFIG
from converged_sim.timescale_model import (
    _DrrScheduler,
    _FifoScheduler,
    _Packet,
    _PriorityScheduler,
    _build_service_trace,
    _bulk_arrivals,
    _on_intervals,
    run_one_timescale,
)


class TimescaleModelTests(unittest.TestCase):
    def setUp(self):
        # Both windows contain complete tau_b cycles and complete 2*tau_s
        # service cycles for every value used below.
        self.config = {
            **DEFAULT_CONFIG,
            "control_period": 1.0,
            "sensor_period": 2.0,
            "control_packet_work": 0.02,
            "sensor_packet_work": 0.04,
            "bulk_packet_work": 0.05,
            "buffer_work": 4.0,
            "trace_low_rate": 0.5,
            "trace_high_rate": 1.5,
            "warmup_control_packets": 12,
            "measured_control_packets": 24,
        }

    def run_arm(self, pmr=2.0, tau_b=3.0, tau_s=1.0, seed=7, **kwargs):
        return run_one_timescale(
            self.config, 0.72, pmr, tau_b, tau_s, seed, **kwargs
        )

    def test_exact_work_and_packet_matching_across_burst_arms(self):
        arms = [
            self.run_arm(pmr=pmr, tau_b=tau_b)
            for pmr in (1.0, 2.0, 3.0)
            for tau_b in (1.0, 2.0, 3.0, 6.0)
        ]
        keys = (
            "bulk_packet_count",
            "bulk_packet_count_measured",
            "offered_bulk_work",
            "offered_bulk_work_measured",
            "offered_total_work",
            "offered_total_work_measured",
            "offered_load_actual",
            "offered_load_measured_actual",
        )
        for key in keys:
            self.assertEqual(len({arm[key] for arm in arms}), 1, key)
        self.assertTrue(all(
            math.isclose(arm["bulk_on_duration"], arm["tau_b"] / arm["pmr"])
            for arm in arms
        ))
        self.assertTrue(all(
            math.isclose(
                arm["bulk_off_duration"],
                arm["tau_b"] * (1.0 - 1.0 / arm["pmr"]),
            )
            for arm in arms
        ))

    def test_burst_and_service_timescales_are_orthogonal(self):
        burst_arms = [self.run_arm(tau_b=value) for value in (1.0, 2.0, 3.0, 6.0)]
        self.assertEqual(len({arm["service_trace_digest"] for arm in burst_arms}), 1)
        self.assertEqual(len({arm["service_phase_fraction"] for arm in burst_arms}), 1)
        self.assertGreater(len({arm["bulk_arrival_digest"] for arm in burst_arms}), 1)

        service_arms = [self.run_arm(tau_s=value) for value in (0.5, 1.0, 2.0, 3.0)]
        self.assertEqual(len({arm["bulk_arrival_digest"] for arm in service_arms}), 1)
        self.assertEqual(len({arm["bulk_phase_fraction"] for arm in service_arms}), 1)
        self.assertGreater(len({arm["service_trace_digest"] for arm in service_arms}), 1)

    def test_service_trace_is_paired_and_has_exact_window_means(self):
        arms = [self.run_arm(pmr=value, tau_b=3.0, tau_s=3.0, seed=19)
                for value in (1.0, 1.5, 2.0, 3.0)]
        self.assertEqual(len({arm["service_trace_digest"] for arm in arms}), 1)
        self.assertEqual(len({arm["service_pattern_digest"] for arm in arms}), 1)
        for arm in arms:
            self.assertAlmostEqual(arm["service_mean_rate"], 1.0, places=12)
            self.assertAlmostEqual(arm["service_mean_rate_measured"], 1.0, places=12)

    def test_random_state_and_phase_are_seed_paired_but_seed_sensitive(self):
        same_seed = [self.run_arm(pmr=value, seed=31) for value in (1.0, 2.0, 3.0)]
        self.assertEqual(len({row["service_initial_high"] for row in same_seed}), 1)
        self.assertEqual(len({row["service_phase_fraction"] for row in same_seed}), 1)
        other = self.run_arm(seed=32)
        self.assertNotEqual(
            (same_seed[0]["service_initial_high"], same_seed[0]["service_phase_fraction"]),
            (other["service_initial_high"], other["service_phase_fraction"]),
        )

    def test_smooth_bulk_uses_seed_randomized_continuous_packet_lattice(self):
        smooth = [self.run_arm(pmr=1.0, seed=seed) for seed in range(8)]
        self.assertGreater(len({row["bulk_arrival_digest"] for row in smooth}), 1)
        self.assertGreater(
            len({row["bulk_packet_lattice_fraction"] for row in smooth}), 1
        )

        for seed in range(8):
            arms = [
                self.run_arm(pmr=pmr, tau_b=tau_b, seed=seed)
                for pmr, tau_b in ((1.0, 1.0), (2.0, 2.0), (3.0, 3.0))
            ]
            self.assertEqual(len({arm["bulk_packet_count"] for arm in arms}), 1)
            self.assertEqual(
                len({arm["bulk_packet_count_measured"] for arm in arms}), 1
            )
            self.assertEqual(len({arm["offered_bulk_work"] for arm in arms}), 1)
            self.assertEqual(
                len({arm["offered_bulk_work_measured"] for arm in arms}), 1
            )

    def test_continuous_packetizer_prefix_does_not_reset_at_a_boundary(self):
        common = {
            "measurement_start": 1.0,
            "measurement_end": 2.0,
            "mean_rate": 0.75,
            "packet_work": 1.0,
            "pmr": 1.0,
            "tau_b": 1.0,
            "seed": 17,
        }
        short = _bulk_arrivals(traffic_end=2.0, **common)[0]
        long = _bulk_arrivals(traffic_end=4.0, **common)[0]
        self.assertEqual(short, [arrival for arrival in long if arrival < 2.0])
        # A continuous two-unit envelope emits one or two packets depending on
        # the paired random offset; it never loses both per-window residuals.
        self.assertGreaterEqual(len(short), 1)

    def test_scheduler_policy_ordering(self):
        packets = [
            _Packet("bulk", 0, 0.0, 0.1, None),
            _Packet("sensor", 0, 0.0, 0.1, None),
            _Packet("control", 0, 0.0, 0.1, None),
        ]
        fifo = _FifoScheduler()
        priority = _PriorityScheduler()
        drr = _DrrScheduler({"control": 0.1, "sensor": 0.1, "bulk": 0.1})
        for packet in packets:
            fifo.push(packet)
            priority.push(packet)
            drr.push(packet)
        self.assertEqual([fifo.pop_next().kind for _ in packets],
                         ["bulk", "sensor", "control"])
        self.assertEqual([priority.pop_next().kind for _ in packets],
                         ["control", "sensor", "bulk"])
        self.assertEqual([drr.pop_next().kind for _ in packets],
                         ["control", "sensor", "bulk"])

    def test_all_policies_are_work_conserving_and_drain_admitted_work(self):
        policies = (
            ("fifo", None),
            ("strict_priority", None),
            ("drr", {"control": 0.02, "sensor": 0.04, "bulk": 0.05}),
        )
        for policy, quanta in policies:
            with self.subTest(policy=policy):
                result = self.run_arm(
                    pmr=3.0,
                    policy=policy,
                    drr_quanta=quanta,
                    collect_instrumentation=True,
                )
                self.assertEqual(result["work_conserving_violations"], 0)
                for kind in ("control", "sensor", "bulk"):
                    self.assertAlmostEqual(
                        result["served_work_all"][kind],
                        result["admitted_work_all"][kind],
                        places=10,
                    )
                sequence = result["service_sequence"]
                for previous, current in zip(sequence, sequence[1:]):
                    # A later packet may start after an idle gap, but never
                    # before the previous nonpreemptive packet completes.
                    self.assertGreaterEqual(current["start"], previous["completion"])

    def test_live_background_guard_removes_measurement_end_cooldown(self):
        base = {
            **self.config,
            "control_packet_work": 0.05,
            "sensor_packet_work": 0.1,
            "bulk_packet_work": 0.1,
            "buffer_work": 50.0,
            "trace_low_rate": 1.0,
            "trace_high_rate": 1.0,
            "warmup_control_packets": 16,
            "measured_control_packets": 24,
        }
        quanta = {"control": 0.01, "sensor": 0.01, "bulk": 1.0}
        short = run_one_timescale(
            base, 0.9, 4.0, 8.0, 2.0, 12,
            policy="drr", drr_quanta=quanta,
        )
        long_config = {**base, "measured_control_packets": 48}
        long = run_one_timescale(
            long_config, 0.9, 4.0, 8.0, 2.0, 12,
            policy="drr", drr_quanta=quanta,
        )
        short_rows = {row["packet_id"]: row for row in short["control_packets"]}
        long_rows = {row["packet_id"]: row for row in long["control_packets"]}
        for packet_id, row in short_rows.items():
            self.assertEqual(row["status"], long_rows[packet_id]["status"])
            self.assertEqual(row["completion"], long_rows[packet_id]["completion"])
            self.assertEqual(row["latency"], long_rows[packet_id]["latency"])

    def test_random_phase_complete_cycle_work_property(self):
        for seed in range(100):
            trace = _build_service_trace(
                duration=24.0,
                drain_horizon=40.0,
                tau_s=1.5,
                low_rate=0.4,
                high_rate=1.6,
                seed=seed,
            )
            self.assertAlmostEqual(trace.integrate(0.0, 12.0), 12.0, places=10)
            self.assertAlmostEqual(trace.integrate(12.0, 24.0), 12.0, places=10)
            phase = random.Random(
                f"timescale-bulk-phase-v3:{seed}"
            ).random() * 3.0
            intervals = _on_intervals(0.0, 12.0, 3.0, 4.0, phase)
            on_width = math.fsum(right - left for left, right in intervals)
            self.assertAlmostEqual(on_width * 4.0, 12.0, places=10)

    def test_event_order_never_starts_a_packet_before_prior_completion(self):
        config = {
            **self.config,
            "control_packet_work": 1.00000000005,
            "sensor_period": 100.0,
            "sensor_packet_work": 0.1,
            "bulk_packet_work": 100.0,
            "buffer_work": 1.00000000005,
            "trace_low_rate": 1.0,
            "trace_high_rate": 1.0,
            "warmup_control_packets": 0,
            "measured_control_packets": 2,
        }
        result = run_one_timescale(
            config, 1.06, 1.0, 1.0, 0.5, 3,
            collect_instrumentation=True,
        )
        sequence = result["service_sequence"]
        for previous, current in zip(sequence, sequence[1:]):
            self.assertGreaterEqual(current["start"], previous["completion"])

    def test_deterministic_replay(self):
        kwargs = {
            "policy": "drr",
            "drr_quanta": {"control": 0.03, "sensor": 0.05, "bulk": 0.07},
            "collect_instrumentation": True,
        }
        self.assertEqual(self.run_arm(seed=41, **kwargs), self.run_arm(seed=41, **kwargs))

    def test_instrumentation_is_outcome_neutral(self):
        plain = self.run_arm(pmr=3.0, policy="strict_priority")
        instrumented = self.run_arm(
            pmr=3.0, policy="strict_priority", collect_instrumentation=True
        )
        instrumentation = instrumented.pop("instrumentation_rows")
        instrumented.pop("service_sequence")
        self.assertEqual(instrumented, plain)
        self.assertEqual(len(instrumentation), len(plain["packets"]))
        for row, mechanism in zip(plain["packets"], instrumentation):
            self.assertGreaterEqual(mechanism["queue_work_at_arrival"], 0.0)
            if row["status"] == "delivered":
                self.assertAlmostEqual(
                    mechanism["waiting_time"] + mechanism["service_time"],
                    row["latency"],
                    places=9,
                )

    def test_equal_timestamp_arrival_order_starts_control_first(self):
        result = self.run_arm(
            pmr=1.0,
            policy="fifo",
            collect_instrumentation=True,
        )
        first = result["service_sequence"][0]
        self.assertEqual(first["class"], "control")
        self.assertEqual(first["start"], 0.0)

    def test_invalid_partial_cycles_and_drr_contract_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "bulk waveform"):
            self.run_arm(tau_b=5.0)
        with self.assertRaisesRegex(ValueError, "service waveform"):
            self.run_arm(tau_s=5.0)
        with self.assertRaisesRegex(ValueError, "drr_quanta"):
            self.run_arm(policy="drr")
        with self.assertRaisesRegex(ValueError, "exactly"):
            self.run_arm(policy="drr", drr_quanta={"control": 1.0})


if __name__ == "__main__":
    unittest.main()
