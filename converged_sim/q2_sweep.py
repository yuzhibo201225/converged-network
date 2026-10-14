"""Reproducible timescale discovery sweep; raw control rows are always saved."""
import argparse
import csv
import gzip
import hashlib
import itertools
import json
import platform
from pathlib import Path
from .timescale_model import run_one_timescale


def sweep(config_path, output):
    config_path, output = Path(config_path), Path(output)
    spec = json.loads(config_path.read_text(encoding="utf-8"))
    if output.exists():
        raise FileExistsError(output)
    keys = ("loads", "pmrs", "tau_bs", "tau_ss", "policies", "seeds")
    for key in keys:
        values = spec[key]
        if not values or len(values) != len(set(values)):
            raise ValueError(f"empty or duplicate {key}")
    grid = list(itertools.product(*(spec[key] for key in keys)))
    output.mkdir(parents=True)
    source = Path(__file__).with_name("timescale_model.py")
    manifest = {
        "status": "RUNNING", "purpose": "discovery, not confirmation",
        "spec": spec, "planned_runs": len(grid), "completed_runs": 0,
        "config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
        "model_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "python": platform.python_version(), "platform": platform.platform(),
    }
    def save():
        (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    save()
    fields = ["rho", "pmr", "tau_b", "tau_s", "policy", "seed", "p99", "miss_ratio",
              "control_generated", "control_dropped", "bulk_goodput", "bulk_delivery_ratio",
              "offered_load_measured_actual", "offered_bulk_work_measured",
              "service_trace_digest", "bulk_arrival_digest", "config_digest"]
    packet_fields = ["run_id", "class", "packet_id", "arrival", "work", "completion",
                     "status", "latency", "deadline_miss"]
    try:
        with (output / "runs.csv").open("w", newline="", encoding="utf-8") as runs, gzip.open(
            output / "control_packets.csv.gz", "wt", newline="", encoding="utf-8"
        ) as packets:
            writer = csv.DictWriter(runs, fieldnames=fields)
            raw = csv.DictWriter(packets, fieldnames=packet_fields)
            writer.writeheader()
            raw.writeheader()
            for run_id, (rho, pmr, tau_b, tau_s, policy, seed) in enumerate(grid):
                result = run_one_timescale(spec["base_config"], rho, pmr, tau_b, tau_s, seed,
                    policy=policy, drr_quanta=spec.get("drr_quanta"))
                control = result["class_summaries"]["control"]
                bulk = result["class_summaries"]["bulk"]
                row = dict(zip(fields[:6], (rho, pmr, tau_b, tau_s, policy, seed)))
                row.update(p99=control["p99_latency"], miss_ratio=control["deadline_miss_ratio"],
                    control_generated=control["generated"], control_dropped=control["dropped"],
                    bulk_goodput=bulk["goodput_work_per_time"], bulk_delivery_ratio=bulk["delivery_ratio"])
                for field in fields[12:]:
                    row[field] = result[field]
                writer.writerow(row)
                raw.writerows({"run_id": run_id, **packet} for packet in result["control_packets"])
                runs.flush()
                manifest["completed_runs"] = run_id + 1
                save()
                if (run_id + 1) % 10 == 0:
                    print(f"{run_id + 1}/{len(grid)} runs", flush=True)
        manifest["status"] = "COMPLETE"
        manifest["outputs_sha256"] = {
            name: hashlib.sha256((output / name).read_bytes()).hexdigest()
            for name in ("runs.csv", "control_packets.csv.gz")
        }
        save()
    except Exception as error:
        manifest["status"] = "FAILED"
        manifest["error"] = repr(error)
        save()
        raise
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    print(json.dumps(sweep(args.config, args.out)), flush=True)
