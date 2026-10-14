import math
import unittest

from converged_sim.analysis import packet_metrics, percentile
from converged_sim.config import DEFAULT_CONFIG, normalize_config
from converged_sim.model import _finish_time, _trace, _trace_work, run_one


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.config = {
            **DEFAULT_CONFIG,
            "warmup_control_packets": 6,
            "measured_control_packets": 12,
        }

    def test_paired_trace_and_actual_offered_work(self):
        arms = [run_one(self.config, 0.6, pmr, 7) for pmr in (1, 1.5, 2, 3)]
        for result in arms[1:]:
            self.assertEqual(result["trace_digest"], arms[0]["trace_digest"])
            for key in ("offered_control_work", "offered_sensor_work", "offered_bulk_work", "offered_total_work", "bulk_packet_count", "bulk_packet_count_measured", "offered_control_work_measured", "offered_sensor_work_measured", "offered_bulk_work_measured", "offered_total_work_measured", "offered_load_measured_actual", "trace_mean_rate_measured"):
                self.assertEqual(result[key], arms[0][key])
            self.assertEqual([p["arrival"] for p in result["packets"]],
                             [p["arrival"] for p in arms[0]["packets"]])
        self.assertEqual(len(arms[0]["packets"]), 12)

    def test_identical_seed_replays_packet_outcomes(self):
        self.assertEqual(run_one(self.config, 0.8, 3, 4), run_one(self.config, 0.8, 3, 4))

    def test_normalized_service_regimes_match_mean_and_random_pattern(self):
        regimes = ((1.0, 1.0), (0.7, 1.3), (0.4, 1.6))
        outputs = []
        for low, high in regimes:
            cfg = normalize_config({
                **self.config, "trace_low_rate": low,
                "trace_high_rate": high, "trace_normalize_mean": True,
            })
            duration = (cfg["warmup_control_packets"] + cfg["measured_control_packets"]) * cfg["control_period"]
            rates, mean, digest, pattern, cv, horizon = _trace(cfg, duration, duration + 100, 7)
            self.assertEqual(mean, 1.0)
            self.assertAlmostEqual(_trace_work(rates, cfg["trace_block_period"], 0, duration), duration, places=12)
            self.assertGreaterEqual(
                _trace_work(rates, cfg["trace_block_period"], duration, horizon),
                cfg["buffer_work"],
            )
            result = run_one(cfg, 0.6, 1.5, 7)
            self.assertEqual(result["trace_mean_rate"], 1.0)
            self.assertEqual(result["trace_digest"], digest)
            self.assertEqual(result["trace_pattern_digest"], pattern)
            self.assertAlmostEqual(result["trace_cv"], cv)
            outputs.append(result)
        self.assertEqual(len({row["trace_pattern_digest"] for row in outputs}), 1)
        self.assertEqual(len({row["trace_digest"] for row in outputs}), 3)
        self.assertLess(outputs[0]["trace_cv"], outputs[1]["trace_cv"])
        self.assertLess(outputs[1]["trace_cv"], outputs[2]["trace_cv"])
        for key in ("offered_control_work", "offered_sensor_work", "offered_bulk_work",
                    "offered_total_work", "bulk_packet_count", "offered_load_actual"):
            self.assertEqual(len({row[key] for row in outputs}), 1, key)

    def test_normalized_trace_stays_paired_across_pmr_and_repeats(self):
        cfg = {**self.config, "trace_normalize_mean": True,
               "trace_low_rate": 0.4, "trace_high_rate": 1.6}
        arms = [run_one(cfg, 0.8, pmr, 11) for pmr in (1, 1.5, 2, 3)]
        self.assertEqual(len({row["trace_digest"] for row in arms}), 1)
        self.assertEqual(len({row["trace_pattern_digest"] for row in arms}), 1)
        self.assertEqual(len({row["offered_total_work"] for row in arms}), 1)
        self.assertEqual(len({row["bulk_packet_count_measured"] for row in arms}), 1)
        self.assertEqual(arms[3], run_one(cfg, 0.8, 3, 11))

    def test_balanced_trace_has_exact_unit_means_and_shared_patterns(self):
        regimes = ((1.0, 1.0), (0.75, 1.25), (0.5, 1.5))
        outputs = []
        for low, high in regimes:
            cfg = normalize_config({
                **self.config,
                "trace_block_period": 1.0,
                "trace_low_rate": low,
                "trace_high_rate": high,
                "trace_normalize_mean": True,
                "trace_balance_windows": True,
            })
            warmup_duration = cfg["warmup_control_packets"] * cfg["control_period"]
            duration = warmup_duration + cfg["measured_control_packets"] * cfg["control_period"]
            rates, mean, _, pattern, _, _ = _trace(cfg, duration, duration + 100, 23)
            self.assertEqual(mean, 1.0)
            self.assertEqual(_trace_work(rates, cfg["trace_block_period"], 0, warmup_duration),
                             warmup_duration)
            self.assertEqual(_trace_work(rates, cfg["trace_block_period"], warmup_duration, duration),
                             duration - warmup_duration)
            self.assertEqual(_trace_work(rates, cfg["trace_block_period"], 0, duration),
                             duration)
            result = run_one(cfg, 0.6, 1.5, 23)
            self.assertEqual(result["trace_mean_rate"], 1.0)
            self.assertEqual(result["trace_mean_rate_measured"], 1.0)
            self.assertEqual(result["trace_pattern_digest"], pattern)
            outputs.append(result)
        self.assertEqual(len({row["trace_pattern_digest"] for row in outputs}), 1)
        self.assertEqual(len({row["offered_total_work"] for row in outputs}), 1)
        self.assertLess(outputs[0]["trace_cv"], outputs[1]["trace_cv"])
        self.assertLess(outputs[1]["trace_cv"], outputs[2]["trace_cv"])

    def test_balanced_trace_pairs_across_pmr_and_replays(self):
        cfg = {
            **self.config,
            "trace_block_period": 1.0,
            "trace_low_rate": 0.5,
            "trace_high_rate": 1.5,
            "trace_balance_windows": True,
        }
        arms = [run_one(cfg, 0.8, pmr, 29) for pmr in (1, 1.5, 2, 3)]
        self.assertEqual(len({row["trace_digest"] for row in arms}), 1)
        self.assertEqual(len({row["trace_pattern_digest"] for row in arms}), 1)
        self.assertEqual(len({row["trace_mean_rate_measured"] for row in arms}), 1)
        self.assertEqual(arms[-1], run_one(cfg, 0.8, 3, 29))

    def test_balanced_trace_rejects_invalid_windows_and_uncentered_rates(self):
        base = {**self.config, "trace_block_period": 1.0,
                "trace_balance_windows": True}
        with self.assertRaisesRegex(ValueError, "warmup duration.*even"):
            normalize_config({**base, "warmup_control_packets": 5})
        with self.assertRaisesRegex(ValueError, "measurement duration.*even"):
            normalize_config({**base, "measured_control_packets": 11})
        with self.assertRaisesRegex(ValueError, "warmup duration.*integer"):
            normalize_config({**base, "trace_block_period": 4.0})
        with self.assertRaisesRegex(ValueError, "arithmetic mean 1"):
            normalize_config({**base, "trace_low_rate": 0.5,
                              "trace_high_rate": 1.4})
        with self.assertRaisesRegex(ValueError, "trace_balance_windows"):
            normalize_config({"trace_balance_windows": 1})

    def test_normalization_flag_is_boolean_and_default_is_legacy(self):
        with self.assertRaisesRegex(ValueError, "trace_normalize_mean"):
            normalize_config({"trace_normalize_mean": 1})
        omitted = {key: value for key, value in self.config.items()
                   if key not in ("trace_normalize_mean", "trace_balance_windows")}
        explicit_false = {**omitted, "trace_normalize_mean": False,
                          "trace_balance_windows": False}
        self.assertFalse(normalize_config(omitted)["trace_balance_windows"])
        self.assertEqual(run_one(omitted, 0.6, 2, 4),
                         run_one(explicit_false, 0.6, 2, 4))
        normalized = {**omitted, "trace_normalize_mean": True}
        self.assertEqual(run_one(normalized, 0.6, 2, 4),
                         run_one({**normalized, "trace_balance_windows": False}, 0.6, 2, 4))

    def test_measured_window_packet_count_pairing_across_seeds_and_loads(self):
        for rho in (0.2, 0.6, 0.95):
            for seed in range(10):
                counts = [run_one(self.config, rho, pmr, seed)["bulk_packet_count_measured"]
                          for pmr in (1, 1.5, 2, 3)]
                self.assertEqual(len(set(counts)), 1, (rho, seed, counts))

    def test_cross_block_service_integrates_capacity(self):
        self.assertAlmostEqual(_finish_time(0.5, 1.5, [1.0, 2.0], 1.0, 2.0), 1.5)

    def test_accepted_tail_packets_drain_past_arrival_horizon(self):
        cfg = {**self.config, "trace_low_rate": 0.2, "trace_high_rate": 0.2,
               "buffer_work": 10.0}
        result = run_one(cfg, 0.99, 3, 14)
        self.assertFalse(any(p["status"] == "unfinished" for p in result["packets"]))
        self.assertTrue(any(p["completion"] is not None and
                            p["completion"] > result["observation_duration"]
                            for p in result["packets"]))

    def test_miss_denominator_and_delivered_only_p99(self):
        packets = [
            {"status": "delivered", "arrival": 0, "completion": 1},
            {"status": "delivered", "arrival": 0, "completion": 0.5},
            {"status": "dropped", "arrival": 0, "completion": None},
            {"status": "unfinished", "arrival": 0, "completion": None},
        ]
        metrics = packet_metrics(packets, deadline=1.0)
        self.assertEqual(metrics["generated"], 4)
        self.assertEqual(metrics["completed"], 2)
        self.assertEqual(metrics["miss_count"], 3)
        self.assertEqual(metrics["miss_ratio"], 0.75)
        self.assertAlmostEqual(metrics["p99"], percentile([0.5, 1], 0.99))

    def test_mechanism_instrumentation_is_outcome_neutral(self):
        cfg = normalize_config({
            **self.config,
            "trace_low_rate": 0.7,
            "trace_high_rate": 1.3,
            "trace_normalize_mean": True,
        })
        plain = run_one(cfg, 0.6, 3.0, 17)
        instrumented = run_one(cfg, 0.6, 3.0, 17, collect_mechanism=True)
        mechanism = instrumented.pop("mechanism_rows")
        self.assertEqual(instrumented, plain)
        self.assertEqual(len(mechanism), cfg["measured_control_packets"])
        for packet, row in zip(plain["packets"], mechanism):
            self.assertGreaterEqual(row["queue_work_ahead"], 0)
            self.assertGreaterEqual(row["bulk_on_fraction_preceding_T"], 0)
            self.assertLessEqual(row["bulk_on_fraction_preceding_T"], 1)
            self.assertGreaterEqual(row["bulk_on_low_fraction_preceding_T"], 0)
            self.assertLessEqual(
                row["bulk_on_low_fraction_preceding_T"],
                min(row["bulk_on_fraction_preceding_T"],
                    row["low_service_fraction_preceding_T"]),
            )
            if packet["status"] == "delivered":
                self.assertAlmostEqual(
                    row["waiting_time"] + row["service_time"], packet["latency"], places=9
                )

    def test_constant_service_has_no_low_service_overlap(self):
        cfg = normalize_config({
            **self.config,
            "trace_low_rate": 1.0,
            "trace_high_rate": 1.0,
            "trace_normalize_mean": True,
        })
        result = run_one(cfg, 0.6, 3.0, 19, collect_mechanism=True)
        self.assertTrue(all(not row["low_service_at_arrival"]
                            for row in result["mechanism_rows"]))
        self.assertTrue(all(row["low_service_fraction_preceding_T"] == 0
                            for row in result["mechanism_rows"]))
        self.assertTrue(all(row["bulk_on_low_fraction_preceding_T"] == 0
                            for row in result["mechanism_rows"]))


if __name__ == "__main__":
    unittest.main()
