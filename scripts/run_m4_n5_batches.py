from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "trace_output" / "IJDRR_v7_strict_formal"
WRAPPER = PROJECT_ROOT / ".venv" / "run_in_crowds_env.ps1"
EXPECTED_MODEL_CONTRACT_VERSION = "ijdrr_strict_v1"
MIN_METRIC_SCHEMA_VERSION = 4

CITIES = [
    ("厦门市", "思明区"),
    ("沈阳市", "沈河区"),
    ("北京市", "东城区"),
]
N_VALUES = [200, 500, 800, 1500, 3000]
HOME_DISTRIBUTIONS = ["poi", "uniform"]


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
        description=(
            "Run M4/MNL batches for n>=5 robustness. "
            "Defaults run the complete strict seed set 42-46."
        )
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Root directory for new trace outputs.",
    )
    parser.add_argument(
        "--seeds",
        type=parse_int_list,
        default=parse_int_list("42,43,44,45,46"),
        help="Comma-separated seeds to run; defaults to the complete n=5 set.",
    )
    parser.add_argument(
        "--n-values",
        type=parse_int_list,
        default=N_VALUES,
        help="Comma-separated resident counts for the F7 population scan.",
    )
    parser.add_argument("--skip-f7", action="store_true", help="Skip N-scan batches.")
    parser.add_argument(
        "--skip-f2",
        action="store_true",
        help="Skip household-distribution centrality batches.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-run even when summary.json already exists.",
    )
    parser.add_argument(
        "--psychology-semantics",
        choices=("strict", "legacy"),
        default="strict",
        help="Psychology ownership contract; strict is required for formal evidence.",
    )
    return parser.parse_args()


def semantics_dir(base: Path, semantics: str) -> Path:
    leaf = f"psychology_{semantics}"
    return base if base.name == leaf else base / leaf


def validate_summary_semantics(summary: Path, expected: str) -> None:
    try:
        data = json.loads(summary.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"unreadable summary: {summary}") from exc
    if data.get("model_contract_version") != EXPECTED_MODEL_CONTRACT_VERSION:
        raise RuntimeError(f"summary model_contract_version mismatch: {summary}")
    try:
        schema_version = int(data.get("metric_schema_version"))
    except (TypeError, ValueError):
        schema_version = -1
    if schema_version < MIN_METRIC_SCHEMA_VERSION:
        raise RuntimeError(f"summary metric_schema_version is too old: {summary}")
    actual = data.get("config", {}).get("psychology_semantics")
    if actual != expected:
        raise RuntimeError(
            f"summary psychology_semantics mismatch: expected={expected!r}, "
            f"actual={actual!r}, path={summary}"
        )
    manifests = data.get("manifest")
    if not isinstance(manifests, dict):
        raise RuntimeError(f"summary manifest missing: {summary}")
    for graph_mode in ("off", "on"):
        manifest = manifests.get(graph_mode)
        actual = manifest.get("psychology_semantics") if isinstance(manifest, dict) else None
        if actual != expected:
            raise RuntimeError(
                f"{graph_mode} manifest psychology_semantics mismatch: "
                f"expected={expected!r}, actual={actual!r}, path={summary}"
            )
        if manifest.get("model_contract_version") != EXPECTED_MODEL_CONTRACT_VERSION:
            raise RuntimeError(
                f"{graph_mode} manifest model_contract_version mismatch: {summary}"
            )
        try:
            manifest_schema = int(manifest.get("metric_schema_version"))
        except (TypeError, ValueError):
            manifest_schema = -1
        if manifest_schema < MIN_METRIC_SCHEMA_VERSION:
            raise RuntimeError(
                f"{graph_mode} manifest metric_schema_version is too old: {summary}"
            )


def command_for_run(script: str, args: list[str]) -> list[str]:
    if WRAPPER.exists():
        return [
            "powershell",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(WRAPPER),
            script,
            *args,
        ]
    return [sys.executable, script, *args]


