# -*- coding: utf-8 -*-
"""Headless acceptance batch for the v2 outage/repair state machine.

This is deliberately separate from the UI trace.  It runs one fixed scenario
for seeds 42--46 and exports per-seed outcomes plus mean [95% CI] summaries.
The default is the analytical baseline: Event 2 (resources -> grid) is OFF and
enhanced repair is OFF, so the measured recovery step can be checked against
the state-machine equation before policy contrasts are reported.

Examples
--------
python scripts/run_outage_v2_acceptance.py
python scripts/run_outage_v2_acceptance.py --resource-grid-mode on --tag e2_on
python scripts/run_outage_v2_acceptance.py --cause typhoon --mode full --steps 600
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import random
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, stdev

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.city_manager import CityManager
from config.config import Config
from simulation.simulation import BlackoutSimulation


DEFAULT_CITY = '沈阳市'
DEFAULT_DISTRICT = '沈河区'
DEFAULT_SEEDS = [42, 43, 44, 45, 46]
T975 = {
    2: 12.706204736,
    3: 4.302652730,
    4: 3.182446305,
    5: 2.776445105,
    6: 2.570581836,
    7: 2.446911851,
    8: 2.364624252,
    9: 2.306004135,
    10: 2.262157163,
}


def mean_ci95(values):
    """Return n, mean, lower, upper for finite observations only."""
    clean = [float(value) for value in values if math.isfinite(float(value))]
    n = len(clean)
    if n == 0:
        return 0, float('nan'), float('nan'), float('nan')
    centre = mean(clean)
    if n == 1:
        return 1, centre, float('nan'), float('nan')
    critical = T975.get(n, 1.959963985)
    half_width = critical * stdev(clean) / math.sqrt(n)
    return n, centre, centre - half_width, centre + half_width


def _city_config(city, district, use_road_graph=False):
    manager = CityManager(map_data_dir=str(ROOT / 'simulation map data'))
    geojson = manager.get_district_geojson(city, district, use_no_mountain=True)
    if not geojson:
        raise RuntimeError(f'Cannot locate GeoJSON for {city}/{district}')
    return {
        'city': city,
        'geojson_paths': [geojson],
        'districts': [district],
        'use_road_graph': bool(use_road_graph),
    }


def _set_grid_mode(sim, mode):
    """Set only Event 2; all other government mechanisms keep their own mode."""
    for government in sim.gov_agents.values():
        setter = getattr(government, 'set_event_mode', None)
        if callable(setter):
            setter('resource_to_grid', mode)
        elif mode == 'off':
            government.manual_resource_to_grid = False
            government.use_manual_events = False
        elif mode == 'on':
            government.manual_resource_to_grid = True
            government.use_manual_events = True


def _average(residents, attribute):
    if not residents:
        return 0.0
    return float(sum(float(getattr(r, attribute, 0.0)) for r in residents) / len(residents))


def _flee_ratio(residents):
    if not residents:
        return 0.0
    return float(sum(
        1 for resident in residents
        if getattr(resident, '_dom_action', None) == 'flee'
    ) / len(residents))


def _resolve_district(sim, requested):
    if requested in sim.district_to_zones:
        return requested
    if len(sim.district_to_zones) == 1:
        return next(iter(sim.district_to_zones))
    raise ValueError(f'Cannot resolve district {requested!r} in simulation mapping')


def run_seed(args, seed):
    random.seed(seed)
    np.random.seed(seed)
    config = Config()
    config.simulation.N_RESIDENTS = args.n_residents
    config.simulation.N_ENTERPRISES = args.n_enterprises
    config.simulation.TOTAL_STEPS = args.steps
    config.simulation.RANDOM_SEED = seed
    sim = BlackoutSimulation(
        config=config,
        city_config=_city_config(args.city, args.district, args.use_road_graph),
    )
    district = _resolve_district(sim, args.district)
    preflight = sim.validate_outage_preflight(district)
    if not preflight.get('ok', False):
        raise RuntimeError('Outage preflight failed: ' + '; '.join(preflight.get('errors', [])))
    preflight_warnings = '; '.join(map(str, preflight.get('warnings', [])))
    if preflight_warnings:
        print(f'[preflight] {args.city}/{district}: {preflight_warnings}')
    _set_grid_mode(sim, args.resource_grid_mode)
    sim.grid.manual_repair = bool(args.enhanced_repair)

    state = sim.trigger_outage_scenario(
        district=district,
        mode=args.mode,
        cause=args.cause,
        shed_ratio=args.shed_ratio,
        damage_level=args.damage_level,
        seed=seed,
        scheduled_duration_hours=args.scheduled_duration_hours,
    )
    if state is None:
        raise RuntimeError('The requested scenario created no outage state')
    initial = state.to_audit_dict()
    capacity = max(0.0, float(initial['current_capacity']))
    expected_steps = None
    if state.scheduled_remaining_hours is not None:
        expected_steps = math.ceil(state.scheduled_remaining_hours / sim.dt)
    elif capacity > 0.0:
        expected_steps = (
            math.ceil(state.detection_remaining_hours / sim.dt)
            + math.ceil(state.total_work / (capacity * sim.dt))
        )

    peak_stress = 0.0
    peak_panic = 0.0
    peak_flee = 0.0
    peak_system_help = 0.0
    peak_public_opinion = 0.0
    for _ in range(args.steps):
        sim.step()
        peak_stress = max(peak_stress, _average(sim.residents, 'stress_level'))
        peak_panic = max(peak_panic, _average(sim.residents, 'panic_value'))
        peak_flee = max(peak_flee, _flee_ratio(sim.residents))
        peak_system_help = max(peak_system_help, float(sim.P_hist[-1] if sim.P_hist else 0.0))
        peak_public_opinion = max(
            peak_public_opinion,
            float(getattr(sim, 'public_opinion_pressure', 0.0)),
        )
        if state.status == 'restored':
            break

    audit = state.to_audit_dict()
    restored = state.status == 'restored'
    recovery_steps = (
        int(state.restored_step - state.start_step)
        if restored and state.restored_step is not None else None
    )
    recovery_hours = recovery_steps * sim.dt if recovery_steps is not None else float('nan')
    return {
        'seed': seed,
        'city': args.city,
        'district': district,
        'preflight_warnings': preflight_warnings,
        'mode': args.mode,
        'cause': args.cause,
        'resource_grid_mode': args.resource_grid_mode,
        'enhanced_repair': int(bool(args.enhanced_repair)),
        'requested_shed_ratio': initial['requested_shed_ratio'],
        'realized_shed_ratio': initial['realized_shed_ratio'],
        'affected_load_count': initial['affected_load_count'],
        'total_work': initial['total_work'],
        'initial_capacity': capacity,
        'expected_baseline_steps': expected_steps if expected_steps is not None else '',
        'restored': int(restored),
        'recovery_steps': recovery_steps if recovery_steps is not None else '',
        'recovery_hours': recovery_hours,
        'recovery_step_error': (
            recovery_steps - expected_steps
            if recovery_steps is not None and expected_steps is not None else ''
        ),
        'final_progress': audit['progress'],
        'final_eta_hours': audit['eta_hours'],
        'peak_mean_stress': peak_stress,
        'peak_mean_panic': peak_panic,
        'peak_flee_ratio': peak_flee,
        'peak_system_help_pressure': peak_system_help,
        'peak_public_opinion_pressure': peak_public_opinion,
        'final_weighted_outage_ratio': sim.get_weighted_outage_ratio(),
        'steps_executed': sim.step_count,
    }


def write_outputs(rows, output_dir, args):
    output_dir.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0]) if rows else []
    per_seed = output_dir / 'per_seed_metrics_v2.csv'
    with per_seed.open('w', newline='', encoding='utf-8-sig') as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    summary_metrics = [
        'recovery_hours', 'peak_mean_stress', 'peak_mean_panic',
        'peak_flee_ratio', 'peak_system_help_pressure',
        'peak_public_opinion_pressure', 'final_weighted_outage_ratio',
    ]
    summary_rows = []
    for metric in summary_metrics:
        values = []
        for row in rows:
            try:
                values.append(float(row[metric]))
            except (KeyError, TypeError, ValueError):
                continue
        n, centre, lower, upper = mean_ci95(values)
        summary_rows.append({
            'metric': metric,
            'n': n,
            'mean': centre,
            'ci95_low': lower,
            'ci95_high': upper,
            'mean_ci95': (
                f'{centre:.6f} [{lower:.6f}, {upper:.6f}]'
                if n >= 2 else f'{centre:.6f} [NA, NA]'
            ),
        })
    summary_path = output_dir / 'summary_mean_95ci_v2.csv'
    with summary_path.open('w', newline='', encoding='utf-8-sig') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary_rows[0]))
        writer.writeheader()
        writer.writerows(summary_rows)

    manifest = vars(args).copy()
    manifest.update({
        'schema_version': 'outage_acceptance_v2',
        'created_utc': datetime.now(timezone.utc).isoformat(),
        'seeds': args.seeds,
        'per_seed_csv': per_seed.name,
        'summary_csv': summary_path.name,
    })
    with (output_dir / 'manifest.json').open('w', encoding='utf-8') as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
    return per_seed, summary_path


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--city', default=DEFAULT_CITY)
    parser.add_argument('--district', default=DEFAULT_DISTRICT)
    parser.add_argument('--mode', choices=['full', 'partial'], default='partial')
    parser.add_argument('--shed-ratio', type=float, default=0.5)
    parser.add_argument('--cause', default='equipment_failure')
    parser.add_argument('--damage-level', type=float, default=None)
    parser.add_argument('--scheduled-duration-hours', type=float, default=None)
    parser.add_argument('--n-residents', type=int, default=300)
    parser.add_argument('--n-enterprises', type=int, default=10)
    parser.add_argument('--steps', type=int, default=600)
    parser.add_argument('--seeds', type=int, nargs='+', default=DEFAULT_SEEDS)
    parser.add_argument('--resource-grid-mode', choices=['auto', 'on', 'off'], default='off')
    parser.add_argument('--enhanced-repair', action='store_true')
    parser.add_argument('--use-road-graph', action='store_true')
    parser.add_argument('--output-dir', default=None)
    parser.add_argument('--tag', default='baseline')
    return parser.parse_args()


def main():
    args = parse_args()
    if not 0.0 < args.shed_ratio <= 1.0:
        raise SystemExit('--shed-ratio must be in (0, 1]')
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_dir = Path(args.output_dir) if args.output_dir else (
        ROOT / 'trace_output' / 'outage_v2_acceptance'
        / f'{args.city}_{args.district}_{args.tag}_{timestamp}'
    )
    rows = []
    for seed in args.seeds:
        row = run_seed(args, seed)
        rows.append(row)
        print(
            f"seed={seed}: restored={row['restored']} "
            f"hours={row['recovery_hours']} "
            f"peak_public={row['peak_public_opinion_pressure']:.4f}"
        )
    per_seed, summary = write_outputs(rows, output_dir, args)
    print(f'per-seed: {per_seed}')
    print(f'mean [95% CI]: {summary}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
