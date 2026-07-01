# -*- coding: utf-8 -*-
"""Aggregate E2 switch-ablation matrix outputs.

Input:
    trace_output/E2_ablation_matrix/t15_*/summary.json

Outputs:
    trace_output/E2_ablation_matrix/e2_ablation_summary.csv
    trace_output/E2_ablation_matrix/e2_ablation_summary.json

The summary table reports graph-off/graph-on means and 95% CI by
city/district/ablation. It also reports the graph-on difference from the
same-city baseline ablation ``none``.
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import math
import os
import sys
from collections import defaultdict


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRACE_ROOT = os.path.join(ROOT, "trace_output")

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


METRICS = [
    "avg_stress",
    "max_stress",
    "pct_stress_gt_06",
    "herd_ratio",
    "flee_ratio",
    "avg_edge_congestion",
]


def ci95(values: list[float]) -> tuple[float, float, float, float]:
    vals = [float(v) for v in values if v is not None]
    if not vals:
        return 0.0, 0.0, 0.0, 0.0
    mean = sum(vals) / len(vals)
    if len(vals) == 1:
        return mean, 0.0, mean, mean
    var = sum((v - mean) ** 2 for v in vals) / (len(vals) - 1)
    std = math.sqrt(var)
    try:
        from scipy.stats import t as student_t

        tval = float(student_t.ppf(0.975, len(vals) - 1))
    except Exception:
        tval = 1.96
    half = tval * std / math.sqrt(len(vals))
    return mean, std, mean - half, mean + half


def load_records(input_dir: str) -> list[dict]:
    records: list[dict] = []
    pattern = os.path.join(input_dir, "t15_*", "summary.json")
    for path in sorted(glob.glob(pattern)):
        with open(path, "r", encoding="utf-8") as fh:
            summary = json.load(fh)
        cfg = summary.get("config", {})
        final = summary.get("final", {})
        rec = {
            "path": path,
            "city": cfg.get("city"),
            "district": cfg.get("district"),
            "seed": cfg.get("seed"),
            "ablation": cfg.get("switch_ablation", "none") or "none",
            "tag": cfg.get("tag", ""),
            "n_residents": cfg.get("n_residents"),
            "total_steps": cfg.get("total_steps"),
        }
        for metric in METRICS:
            pair = final.get(metric, {})
            rec[f"{metric}_off"] = pair.get("off")
            rec[f"{metric}_on"] = pair.get("on")
            off = rec[f"{metric}_off"]
            on = rec[f"{metric}_on"]
            rec[f"{metric}_graph_delta"] = None if off is None or on is None else float(on) - float(off)
        records.append(rec)
    return records


def aggregate(records: list[dict]) -> list[dict]:
    groups: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for rec in records:
        groups[(rec["city"], rec["district"], rec["ablation"])].append(rec)

    rows: list[dict] = []
    for (city, district, ablation), recs in sorted(groups.items()):
        row = {
            "city": city,
            "district": district,
            "ablation": ablation,
            "n_runs": len(recs),
            "seeds": ",".join(str(r.get("seed")) for r in sorted(recs, key=lambda x: x.get("seed") or 0)),
        }
        for metric in METRICS:
            for mode in ("off", "on", "graph_delta"):
                mean, std, lo, hi = ci95([r.get(f"{metric}_{mode}") for r in recs])
                row[f"{metric}_{mode}_mean"] = mean
                row[f"{metric}_{mode}_std"] = std
                row[f"{metric}_{mode}_lo95"] = lo
                row[f"{metric}_{mode}_hi95"] = hi
        rows.append(row)

    baseline_by_city = {
        (r["city"], r["district"]): r
        for r in rows
        if r["ablation"] == "none"
    }
    for row in rows:
        base = baseline_by_city.get((row["city"], row["district"]))
        for metric in METRICS:
            key = f"{metric}_on_mean"
            if base is None:
                row[f"{metric}_on_vs_baseline"] = None
                row[f"{metric}_on_vs_baseline_pct"] = None
                continue
            delta = row[key] - base[key]
            row[f"{metric}_on_vs_baseline"] = delta
            denom = base[key]
            row[f"{metric}_on_vs_baseline_pct"] = 0.0 if abs(denom) < 1e-12 else delta / denom * 100.0
    return rows


def save_csv(rows: list[dict], out_path: str) -> None:
    if not rows:
        return
    fields = list(rows[0].keys())
    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(f"[csv] {out_path}")


def save_json(rows: list[dict], out_path: str) -> None:
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(rows, fh, ensure_ascii=False, indent=2)
    print(f"[json] {out_path}")


def print_brief(rows: list[dict]) -> None:
    print("\nE2 aggregate brief: graph-on difference vs baseline")
    print("-" * 96)
    print(f"{'city/district':<20} {'ablation':<22} {'herd Δ':>10} {'flee Δ':>10} {'stress Δ':>10}")
    for row in rows:
        city = f"{row['city']}/{row['district']}"
        print(
            f"{city:<20} {row['ablation']:<22} "
            f"{row['herd_ratio_on_vs_baseline']:>+10.4f} "
            f"{row['flee_ratio_on_vs_baseline']:>+10.4f} "
            f"{row['avg_stress_on_vs_baseline']:>+10.4f}"
        )


def parse_args():
    parser = argparse.ArgumentParser(description="Aggregate E2 ablation matrix outputs.")
    parser.add_argument("--input-base", default="E2_ablation_matrix")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_dir = (
        args.input_base if os.path.isabs(args.input_base) else os.path.join(TRACE_ROOT, args.input_base)
    )
    if not os.path.exists(input_dir):
        raise SystemExit(f"input directory does not exist: {input_dir}")

    records = load_records(input_dir)
    print(f"[load] {len(records)} summary.json from {input_dir}")
    if not records:
        raise SystemExit("no summary.json files found")

    rows = aggregate(records)
    save_csv(rows, os.path.join(input_dir, "e2_ablation_summary.csv"))
    save_json(rows, os.path.join(input_dir, "e2_ablation_summary.json"))
    print_brief(rows)


if __name__ == "__main__":
    main()