def run_ablation(
    output_base: Path,
    run_dir: Path,
    log_path: Path,
    args: list[str],
    force: bool,
    psychology_semantics: str,
) -> None:
    summary = run_dir / "summary.json"
    if summary.exists() and not force:
        validate_summary_semantics(summary, psychology_semantics)
        print(f"[skip] {run_dir}", flush=True)
        return

    output_base.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = command_for_run(
        "scripts\\run_ablation.py",
        [
            *args,
            "--output-base",
            str(output_base),
            "--psychology-semantics",
            psychology_semantics,
        ],
    )
    print(f"[run] {log_path.name}", flush=True)
    started = time.time()
    with log_path.open("w", encoding="utf-8") as log:
        proc = subprocess.run(
            cmd,
            cwd=PROJECT_ROOT,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
        )
    elapsed = time.time() - started
    if proc.returncode != 0 or not summary.exists():
        raise RuntimeError(
            f"failed: {log_path.name}; return={proc.returncode}; see {log_path}"
        )
    validate_summary_semantics(summary, psychology_semantics)
    print(f"[ok] {log_path.name} ({elapsed:.1f}s)", flush=True)


def run_f7(args: argparse.Namespace, output_root: Path, log_root: Path) -> None:
    f7_out = output_root / "F7_N_scan_n5"
    f7_run_root = semantics_dir(f7_out, args.psychology_semantics)
    total = len(CITIES) * len(args.seeds) * len(args.n_values)
    done = 0
    for city, district in CITIES:
        for seed in args.seeds:
            for n_residents in args.n_values:
                done += 1
                tag = f"N{n_residents:04d}_seed{seed}"
                run_dir = f7_run_root / f"t15_{city}_{district}_{tag}"
                log_path = log_root / f"F7_{city}_{district}_{tag}.log"
                print(
                    f"[F7 {done}/{total}] {city}/{district} "
                    f"N={n_residents} seed={seed}",
                    flush=True,
                )
                run_ablation(
                    f7_out,
                    run_dir,
                    log_path,
                    [
                        "--city",
                        city,
                        "--district",
                        district,
                        "--n-residents",
                        str(n_residents),
                        "--seed",
                        str(seed),
                        "--tag",
                        tag,
                    ],
                    force=args.force,
                    psychology_semantics=args.psychology_semantics,
                )


def run_f2(args: argparse.Namespace, output_root: Path, log_root: Path) -> None:
    f2_out = output_root / "F2_home_dist_n5"
    f2_run_root = semantics_dir(f2_out, args.psychology_semantics)
    total = len(CITIES) * len(args.seeds) * len(HOME_DISTRIBUTIONS)
    done = 0
    for city, district in CITIES:
        for seed in args.seeds:
            for home_dist in HOME_DISTRIBUTIONS:
                done += 1
                tag = f"{home_dist}_seed{seed}"
                run_dir = f2_run_root / f"t15_{city}_{district}_{tag}"
                log_path = log_root / f"F2_{city}_{district}_{tag}.log"
                print(
                    f"[F2 {done}/{total}] {city}/{district} "
                    f"home={home_dist} seed={seed}",
                    flush=True,
                )
                run_ablation(
                    f2_out,
                    run_dir,
                    log_path,
                    [
                        "--city",
                        city,
                        "--district",
                        district,
                        "--seed",
                        str(seed),
                        "--tag",
                        tag,
                        "--home-distribution",
                        home_dist,
                    ],
                    force=args.force,
                    psychology_semantics=args.psychology_semantics,
                )


def main() -> int:
    args = parse_args()
    output_root = args.output_root.resolve()
    log_root = semantics_dir(
        output_root / "batch_logs", args.psychology_semantics
    )
    if not args.skip_f7:
        run_f7(args, output_root, log_root)
    if not args.skip_f2:
        run_f2(args, output_root, log_root)
    print("[done] M4 additional robustness batches complete", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
