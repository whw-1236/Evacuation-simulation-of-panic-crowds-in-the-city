from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np
from scipy.stats import t as student_t


PROJECT = Path(__file__).resolve().parents[1]
DEFAULT_F7_BASE = (
    PROJECT / "trace_output" / "IJDRR_v7_strict_formal" / "F7_N_scan_n5"
)
EXPECTED_MODEL_CONTRACT_VERSION = "ijdrr_strict_v1"
MIN_METRIC_SCHEMA_VERSION = 4
CITIES = [
    ("厦门市", "思明区"),
    ("沈阳市", "沈河区"),
    ("北京市", "东城区"),
]
METRICS = [
    "flee_ratio",
    "herd_ratio",
    "pct_stress_gt_06",
    "avg_stress",
]


def parse_int_list(value: str) -> list[int]:
    values: list[int] = []
    for item in value.split(","):
        item = item.strip()
        if item:
            values.append(int(item))
    if not values:
        raise argparse.ArgumentTypeError("expected at least one integer")
    return values


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Aggregate F7 population-size scans into mean/95% CI tables."
    )
    parser.add_argument(
        "--trace-dir",
        type=Path,
        default=DEFAULT_F7_BASE,
        help="Directory containing t15_city_district_N####_seed## runs.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_F7_BASE,
        help="Directory for n_curve_raw.csv and n_curve_ci.csv.",
    )
    parser.add_argument(
        "--seeds",
        type=parse_int_list,
        default=parse_int_list("42,43,44,45,46"),
        help="Comma-separated simulation seeds to aggregate.",
    )
    parser.add_argument(
        "--n-values",
        type=parse_int_list,
        default=parse_int_list("200,500,800,1500,3000"),
        help="Comma-separated resident counts to aggregate.",
    )
    parser.add_argument(
        "--run-tag-template",
        default="N{n:04d}_seed{seed}",
        help="Run tag suffix in t15_city_district_TAG.",
    )
    parser.add_argument(
        "--psychology-semantics",
        choices=("strict", "legacy"),
        default="strict",
        help="Only aggregate runs produced under this psychology contract.",
    )
    return parser.parse_args()


def semantics_dir(base: Path, semantics: str) -> Path:
    leaf = f"psychology_{semantics}"
    return base if base.name == leaf else base / leaf


def mean_ci(values: list[float | None]) -> tuple[float | None, float | None, float | None, int]:
    clean = [float(value) for value in values if value is not None and np.isfinite(value)]
    n = len(clean)
    if n == 0:
        return None, None, None, 0
    mean = float(np.mean(clean))
    if n == 1:
        return mean, None, None, 1
    tcrit = float(student_t.ppf(0.975, n - 1))
    half_width = float(tcrit * np.std(clean, ddof=1) / np.sqrt(n))
    return mean, mean - half_width, mean + half_width, n


