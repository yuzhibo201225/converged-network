"""Validated model defaults, in normalized work and time units."""

from __future__ import annotations

import math
from typing import Any, Mapping


DEFAULT_CONFIG: dict[str, int | float | bool] = {
    "control_period": 1.0,
    "sensor_period": 2.0,
    "control_packet_work": 0.01,
    "sensor_packet_work": 0.04,
    "bulk_packet_work": 0.1,
    "buffer_work": 10.0,
    "trace_block_period": 5.0,
    "trace_low_rate": 0.7,
    "trace_high_rate": 1.3,
    "trace_normalize_mean": False,
    "trace_balance_windows": False,
    "warmup_control_packets": 204,
    "measured_control_packets": 10002,
    "deadline_periods": 1.0,
}

_POSITIVE = (
    "control_period",
    "sensor_period",
    "control_packet_work",
    "sensor_packet_work",
    "bulk_packet_work",
    "buffer_work",
    "trace_block_period",
    "trace_low_rate",
    "trace_high_rate",
    "deadline_periods",
)


def normalize_config(config: Mapping[str, Any] | None = None) -> dict[str, int | float | bool]:
    """Merge model settings with defaults and reject invalid model parameters.

    Sweep-level keys, such as ``loads`` and ``seeds``, may coexist in a caller's
    JSON config and are intentionally ignored here.  The model digest therefore
    covers exactly the settings that can affect one simulation run.
    """

    supplied = config or {}
    if not isinstance(supplied, Mapping):
        raise TypeError("config must be a mapping")
    result = dict(DEFAULT_CONFIG)
    for key in result:
        if key in supplied:
            result[key] = supplied[key]

    for key in _POSITIVE:
        value = result[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{key} must be a positive finite number")
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{key} must be a positive finite number")
        result[key] = float(value)

    for key in ("warmup_control_packets", "measured_control_packets"):
        value = result[key]
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{key} must be an integer")
        if value < (0 if key == "warmup_control_packets" else 1):
            raise ValueError(f"{key} is out of range")

    for key in ("trace_normalize_mean", "trace_balance_windows"):
        if not isinstance(result[key], bool):
            raise ValueError(f"{key} must be a boolean")

    if result["trace_balance_windows"]:
        block = float(result["trace_block_period"])
        period = float(result["control_period"])
        for packet_key, label in (
            ("warmup_control_packets", "warmup"),
            ("measured_control_packets", "measurement"),
        ):
            blocks = int(result[packet_key]) * period / block
            if not math.isclose(blocks, round(blocks), rel_tol=0, abs_tol=1e-10):
                raise ValueError(
                    f"{label} duration must contain an integer number of service blocks "
                    "when trace_balance_windows is enabled"
                )
            if int(round(blocks)) % 2:
                raise ValueError(
                    f"{label} duration must contain an even number of service blocks "
                    "when trace_balance_windows is enabled"
                )
        if not math.isclose(
            (float(result["trace_low_rate"]) + float(result["trace_high_rate"])) / 2,
            1.0,
            rel_tol=0,
            abs_tol=1e-12,
        ):
            raise ValueError(
                "trace_low_rate and trace_high_rate must have arithmetic mean 1 "
                "when trace_balance_windows is enabled"
            )

    if result["buffer_work"] < min(
        result["control_packet_work"],
        result["sensor_packet_work"],
        result["bulk_packet_work"],
    ):
        raise ValueError("buffer_work cannot hold even the smallest packet")

    return result
