"""Recompute every ns-3 control endpoint from per-packet measurements."""
import argparse
import csv
import hashlib
import itertools
import json
import statistics
from collections import defaultdict
from pathlib import Path


def audit(source, output):
    source, output = Path(source), Path(output)
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8-sig"))
    if manifest["status"] != "COMPLETE":
        raise ValueError("ns-3 sweep incomplete")
    if output.exists():
        raise FileExistsError(output)
    runs, receipts, packet_count = [], {}, 0
    groups, paired = defaultdict(list), defaultdict(list)
    for index in range(manifest["planned_runs"]):
        summary_path, packet_path = source / f"{index}-summary.csv", source / f"{index}-packets.csv"
        with summary_path.open() as handle:
            summaries = list(csv.DictReader(handle))
        if len(summaries) != 1:
            raise ValueError("expected one run summary")
        row = summaries[0]
        with packet_path.open() as handle:
            packets = list(csv.DictReader(handle))
        if len(packets) != int(row["control_generated"]) or len(packets) != manifest["measured_control_packets"]:
            raise ValueError(f"wrong raw packet count {index}")
        if len({packet["control_sequence"] for packet in packets}) != len(packets):
            raise ValueError(f"duplicate sequence {index}")
        values = sorted(float(packet["latency_s"]) for packet in packets if packet["delivered"] == "1")
        misses = sum(packet["deadline_miss"] == "1" for packet in packets)
        for packet in packets:
            expected_miss = packet["delivered"] != "1" or float(packet["latency_s"]) >= float(row["deadline_s"])
            if expected_miss != (packet["deadline_miss"] == "1"):
                raise ValueError(f"wrong packet deadline flag {index}")
        if len(values) != int(row["control_delivered"]) or misses != int(row["control_deadline_misses"]):
            raise ValueError(f"wrong count endpoint {index}")
        if abs(misses / len(packets) - float(row["control_miss_ratio"])) > 1e-12:
            raise ValueError(f"wrong miss ratio {index}")
        if values:
            position = (len(values) - 1) * .99
            lower = int(position)
            p99 = values[lower]*(1-position+lower) + values[min(lower+1,len(values)-1)]*(position-lower)
            if abs(p99-float(row["control_p99_s"])) > 1e-12:
                raise ValueError(f"wrong P99 {index}")
        packet_count += len(packets)
        runs.append(row)
        groups[tuple(row[key] for key in ("target_rho", "R", "tauB_periods", "queue_mode"))].append(row)
        paired[(row["target_rho"], row["run"])].append(row)
        receipts[index] = {"summary_sha256": hashlib.sha256(summary_path.read_bytes()).hexdigest(),
                           "packets_sha256": hashlib.sha256(packet_path.read_bytes()).hexdigest()}
    for key, rows in paired.items():
        for field in ("realized_bulk_bps", "realized_offered_load", "service_phase_fraction", "realized_mean_service_bps"):
            if len({row[field] for row in rows}) != 1:
                raise ValueError(f"unpaired {key}: {field}")
    points = []
    for key, rows in groups.items():
        values = [float(row["control_p99_over_T"]) for row in rows]
        points.append(dict(zip(("rho", "pmr", "tau_b", "queue"),key), n=len(rows),
            p99_median=statistics.median(values),p99_min=min(values),p99_max=max(values),
            miss_median=statistics.median(float(row["control_miss_ratio"]) for row in rows),
            bulk_goodput_median=statistics.median(float(row["bulk_goodput_bps"]) for row in rows)))
    expected = set(itertools.product(manifest["loads"], [(1.,2.),(3.,.5),(3.,8.)], manifest["queues"], manifest["runs"]))
    actual = [(float(row["target_rho"]), (float(row["R"]),float(row["tauB_periods"])), row["queue_mode"],int(row["run"])) for row in runs]
    if len(actual) != len(set(actual)) or set(actual) != expected or len(runs) != manifest["planned_runs"]:
        raise ValueError("unexpected validation subset grid")
    if any(int(row["seed"]) != manifest["seed"] for row in runs):
        raise ValueError("unexpected validation seed")
    output.mkdir(parents=True)
    for filename, rows in (("runs.csv", runs), ("points.csv", points)):
        with (output / filename).open("w",newline="") as handle:
            writer=csv.DictWriter(handle,fieldnames=list(rows[0]))
            writer.writeheader(); writer.writerows(rows)
    result={"status":"PASS","runs":len(runs),"raw_control_packets":packet_count,
            "points":len(points),"receipts":receipts,"software":manifest}
    (output / "audit.json").write_text(json.dumps(result,indent=2))
    return {key:result[key] for key in ("status","runs","raw_control_packets","points")}


if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--input",required=True)
    parser.add_argument("--out",required=True)
    args=parser.parse_args()
    print(json.dumps(audit(args.input,args.out)))