def read_summary(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def validate_summary_semantics(summary: dict, expected: str, path: Path) -> None:
    if summary.get("model_contract_version") != EXPECTED_MODEL_CONTRACT_VERSION:
        raise ValueError(f"summary model_contract_version mismatch: {path}")
    try:
        schema_version = int(summary.get("metric_schema_version"))
    except (TypeError, ValueError):
        schema_version = -1
    if schema_version < MIN_METRIC_SCHEMA_VERSION:
        raise ValueError(f"summary metric_schema_version is too old: {path}")
    actual = summary.get("config", {}).get("psychology_semantics")
    if actual != expected:
        raise ValueError(
            f"summary psychology_semantics mismatch: expected={expected!r}, "
            f"actual={actual!r}, path={path}"
        )
    manifests = summary.get("manifest")
    if not isinstance(manifests, dict):
        raise ValueError(f"summary manifest missing: {path}")
    for graph_mode in ("off", "on"):
        manifest = manifests.get(graph_mode)
        actual = manifest.get("psychology_semantics") if isinstance(manifest, dict) else None
        if actual != expected:
            raise ValueError(
                f"{graph_mode} manifest psychology_semantics mismatch: "
                f"expected={expected!r}, actual={actual!r}, path={path}"
            )
        if manifest.get("model_contract_version") != EXPECTED_MODEL_CONTRACT_VERSION:
            raise ValueError(
                f"{graph_mode} manifest model_contract_version mismatch: {path}"
            )
        try:
            manifest_schema = int(manifest.get("metric_schema_version"))
        except (TypeError, ValueError):
            manifest_schema = -1
        if manifest_schema < MIN_METRIC_SCHEMA_VERSION:
            raise ValueError(
                f"{graph_mode} manifest metric_schema_version is too old: {path}"
            )


def metric_values(summary: dict, metric: str) -> dict:
    final = summary.get("final", {})
    values = final.get(metric, {}) or {}
    off = values.get("off")
    on = values.get("on")
    delta = (on - off) if off is not None and on is not None else None
    delta_pct = (
        (on - off) / off * 100.0
        if off is not None and on is not None and abs(off) > 1e-12
        else None
    )
    return {
        f"{metric}_off": off,
        f"{metric}_on": on,
        f"{metric}_delta": delta,
        f"{metric}_delta_pct": delta_pct,
    }


def load_raw_rows(args: argparse.Namespace) -> list[dict]:
    rows = []
    for city, district in CITIES:
        for n_residents in args.n_values:
            for seed in args.seeds:
                tag = args.run_tag_template.format(n=n_residents, seed=seed)
                summary_path = (
                    args.trace_dir
                    / f"t15_{city}_{district}_{tag}"
                    / "summary.json"
                )
                if not summary_path.exists():
                    raise FileNotFoundError(f"Missing summary: {summary_path}")
                summary = read_summary(summary_path)
                validate_summary_semantics(
                    summary, args.psychology_semantics, summary_path
                )
                config = summary.get("config", {})
                expected_config = {
                    "city": city,
                    "district": district,
                    "seed": seed,
                    "tag": tag,
                    "n_residents": n_residents,
                }
                mismatches = {
                    key: (expected, config.get(key))
                    for key, expected in expected_config.items()
                    if config.get(key) != expected
                }
                if mismatches:
                    raise ValueError(
                        f"summary config mismatch: {mismatches}, path={summary_path}"
                    )
                row = {
                    "city": city,
                    "district": district,
                    "N": n_residents,
                    "seed": seed,
                    "run_tag": tag,
                    "psychology_semantics": args.psychology_semantics,
                }
                for metric in METRICS:
                    row.update(metric_values(summary, metric))
                rows.append(row)
    return rows


def aggregate_rows(raw_rows: list[dict]) -> list[dict]:
    grouped: dict[tuple[str, str, int], list[dict]] = {}
    for row in raw_rows:
        key = (row["city"], row["district"], int(row["N"]))
        grouped.setdefault(key, []).append(row)

    out = []
    fields = [
        f"{metric}_{suffix}"
        for metric in METRICS
        for suffix in ("off", "on", "delta", "delta_pct")
    ]
    for (city, district, n_residents), group in grouped.items():
        row = {
            "city": city,
            "district": district,
            "N": n_residents,
            "n_runs": len(group),
            "psychology_semantics": group[0]["psychology_semantics"],
        }
        for field in fields:
            mean, lo, hi, n = mean_ci([item.get(field) for item in group])
            row[f"{field}_mean"] = mean
            row[f"{field}_ci95_lo"] = lo
            row[f"{field}_ci95_hi"] = hi
            row[f"{field}_n"] = n
        out.append(row)
    out.sort(key=lambda item: (item["city"], item["district"], item["N"]))
    return out


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = parse_args()
    args.trace_dir = semantics_dir(args.trace_dir, args.psychology_semantics)
    args.output_dir = semantics_dir(args.output_dir, args.psychology_semantics)
    raw_rows = load_raw_rows(args)
    ci_rows = aggregate_rows(raw_rows)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    raw_csv = args.output_dir / "n_curve_raw.csv"
    ci_csv = args.output_dir / "n_curve_ci.csv"
    write_csv(raw_csv, raw_rows)
    write_csv(ci_csv, ci_rows)
    print(raw_csv)
    print(ci_csv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
