# -*- coding: utf-8 -*-
"""E2 mechanism-ablation batch runner.

This script is intentionally thin: all mechanism changes live in
``scripts/run_ablation.py --switch-ablation``. Here we only define the
city/seed/ablation matrix, run each cell in a fresh subprocess, and skip cells
whose ``summary.json`` already exists.

Default full matrix:
    3 cities x 10 seeds x 11 ablation presets = 330 subprocesses

Typical smoke run:
    python -u scripts/run_e2_ablation_matrix.py --seeds 42 --ablations none,no_inertia --n-residents 8 --total-steps 2 --outage-step 1

Full run:
    .\\.venv\\run_in_crowds_env.ps1 scripts\\run_e2_ablation_matrix.py
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import time


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


CITIES = [
    ("厦门市", "思明区"),
    ("沈阳市", "沈河区"),
    ("北京市", "东城区"),
]

DEFAULT_SEEDS = list(range(42, 52))
DEFAULT_ABLATIONS = [
    "none",
    "hard_switch",
    "soft_switch",
    "no_info_network",
    "distance_only_store",
    "no_inertia",
    "no_hysteresis",
    "no_outcome_feedback",
    "no_behavior_demo",
    "i1_minimal",
    "no_flee",
]

TRACE_ROOT = os.path.join(ROOT, "trace_output")
PYTHON_EXE = sys.executable
DEFAULT_OUTPUT_BASE = os.path.join(
    "IJDRR_v7_strict_formal", "E2_ablation_matrix_n10"
)
EXPECTED_MODEL_CONTRACT_VERSION = "ijdrr_strict_v1"
MIN_METRIC_SCHEMA_VERSION = 4


def _parse_csv_or_range(value: str, default: list[int] | None = None) -> list[int]:
    if value is None:
        return list(default or [])
    items: list[int] = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo_s, hi_s = part.split("-", 1)
            lo, hi = int(lo_s), int(hi_s)
            step = 1 if hi >= lo else -1
            items.extend(range(lo, hi + step, step))
        else:
            items.append(int(part))
    return items


def _parse_csv(value: str | None, default: list[str]) -> list[str]:
    if value is None:
        return list(default)
    return [x.strip() for x in value.split(",") if x.strip()]


def _selected_cities(names: list[str]) -> list[tuple[str, str]]:
    if not names or names == ["all"]:
        return list(CITIES)
    aliases = {
        "xiamen": ("厦门市", "思明区"),
        "siming": ("厦门市", "思明区"),
        "shenyang": ("沈阳市", "沈河区"),
        "shenhe": ("沈阳市", "沈河区"),
        "beijing": ("北京市", "东城区"),
        "dongcheng": ("北京市", "东城区"),
    }
    selected: list[tuple[str, str]] = []
    for name in names:
        key = name.lower()
        if key not in aliases:
            raise SystemExit(f"unknown city alias: {name}")
        selected.append(aliases[key])
    return selected


def _check_runtime(dry_run: bool) -> None:
    if dry_run:
        return
    missing = [mod for mod in ("networkx", "osmnx") if importlib.util.find_spec(mod) is None]
    if missing:
        raise SystemExit(
            "[FATAL] missing modules in current Python: "
            + ", ".join(missing)
            + "\nRun with .\\.venv\\run_in_crowds_env.ps1 or the Crowds_sim environment."
        )


def _validate_summary_semantics(summary_path: str, expected: str) -> None:
    try:
        with open(summary_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception as exc:
        raise RuntimeError(f"unreadable summary: {summary_path}") from exc
    if data.get("model_contract_version") != EXPECTED_MODEL_CONTRACT_VERSION:
        raise RuntimeError(f"model_contract_version mismatch: {summary_path}")
    try:
        schema_version = int(data.get("metric_schema_version"))
    except (TypeError, ValueError):
        schema_version = -1
    if schema_version < MIN_METRIC_SCHEMA_VERSION:
        raise RuntimeError(f"metric_schema_version is too old: {summary_path}")
    if data.get("config", {}).get("psychology_semantics") != expected:
        raise RuntimeError(f"summary psychology_semantics mismatch: {summary_path}")
    manifests = data.get("manifest")
    if not isinstance(manifests, dict):
        raise RuntimeError(f"summary manifest missing: {summary_path}")
    for graph_mode in ("off", "on"):
        manifest = manifests.get(graph_mode)
        actual = manifest.get("psychology_semantics") if isinstance(manifest, dict) else None
        if actual != expected:
            raise RuntimeError(
                f"{graph_mode} manifest psychology_semantics mismatch: {summary_path}"
            )
        if manifest.get("model_contract_version") != EXPECTED_MODEL_CONTRACT_VERSION:
            raise RuntimeError(
                f"{graph_mode} manifest model_contract_version mismatch: {summary_path}"
            )
        try:
            manifest_schema = int(manifest.get("metric_schema_version"))
        except (TypeError, ValueError):
            manifest_schema = -1
        if manifest_schema < MIN_METRIC_SCHEMA_VERSION:
            raise RuntimeError(
                f"{graph_mode} manifest metric_schema_version is too old: {summary_path}"
            )


def _build_command(args, city: str, district: str, seed: int, ablation: str) -> tuple[list[str], str]:
    tag = f"e2_{ablation}_seed{seed:02d}"
    run_dir = os.path.join(args.run_root_abs, f"t15_{city}_{district}_{tag}")
    cmd = [
        PYTHON_EXE,
        "-u",
        os.path.join(ROOT, "scripts", "run_ablation.py"),
        "--city",
        city,
        "--district",
        district,
        "--seed",
        str(seed),
        "--tag",
        tag,
        "--output-base",
        args.output_base,
        "--n-residents",
        str(args.n_residents),
        "--n-enterprises",
        str(args.n_enterprises),
        "--total-steps",
        str(args.total_steps),
        "--outage-step",
        str(args.outage_step),
        "--switch-ablation",
        ablation,
        "--psychology-semantics",
        args.psychology_semantics,
        "--use-mml",
    ]
    return cmd, run_dir


def _parse_args():
    parser = argparse.ArgumentParser(description="Run the E2 switch-ablation matrix.")
    parser.add_argument("--cities", default="all", help="all or comma list: xiamen,shenyang,beijing")
    parser.add_argument("--seeds", default="42-51", help="comma/range syntax, e.g. 42 or 42-51")
    parser.add_argument(
        "--ablations",
        default=",".join(DEFAULT_ABLATIONS),
        help="comma list of run_ablation.py --switch-ablation presets",
    )
    parser.add_argument("--output-base", default=DEFAULT_OUTPUT_BASE)
    parser.add_argument("--n-residents", type=int, default=800)
    parser.add_argument("--n-enterprises", type=int, default=30)
    parser.add_argument("--total-steps", type=int, default=120)
    parser.add_argument("--outage-step", type=int, default=16)
    parser.add_argument("--force", action="store_true", help="re-run even when summary.json exists")
    parser.add_argument("--dry-run", action="store_true", help="print commands without running")
    parser.add_argument(
        "--psychology-semantics",
        choices=("strict", "legacy"),
        default="strict",
        help="Psychology ownership contract; strict is required for formal evidence.",
    )
    parsed = parser.parse_args()
    parsed.city_pairs = _selected_cities(_parse_csv(parsed.cities, ["all"]))
    parsed.seed_values = _parse_csv_or_range(parsed.seeds, DEFAULT_SEEDS)
    parsed.ablation_values = _parse_csv(parsed.ablations, DEFAULT_ABLATIONS)
    parsed.output_base_abs = (
        parsed.output_base
        if os.path.isabs(parsed.output_base)
        else os.path.join(TRACE_ROOT, parsed.output_base)
    )
    parsed.run_root_abs = os.path.join(
        parsed.output_base_abs, f"psychology_{parsed.psychology_semantics}"
    )
    return parsed


def main() -> None:
    args = _parse_args()
    _check_runtime(args.dry_run)

    total = len(args.city_pairs) * len(args.seed_values) * len(args.ablation_values)
    done = skipped = failed = 0
    t_global = time.time()

    print("=" * 72)
    print("E2 ablation matrix")
    print(f"cities={len(args.city_pairs)} seeds={args.seed_values} ablations={args.ablation_values}")
    print(f"output={args.run_root_abs}")
    print("=" * 72)

    for city, district in args.city_pairs:
        for seed in args.seed_values:
            for ablation in args.ablation_values:
                done += 1
                cmd, run_dir = _build_command(args, city, district, seed, ablation)
                summary_path = os.path.join(run_dir, "summary.json")
                if os.path.exists(summary_path) and not args.force:
                    _validate_summary_semantics(summary_path, args.psychology_semantics)
                    skipped += 1
                    print(f"[{done}/{total}] skip {city}/{district} seed={seed} ablation={ablation}")
                    continue
                if args.dry_run:
                    print(" ".join(cmd))
                    continue

                print("\n" + "#" * 72)
                print(f"[{done}/{total}] {city}/{district} seed={seed} ablation={ablation}")
                print("#" * 72)
                t0 = time.time()
                try:
                    subprocess.run(cmd, check=True)
                except subprocess.CalledProcessError as exc:
                    failed += 1
                    print(f"[ERROR] exit code {exc.returncode}: {city}/{district} {seed} {ablation}")
                    continue
                _validate_summary_semantics(summary_path, args.psychology_semantics)
                elapsed = time.time() - t_global
                active_done = max(1, done - skipped - failed)
                eta = (elapsed / active_done) * max(0, total - done)
                print(
                    f"[progress] {done}/{total} | this {time.time() - t0:.0f}s | "
                    f"elapsed {elapsed / 60:.1f}min | ETA {eta / 60:.1f}min"
                )

    print("\n" + "=" * 72)
    print(f"E2 complete: total={total}, skipped={skipped}, failed={failed}")
    print(f"output: {args.run_root_abs}")
    print("=" * 72)


if __name__ == "__main__":
    main()
