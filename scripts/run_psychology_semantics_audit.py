# -*- coding: utf-8 -*-
"""Run and audit the strict-versus-legacy psychology semantics experiment.

This runner deliberately keeps the two semantics in separate output trees.  It
then creates paired, seed-level audit tables and Student-t 95% CI curves.  It
is intended for *mechanism auditing*, not for mixing legacy output into paper
statistics.

Example (the formal batch should use the manuscript's full scenario settings)::

    python scripts/run_psychology_semantics_audit.py \
        --seeds 42,43,44,45,46 --output-base IJDRR_psychology_audit_v1

For a fast implementation check, explicitly reduce the model size and horizon::

    python scripts/run_psychology_semantics_audit.py --seeds 42,43,44,45,46 \
        --n-residents 24 --n-enterprises 3 --total-steps 180 --outage-step 2 \
        --output-base psychology_semantics_audit_smoke
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from typing import Iterable

import numpy as np
from scipy import stats as sstats


ROOT = Path(__file__).resolve().parents[1]
TRACE_ROOT = ROOT / 'trace_output'
SEMANTICS = ('strict', 'legacy')
DEFAULT_SEEDS = (42, 43, 44, 45, 46)
MODEL_CONTRACT_VERSION = 'ijdrr_strict_v1'
METRIC_SCHEMA_VERSION = 4
AUDIT_METRICS = (
    'avg_stress', 'avg_emotion', 'avg_panic',
    'avg_region_psychological_pressure', 'service_restoration_ratio',
    'avg_episode_outage_hours', 'avg_cumulative_outage_hours',
    'avg_time_since_service_restoration', 'flee_ratio',
)
CURVE_METRICS = (
    ('avg_stress', 'Mean unified stress, $\\sigma$'),
    ('avg_emotion', 'Mean expressed emotion, $E$'),
    ('avg_panic', 'Mean panic, $P$'),
    ('service_restoration_ratio', 'Service restoration ratio'),
)


def _parse_seeds(text: str) -> tuple[int, ...]:
    seeds = tuple(int(item.strip()) for item in text.split(',') if item.strip())
    if len(seeds) < 2:
        raise argparse.ArgumentTypeError('At least two fixed seeds are required for an audit.')
    if len(set(seeds)) != len(seeds):
        raise argparse.ArgumentTypeError('Seeds must be unique.')
    return seeds


def _mean_ci(values: Iterable[float]) -> tuple[float, float]:
    values = np.asarray(list(values), dtype=float)
    if not len(values):
        return float('nan'), float('nan')
    mean = float(values.mean())
    if len(values) < 2:
        return mean, float('nan')
    ci = (
        float(sstats.t.ppf(0.975, len(values) - 1))
        * float(values.std(ddof=1))
        / math.sqrt(len(values))
    )
    return mean, ci


def _pointwise_t95_halfwidth(matrix: np.ndarray) -> np.ndarray:
    """Return pointwise Student-t 95% CI half-widths across seed rows.

    A formal evidence plot must not silently fall back to the large-sample
    normal critical value.  A single-seed input therefore returns NaNs rather
    than a visually misleading zero-width interval.
    """
    matrix = np.asarray(matrix, dtype=float)
    if matrix.ndim != 2:
        raise ValueError(f'Expected a 2-D seed-by-time matrix, got {matrix.shape!r}')
    n = matrix.shape[0]
    if n < 2:
        return np.full(matrix.shape[1], np.nan, dtype=float)
    critical = float(sstats.t.ppf(0.975, n - 1))
    return critical * matrix.std(axis=0, ddof=1) / math.sqrt(n)


def _run_dir(batch_root: Path, semantics: str, city: str, district: str, tag: str, seed: int) -> Path:
    return batch_root / f'psychology_{semantics}' / f't15_{city}_{district}_{tag}_s{seed}'


def _read_csv(path: Path, expected_semantics: str) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f'Missing trace: {path}')
    with path.open('r', encoding='utf-8-sig', newline='') as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError(f'Empty trace: {path}')
    observed = {row.get('psychology_semantics', '') for row in rows}
    if observed != {expected_semantics}:
        raise ValueError(
            f'Semantic contamination in {path}: expected {expected_semantics!r}, got {sorted(observed)!r}'
        )
    schemas = set()
    for row in rows:
        try:
            schemas.add(float(row.get('metric_schema_version', '')))
        except (TypeError, ValueError) as exc:
            raise ValueError(f'Missing or invalid metric_schema_version in {path}') from exc
    if schemas != {float(METRIC_SCHEMA_VERSION)}:
        raise ValueError(
            f'Incompatible metric schema in {path}: expected '
            f'{METRIC_SCHEMA_VERSION}, got {sorted(schemas)!r}'
        )
    return rows


def _float(row: dict[str, str], key: str) -> float:
    try:
        return float(row[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f'Missing or invalid {key!r} in global_metrics.csv') from exc


def _run_batch(args: argparse.Namespace, batch_root: Path) -> None:
    for seed in args.seeds:
        for semantics in SEMANTICS:
            run_dir = _run_dir(batch_root, semantics, args.city, args.district, args.tag, seed)
            summary_path = run_dir / 'summary.json'
            if summary_path.exists():
                with summary_path.open('r', encoding='utf-8-sig') as handle:
                    existing = json.load(handle)
                configured = str(existing.get('config', {}).get('psychology_semantics', ''))
                if configured == semantics:
                    print(f'[skip] seed={seed} semantics={semantics}: {run_dir}', flush=True)
                    continue
                raise RuntimeError(
                    f'Refusing to reuse incompatible directory {run_dir}: {configured!r} != {semantics!r}'
                )

            command = [
                sys.executable, '-u', str(ROOT / 'scripts' / 'run_ablation.py'),
                '--city', args.city, '--district', args.district,
                '--seed', str(seed), '--tag', f'{args.tag}_s{seed}',
                '--output-base', args.output_base,
                '--psychology-semantics', semantics,
            ]
            for option, value in (
                ('--n-residents', args.n_residents),
                ('--n-enterprises', args.n_enterprises),
                ('--total-steps', args.total_steps),
                ('--outage-step', args.outage_step),
            ):
                if value is not None:
                    command.extend((option, str(value)))
            if args.no_mml:
                command.append('--no-mml')

            print(f'\n[run] seed={seed} semantics={semantics}', flush=True)
            subprocess.run(command, cwd=ROOT, check=True)


def _collect(args: argparse.Namespace, batch_root: Path) -> tuple[list[dict[str, object]], dict[tuple[int, str, str], list[dict[str, str]]]]:
    audit_rows: list[dict[str, object]] = []
    traces: dict[tuple[int, str, str], list[dict[str, str]]] = {}

    for seed in args.seeds:
        for graph in ('graph_off', 'graph_on'):
            paired: dict[str, list[dict[str, str]]] = {}
            for semantics in SEMANTICS:
                run_dir = _run_dir(batch_root, semantics, args.city, args.district, args.tag, seed)
                rows = _read_csv(run_dir / graph / 'global_metrics.csv', semantics)
                paired[semantics] = rows
                traces[(seed, semantics, graph)] = rows

            strict, legacy = paired['strict'], paired['legacy']
            if len(strict) != len(legacy):
                raise ValueError(
                    f'Unpaired step count for seed={seed}, {graph}: strict={len(strict)}, legacy={len(legacy)}'
                )
            for metric in AUDIT_METRICS:
                for statistic, strict_value, legacy_value in (
                    ('end', _float(strict[-1], metric), _float(legacy[-1], metric)),
                    ('peak', max(_float(row, metric) for row in strict), max(_float(row, metric) for row in legacy)),
                ):
                    delta = strict_value - legacy_value
                    audit_rows.append({
                        'seed': seed,
                        'graph': graph,
                        'statistic': statistic,
                        'metric': metric,
                        'strict_value': strict_value,
                        'legacy_value': legacy_value,
                        'strict_minus_legacy': delta,
                        'relative_to_legacy_pct': (100.0 * delta / legacy_value) if abs(legacy_value) > 1e-12 else float('nan'),
                    })
    return audit_rows, traces


def _write_audit(batch_root: Path, audit_rows: list[dict[str, object]], args: argparse.Namespace) -> Path:
    audit_path = batch_root / 'psychology_semantics_audit.csv'
    summary_path = batch_root / 'psychology_semantics_audit_summary.csv'
    manifest_path = batch_root / 'psychology_semantics_audit_manifest.json'

    with audit_path.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(audit_rows[0]))
        writer.writeheader()
        writer.writerows(audit_rows)

    summary_rows: list[dict[str, object]] = []
    groups: dict[tuple[str, str, str], list[dict[str, object]]] = {}
    for row in audit_rows:
        groups.setdefault((str(row['graph']), str(row['statistic']), str(row['metric'])), []).append(row)
    for (graph, statistic, metric), rows in sorted(groups.items()):
        strict_mean, strict_ci = _mean_ci(float(row['strict_value']) for row in rows)
        legacy_mean, legacy_ci = _mean_ci(float(row['legacy_value']) for row in rows)
        delta_mean, delta_ci = _mean_ci(float(row['strict_minus_legacy']) for row in rows)
        summary_rows.append({
            'seed_count': len(rows), 'graph': graph, 'statistic': statistic, 'metric': metric,
            'strict_mean': strict_mean, 'strict_ci95': strict_ci,
            'legacy_mean': legacy_mean, 'legacy_ci95': legacy_ci,
            'paired_delta_mean': delta_mean, 'paired_delta_ci95': delta_ci,
        })
    with summary_path.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary_rows[0]))
        writer.writeheader()
        writer.writerows(summary_rows)

    manifest = {
        'purpose': 'mechanism audit only; legacy rows must not be pooled into formal strict-mode statistics',
        'city': args.city,
        'district': args.district,
        'tag': args.tag,
        'seeds': list(args.seeds),
        'semantics': list(SEMANTICS),
        'model_contract_version': MODEL_CONTRACT_VERSION,
        'metric_schema_version': METRIC_SCHEMA_VERSION,
        'ci95_method': 'Student-t, two-sided, df=n-1',
        'strict_is_paper_default': True,
        'audit_rows': len(audit_rows),
    }
    with manifest_path.open('w', encoding='utf-8') as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
    print(f'[audit] {audit_path}')
    print(f'[audit] {summary_path}')
    return manifest_path


def _plot_curves(batch_root: Path, traces: dict[tuple[int, str, str], list[dict[str, str]]], args: argparse.Namespace) -> Path:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    graph = args.audit_graph
    plt.rcParams.update({
        'font.family': 'Arial', 'font.size': 8,
        'axes.titlesize': 9, 'axes.labelsize': 8,
        'legend.fontsize': 8,
    })
    fig, axes = plt.subplots(2, 2, figsize=(7.48, 5.3), sharex=True)
    for panel, (axis, (metric, title)) in enumerate(zip(axes.ravel(), CURVE_METRICS)):
        if metric == 'service_restoration_ratio':
            # Both modes use the same DistrictOutageState truth.  Drawing two
            # identical lines would hide one curve and falsely suggest a
            # psychology-dependent service schedule.
            series = [
                np.asarray([_float(row, metric) for row in traces[(seed, 'strict', graph)]], dtype=float)
                for seed in args.seeds
            ]
            matrix = np.vstack(series)
            mean = matrix.mean(axis=0)
            ci = _pointwise_t95_halfwidth(matrix)
            hours = np.asarray([_float(row, 't_hour') for row in traces[(args.seeds[0], 'strict', graph)]])
            axis.plot(hours, mean, color='#333333', lw=1.5, label='shared load-state recovery')
            axis.fill_between(hours, mean - ci, mean + ci, color='#333333', alpha=0.15, linewidth=0)
        else:
            for semantics, color, style, label in (
                ('strict', '#0072B2', '-', 'strict (derived E/P)'),
                ('legacy', '#D55E00', '--', 'legacy (historical path)'),
            ):
                series = [
                    np.asarray([_float(row, metric) for row in traces[(seed, semantics, graph)]], dtype=float)
                    for seed in args.seeds
                ]
                matrix = np.vstack(series)
                mean = matrix.mean(axis=0)
                ci = _pointwise_t95_halfwidth(matrix)
                hours = np.asarray([_float(row, 't_hour') for row in traces[(args.seeds[0], semantics, graph)]])
                axis.plot(hours, mean, color=color, linestyle=style, lw=1.6, label=label)
                axis.fill_between(hours, mean - ci, mean + ci, color=color, alpha=0.16, linewidth=0)
        axis.set_title(title)
        axis.text(-0.12, 1.08, chr(ord('a') + panel), transform=axis.transAxes,
                  fontweight='bold', va='top')
        axis.set_ylim(bottom=0)
        axis.grid(alpha=0.25, linewidth=0.5)
    axes[0, 0].legend(frameon=False)
    axes[1, 1].legend(frameon=False, loc='center right')
    axes[1, 0].set_xlabel('Simulation time (h)')
    axes[1, 1].set_xlabel('Simulation time (h)')
    fig.suptitle(
        f'Strict versus legacy mechanism audit ({graph}; mean $\\pm$ 95% CI; n={len(args.seeds)} fixed seeds)',
        fontsize=10,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    output = batch_root / 'psychology_semantics_audit_curves.png'
    fig.savefig(output, dpi=300, bbox_inches='tight')
    fig.savefig(output.with_suffix('.pdf'), bbox_inches='tight')
    plt.close(fig)
    print(f'[audit] {output}')
    print(f'[audit] {output.with_suffix(".pdf")}')
    return output


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Strict/legacy paired multi-seed psychology-semantics audit.')
    parser.add_argument('--city', default='厦门市')
    parser.add_argument('--district', default='思明区')
    parser.add_argument('--seeds', type=_parse_seeds, default=DEFAULT_SEEDS,
                        help='Comma-separated fixed seeds; default: 42,43,44,45,46')
    parser.add_argument('--tag', default='semantics_audit')
    parser.add_argument('--output-base', default='IJDRR_psychology_semantics_audit')
    parser.add_argument('--collect-only', action='store_true',
                        help='Do not run models; only audit an already-complete paired batch.')
    parser.add_argument('--audit-graph', choices=('graph_off', 'graph_on'), default='graph_on')
    parser.add_argument('--n-residents', type=int, default=None)
    parser.add_argument('--n-enterprises', type=int, default=None)
    parser.add_argument('--total-steps', type=int, default=None)
    parser.add_argument('--outage-step', type=int, default=None)
    parser.add_argument('--no-mml', action='store_true')
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    batch_root = Path(args.output_base)
    if not batch_root.is_absolute():
        batch_root = TRACE_ROOT / batch_root
    batch_root.mkdir(parents=True, exist_ok=True)
    if not args.collect_only:
        _run_batch(args, batch_root)
    audit_rows, traces = _collect(args, batch_root)
    _write_audit(batch_root, audit_rows, args)
    _plot_curves(batch_root, traces, args)


if __name__ == '__main__':
    main()
