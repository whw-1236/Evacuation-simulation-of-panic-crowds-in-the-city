# -*- coding: utf-8 -*-
"""Validate IJDRR strict simulation outputs before statistical aggregation."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any


MODEL_CONTRACT_VERSION = "ijdrr_strict_v1"
MIN_METRIC_SCHEMA_VERSION = 4
GRAPH_MODES = ("off", "on")
REQUIRED_COLUMNS = {
    "metric_schema_version",
    "metric_phase",
    "psychology_semantics",
    "avg_stress",
    "avg_emotion",
    "avg_panic",
    "pts_ratio",
    "decision_avg_region_psychological_pressure",
    "avg_region_psychological_pressure",
    "avg_episode_outage_hours",
    "avg_cumulative_outage_hours",
    "avg_time_since_service_restoration",
    "service_restoration_ratio",
}
REQUIRED_NUMERIC_COLUMNS = REQUIRED_COLUMNS - {
    "metric_phase",
    "psychology_semantics",
}
UNIT_INTERVAL_FIELDS = {
    "avg_stress",
    "max_stress",
    "pct_stress_gt_06",
    "avg_emotion",
    "avg_panic",
    "pts_ratio",
    "decision_avg_region_psychological_pressure",
    "avg_region_psychological_pressure",
    "occupied_zone_mean_psychological_pressure",
    "service_restoration_ratio",
    "hoard_ratio",
    "herd_ratio",
    "flee_ratio",
    "outage_ratio",
    "full_outage_zone_ratio",
    "unpowered_resident_ratio",
    "outage_requested_shed_ratio",
    "outage_realized_shed_ratio",
    "outage_progress",
    "public_opinion_pressure",
    "system_help_pressure",
    "public_opinion_active",
    "opinion_active_district_ratio",
    "opinion_active_resident_ratio",
    "seir_S",
    "seir_E",
    "seir_I",
    "seir_R",
}
NONNEGATIVE_FIELDS = {
    "avg_episode_outage_hours",
    "avg_cumulative_outage_hours",
    "avg_time_since_service_restoration",
}
PAIR_KEYS = (
    "model_contract_version",
    "metric_schema_version",
    "city",
    "district",
    "seed",
    "n_residents",
    "n_enterprises",
    "total_steps",
    "dt",
    "outage_step",
    "outage_cause",
    "tag",
    "use_mml",
    "switch_ablation",
    "opinion_mode",
    "outage_stress_profile",
    "psychology_semantics",
    "home_distribution",
    "flee_threshold",
    "mml_overrides",
    "psychology_contract",
    "phase_contract",
)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        raise ValueError(f"unreadable JSON: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON root is not an object: {path}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _number(row: dict[str, str], field: str) -> float:
    try:
        value = float(row[field])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid numeric field {field!r}") from exc
    if not math.isfinite(value):
        raise ValueError(f"non-finite numeric field {field!r}: {value!r}")
    return value


def _optional_number(row: dict[str, str], field: str) -> float | None:
    """Parse an optional CSV number, preserving an intentionally blank cell."""
    raw = row.get(field)
    if raw is None or str(raw).strip() == "":
        return None
    return _number(row, field)


def _read_metrics(path: Path) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except Exception as exc:
        raise ValueError(f"unreadable CSV: {path}: {exc}") from exc
    if not rows:
        raise ValueError(f"empty CSV: {path}")
    missing = REQUIRED_COLUMNS - set(rows[0])
    if missing:
        raise ValueError(f"missing CSV fields {sorted(missing)}: {path}")
    return rows


def _validate_metrics(
    rows: list[dict[str, str]], expected_steps: int, semantics: str
) -> list[str]:
    issues: list[str] = []
    if len(rows) != expected_steps:
        issues.append(f"row_count={len(rows)} expected={expected_steps}")
    cumulative: list[float] = []
    restoration: list[float] = []
    restored_ratio: list[float] = []
    for index, row in enumerate(rows, start=1):
        prefix = f"row {index}"
        if row.get("psychology_semantics") != semantics:
            issues.append(
                f"{prefix}: psychology_semantics={row.get('psychology_semantics')!r}"
            )
        if row.get("metric_phase") != "end_of_step":
            issues.append(f"{prefix}: metric_phase={row.get('metric_phase')!r}")
        try:
            required_numbers = {
                field: _number(row, field)
                for field in REQUIRED_NUMERIC_COLUMNS
            }
            schema = required_numbers["metric_schema_version"]
            if schema < MIN_METRIC_SCHEMA_VERSION:
                issues.append(f"{prefix}: metric_schema_version={schema}")
            for field in UNIT_INTERVAL_FIELDS & set(row):
                value = _optional_number(row, field)
                if value is None:
                    # Optional diagnostics can be blank when their mechanism is
                    # unavailable.  Required contract fields were parsed above
                    # and therefore cannot reach this branch blank.
                    continue
                if value < -1e-9 or value > 1.0 + 1e-9:
                    issues.append(f"{prefix}: {field}={value} outside [0,1]")
            for field in NONNEGATIVE_FIELDS:
                value = required_numbers[field]
                if value < -1e-9:
                    issues.append(f"{prefix}: {field}={value} is negative")
            observed_az = required_numbers["avg_region_psychological_pressure"]
            reconstructed_az = (
                0.4 * required_numbers["avg_emotion"]
                + 0.4 * required_numbers["avg_panic"]
                + 0.2 * required_numbers["pts_ratio"]
            )
            if abs(observed_az - reconstructed_az) > 1e-6:
                issues.append(
                    f"{prefix}: A_z identity mismatch "
                    f"{observed_az:.9g}!={reconstructed_az:.9g}"
                )
            cumulative.append(required_numbers["avg_cumulative_outage_hours"])
            restoration.append(
                required_numbers["avg_time_since_service_restoration"]
            )
            restored_ratio.append(required_numbers["service_restoration_ratio"])
        except ValueError as exc:
            issues.append(f"{prefix}: {exc}")
    if any(b + 1e-9 < a for a, b in zip(cumulative, cumulative[1:])):
        issues.append("avg_cumulative_outage_hours is not monotone")
    # Ignore the normal all-powered baseline.  After an observed outage, each
    # contiguous fully-restored interval must have a nondecreasing mean clock;
    # a later re-outage legitimately resets the clock and starts a new episode.
    outage_observed = False
    previous_full = True
    for index, ratio in enumerate(restored_ratio):
        is_full = ratio >= 1.0 - 1e-9
        if not is_full:
            outage_observed = True
        elif outage_observed and previous_full and index > 0:
            if restoration[index] + 1e-9 < restoration[index - 1]:
                issues.append(
                    "restoration clock decreases during continuous full service"
                )
                break
        previous_full = is_full
    return issues


def validate_run_dir(run_dir: Path, semantics: str = "strict") -> dict[str, Any]:
    run_dir = run_dir.resolve()
    issues: list[str] = []
    files: dict[str, str] = {}
    summary_path = run_dir / "summary.json"
    try:
        summary = _load_json(summary_path)
        files[str(summary_path)] = _sha256(summary_path)
    except ValueError as exc:
        return {"run_dir": str(run_dir), "ok": False, "issues": [str(exc)], "files": {}}

    config = summary.get("config") if isinstance(summary.get("config"), dict) else {}
    if summary.get("model_contract_version") != MODEL_CONTRACT_VERSION:
        issues.append("summary model_contract_version mismatch")
    if int(summary.get("metric_schema_version", 0) or 0) < MIN_METRIC_SCHEMA_VERSION:
        issues.append("summary metric_schema_version is missing or old")
    if config.get("psychology_semantics") != semantics:
        issues.append("summary psychology_semantics mismatch")
    if config.get("model_contract_version") != MODEL_CONTRACT_VERSION:
        issues.append("summary config model_contract_version mismatch")
    if int(config.get("metric_schema_version", 0) or 0) < MIN_METRIC_SCHEMA_VERSION:
        issues.append("summary config metric_schema_version is missing or old")
    if not isinstance(config.get("psychology_contract"), dict):
        issues.append("summary psychology_contract missing")
    phase_contract = config.get("phase_contract")
    if not isinstance(phase_contract, dict) or phase_contract.get("global_metrics") != "end_of_step":
        issues.append("summary phase_contract missing or invalid")

    manifests: dict[str, dict[str, Any]] = {}
    expected_steps = int(config.get("total_steps", 0) or 0)
    for graph_mode in GRAPH_MODES:
        graph_dir = run_dir / f"graph_{graph_mode}"
        manifest_path = graph_dir / "manifest.json"
        metrics_path = graph_dir / "global_metrics.csv"
        try:
            manifest = _load_json(manifest_path)
            manifests[graph_mode] = manifest
            files[str(manifest_path)] = _sha256(manifest_path)
        except ValueError as exc:
            issues.append(str(exc))
            continue
        if manifest.get("graph_mode") != graph_mode:
            issues.append(f"graph_{graph_mode}: graph_mode mismatch")
        if bool(manifest.get("use_road_graph")) != (graph_mode == "on"):
            issues.append(f"graph_{graph_mode}: use_road_graph mismatch")
        if manifest.get("psychology_semantics") != semantics:
            issues.append(f"graph_{graph_mode}: psychology_semantics mismatch")
        if manifest.get("model_contract_version") != MODEL_CONTRACT_VERSION:
            issues.append(f"graph_{graph_mode}: model_contract_version mismatch")
        if int(manifest.get("metric_schema_version", 0) or 0) < MIN_METRIC_SCHEMA_VERSION:
            issues.append(f"graph_{graph_mode}: metric_schema_version is old")
        if not manifest.get("config_sha256"):
            issues.append(f"graph_{graph_mode}: config_sha256 missing")
        if not isinstance(manifest.get("psychology_contract"), dict):
            issues.append(f"graph_{graph_mode}: psychology_contract missing")
        git_info = manifest.get("git") if isinstance(manifest.get("git"), dict) else {}
        if not git_info.get("commit") or not git_info.get("worktree_fingerprint_sha256"):
            issues.append(f"graph_{graph_mode}: git evidence incomplete")
        try:
            rows = _read_metrics(metrics_path)
            files[str(metrics_path)] = _sha256(metrics_path)
            issues.extend(
                f"graph_{graph_mode}: {issue}"
                for issue in _validate_metrics(rows, expected_steps, semantics)
            )
        except ValueError as exc:
            issues.append(str(exc))

    if set(manifests) == set(GRAPH_MODES):
        off, on = manifests["off"], manifests["on"]
        for key in PAIR_KEYS:
            if off.get(key) != on.get(key):
                issues.append(f"paired manifest mismatch: {key}")
        off_git = off.get("git") if isinstance(off.get("git"), dict) else {}
        on_git = on.get("git") if isinstance(on.get("git"), dict) else {}
        if off_git.get("worktree_fingerprint_sha256") != on_git.get(
            "worktree_fingerprint_sha256"
        ):
            issues.append("paired worktree fingerprints differ")

    return {
        "run_dir": str(run_dir),
        "ok": not issues,
        "issues": issues,
        "files": files,
        "config": config,
    }


def _discover(root: Path, semantics: str) -> list[Path]:
    root = root.resolve()
    candidates: set[Path] = set()
    if (root / "summary.json").exists():
        candidates.add(root)
    for summary in root.glob(f"**/psychology_{semantics}/t15_*/summary.json"):
        candidates.add(summary.parent)
    if root.name == f"psychology_{semantics}":
        for summary in root.glob("t15_*/summary.json"):
            candidates.add(summary.parent)
    return sorted(candidates)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate strict IJDRR run directories before aggregation."
    )
    parser.add_argument("paths", nargs="*", type=Path, help="Run directories.")
    parser.add_argument("--root", type=Path, help="Discover runs below this root.")
    parser.add_argument(
        "--psychology-semantics",
        choices=("strict", "legacy"),
        default="strict",
    )
    parser.add_argument("--report", type=Path, help="Optional JSON report path.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_dirs = {path.resolve() for path in args.paths}
    if args.root:
        run_dirs.update(_discover(args.root, args.psychology_semantics))
    if not run_dirs:
        raise SystemExit("no run directories found")
    reports = [
        validate_run_dir(path, semantics=args.psychology_semantics)
        for path in sorted(run_dirs)
    ]
    payload = {
        "model_contract_version": MODEL_CONTRACT_VERSION,
        "psychology_semantics": args.psychology_semantics,
        "run_count": len(reports),
        "passed": sum(bool(report["ok"]) for report in reports),
        "failed": sum(not bool(report["ok"]) for report in reports),
        "runs": reports,
    }
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    for report in reports:
        status = "PASS" if report["ok"] else "FAIL"
        print(f"[{status}] {report['run_dir']}")
        for issue in report["issues"]:
            print(f"  - {issue}")
    print(
        f"validated={payload['run_count']} passed={payload['passed']} "
        f"failed={payload['failed']}"
    )
    return 0 if payload["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
