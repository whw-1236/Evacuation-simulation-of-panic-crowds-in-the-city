# -*- coding: utf-8 -*-
"""F7: 三城 × N ∈ {200, 500, 800, 1500, 3000} 居民数扫描 (subprocess 模式)。

每个 (city, N) 调用 run_ablation.py 一次 (内部跑 graph-off + graph-on),
默认总计 3 × 5 seeds × 5 population sizes = 75 次 subprocess。

⚠️ 必须用 Crowds_sim conda env 启动:
    D:/EnvironmentAnaconda/envs/Crowds_sim/python.exe -u scripts/run_f7_n_scan.py

设计:
  - 默认 seeds=42-46，并允许 CLI 覆盖
  - 输出 trace_output/IJDRR_v7_strict_formal/F7_N_scan_n5/psychology_<semantics>/
  - 后处理: analysis/f7_n_curve.py 出 cascade 强度 vs N 的 log-log 曲线

预估时长: N=3000 单次 ~60-120s, 总计 ~30 min
"""
import argparse
import importlib.util
import json
import os
import sys
import subprocess
import time
from itertools import product

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

for _mod in ('networkx', 'osmnx'):
    if importlib.util.find_spec(_mod) is None:
        raise SystemExit(
            f'[FATAL] {_mod} 未安装。本脚本必须用 Crowds_sim env 启动:\n'
            f'    D:/EnvironmentAnaconda/envs/Crowds_sim/python.exe -u scripts/run_f7_n_scan.py'
        )


CITIES = [
    ('厦门市', '思明区'),
    ('沈阳市', '沈河区'),
    ('北京市', '东城区'),
]
N_VALUES = [200, 500, 800, 1500, 3000]
SEEDS = [42, 43, 44, 45, 46]

USE_MML = os.environ.get('BLACKOUT_USE_MML', '1') != '0'   # MML default since 2026-06-28; set '0' for sigmoid legacy
DEFAULT_OUTPUT_BASE = os.path.join(
    'IJDRR_v7_strict_formal',
    'F7_N_scan_n5' if USE_MML else 'F7_N_scan_n5_sigmoid',
)
TRACE_ROOT = os.path.join(ROOT, 'trace_output')
PYTHON_EXE = sys.executable
EXPECTED_MODEL_CONTRACT_VERSION = 'ijdrr_strict_v1'
MIN_METRIC_SCHEMA_VERSION = 4


def parse_int_list(value):
    values = []
    for part in value.split(','):
        part = part.strip()
        if not part:
            continue
        if '-' in part:
            lo_text, hi_text = part.split('-', 1)
            lo, hi = int(lo_text), int(hi_text)
            step = 1 if hi >= lo else -1
            values.extend(range(lo, hi + step, step))
        else:
            values.append(int(part))
    if not values:
        raise argparse.ArgumentTypeError('expected at least one integer')
    return values


def parse_args():
    parser = argparse.ArgumentParser(description="Run the F7 population-size scan.")
    parser.add_argument(
        "--psychology-semantics",
        choices=("strict", "legacy"),
        default="strict",
        help="Psychology ownership contract; strict is required for formal evidence.",
    )
    parser.add_argument(
        '--seeds',
        type=parse_int_list,
        default=list(SEEDS),
        help='Comma/range seed list; defaults to 42-46.',
    )
    parser.add_argument(
        '--n-values',
        type=parse_int_list,
        default=list(N_VALUES),
        help='Comma/range resident-count list.',
    )
    parser.add_argument(
        '--output-base',
        default=DEFAULT_OUTPUT_BASE,
        help='Trace output base, relative to trace_output or absolute.',
    )
    return parser.parse_args()


def validate_summary_semantics(summary_path, expected):
    try:
        with open(summary_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception as exc:
        raise RuntimeError(f"unreadable summary: {summary_path}") from exc
    if data.get('model_contract_version') != EXPECTED_MODEL_CONTRACT_VERSION:
        raise RuntimeError(f'model_contract_version mismatch: {summary_path}')
    try:
        schema_version = int(data.get('metric_schema_version'))
    except (TypeError, ValueError):
        schema_version = -1
    if schema_version < MIN_METRIC_SCHEMA_VERSION:
        raise RuntimeError(f'metric_schema_version is too old: {summary_path}')
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
        if manifest.get('model_contract_version') != EXPECTED_MODEL_CONTRACT_VERSION:
            raise RuntimeError(
                f'{graph_mode} manifest model_contract_version mismatch: {summary_path}'
            )
        try:
            manifest_schema = int(manifest.get('metric_schema_version'))
        except (TypeError, ValueError):
            manifest_schema = -1
        if manifest_schema < MIN_METRIC_SCHEMA_VERSION:
            raise RuntimeError(
                f'{graph_mode} manifest metric_schema_version is too old: {summary_path}'
            )


def main():
    args = parse_args()
    output_base_abs = (
        args.output_base
        if os.path.isabs(args.output_base)
        else os.path.join(TRACE_ROOT, args.output_base)
    )
    run_root = os.path.join(
        output_base_abs, f"psychology_{args.psychology_semantics}"
    )
    total = len(CITIES) * len(args.seeds) * len(args.n_values)
    done = 0
    skipped = 0
    failed = 0
    t_global = time.time()

    for city, district in CITIES:
        for seed, N in product(args.seeds, args.n_values):
            done += 1
            tag = f'N{N:04d}_seed{seed}'
            run_dir = os.path.join(run_root, f't15_{city}_{district}_{tag}')

            summary_path = os.path.join(run_dir, 'summary.json')
            if os.path.exists(summary_path):
                validate_summary_semantics(summary_path, args.psychology_semantics)
                skipped += 1
                print(f'[{done}/{total}] skip (已完成) {city}/{district} {tag}',
                      flush=True)
                continue

            cmd = [
                PYTHON_EXE, '-u', os.path.join(ROOT, 'scripts', 'run_ablation.py'),
                '--city', city, '--district', district,
                '--seed', str(seed), '--tag', tag,
                '--n-residents', str(N),
                '--output-base', args.output_base,
                '--psychology-semantics', args.psychology_semantics,
            ]
            if not USE_MML:
                cmd.append('--no-mml')
            print(f'\n{"#"*70}', flush=True)
            print(f'[{done}/{total}] {city}/{district} {tag} (N={N})', flush=True)
            print(f'{"#"*70}', flush=True)

            t0 = time.time()
            try:
                subprocess.run(cmd, check=True)
            except subprocess.CalledProcessError as ex:
                failed += 1
                print(f'[ERROR] {city}/{district} {tag}: exit code {ex.returncode}',
                      flush=True)
                continue

            validate_summary_semantics(summary_path, args.psychology_semantics)

            dt = time.time() - t0
            elapsed = time.time() - t_global
            actually_done = done - skipped - failed
            avg = elapsed / max(1, actually_done)
            remain = avg * (total - done)
            print(f'[progress] {done}/{total} ({(done/total*100):.0f}%) | '
                  f'this {dt:.0f}s | elapsed {elapsed/60:.1f}min | '
                  f'ETA {remain/60:.1f}min', flush=True)

    print(f'\n{"="*70}', flush=True)
    print(f'F7 complete: {total} runs ({skipped} skipped, {failed} failed), '
          f'total {(time.time()-t_global)/60:.1f} min', flush=True)
    print(f'output: {run_root}', flush=True)
    print(f'{"="*70}', flush=True)


if __name__ == '__main__':
    main()
