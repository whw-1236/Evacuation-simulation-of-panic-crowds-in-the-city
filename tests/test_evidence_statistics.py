import csv
import math
from types import SimpleNamespace

import pytest

from scripts import run_e6_iia_test as iia
from scripts import run_psychology_semantics_audit as semantics_audit


def test_semantics_audit_uses_student_t_with_four_degrees_of_freedom():
    mean, half_width = semantics_audit._mean_ci([1, 2, 3, 4, 5])

    assert mean == pytest.approx(3.0)
    assert half_width == pytest.approx(1.963243161477561, rel=1e-12)
    normal_half_width = 1.96 * math.sqrt(2.5) / math.sqrt(5)
    assert half_width > normal_half_width


def test_semantics_audit_rejects_pre_v4_metric_schema(tmp_path):
    path = tmp_path / 'global_metrics.csv'
    with path.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=['psychology_semantics', 'metric_schema_version'],
        )
        writer.writeheader()
        writer.writerow({
            'psychology_semantics': 'strict',
            'metric_schema_version': 3,
        })

    with pytest.raises(ValueError, match='Incompatible metric schema'):
        semantics_audit._read_csv(path, 'strict')


def test_iia_grid_rejects_missing_alpha_cell():
    cities = [('CityA', 'DistrictA')]
    seeds = [42]
    alphas = [-7.0, -6.0, -5.0]
    records = [
        {'city': 'CityA', 'district': 'DistrictA', 'seed': 42,
         'alpha_flee': -7.0},
        {'city': 'CityA', 'district': 'DistrictA', 'seed': 42,
         'alpha_flee': -6.0},
    ]

    with pytest.raises(ValueError, match='Incomplete or non-unique'):
        iia._validate_complete_alpha_grid(records, cities, seeds, alphas)


def test_iia_grid_rejects_duplicate_alpha_cell():
    cities = [('CityA', 'DistrictA')]
    seeds = [42]
    alphas = [-7.0, -6.0]
    records = [
        {'city': 'CityA', 'district': 'DistrictA', 'seed': 42,
         'alpha_flee': -7.0},
        {'city': 'CityA', 'district': 'DistrictA', 'seed': 42,
         'alpha_flee': -7.0},
        {'city': 'CityA', 'district': 'DistrictA', 'seed': 42,
         'alpha_flee': -6.0},
    ]

    with pytest.raises(ValueError, match='Incomplete or non-unique'):
        iia._validate_complete_alpha_grid(records, cities, seeds, alphas)


def test_iia_rejects_legacy_cache_missing_evidence_metadata():
    args = SimpleNamespace(
        psychology_semantics='strict',
        n_residents=800,
        n_enterprises=30,
        total_steps=120,
        outage_step=16,
        outage_cause='equipment_failure',
        damage_level=None,
        tail_steps=10,
    )
    expected_config = iia._run_config(
        'CityA', 'DistrictA', -7.0, 42, args
    )
    legacy_cache = {
        'city': 'CityA',
        'district': 'DistrictA',
        'alpha_flee': -7.0,
        'seed': 42,
    }

    with pytest.raises(ValueError, match='cache_schema_version: missing'):
        iia._validate_cached_record(
            legacy_cache, expected_config, {'commit': 'abc', 'dirty': False}
        )


def test_holm_adjustment_is_monotone_in_sorted_p_values():
    adjusted = iia._holm_adjust([0.01, 0.04, 0.03])

    assert adjusted == pytest.approx([0.03, 0.06, 0.06])


def test_iia_slope_output_retains_effect_ci_and_holm_p(tmp_path):
    git_info = {
        'commit': 'abc123',
        'dirty': False,
        'status_short': '',
        'git_diff_sha256': 'diff',
        'untracked_code_sha256': {},
        'worktree_fingerprint_sha256': 'fingerprint',
    }
    records = []
    for seed, seed_shift in ((42, 0.00), (43, 0.01), (44, -0.01)):
        for alpha in (-7.0, -6.0, -5.0):
            odds = {
                'home_hoard': 0.02 * alpha + seed_shift,
                'home_herd': -0.01 * alpha + seed_shift,
                'hoard_herd': 0.03 * alpha + seed_shift,
            }
            records.append({
                'model_contract_version': iia.MODEL_CONTRACT_VERSION,
                'metric_schema_version': iia.METRIC_SCHEMA_VERSION,
                'psychology_semantics': 'strict',
                'run_config_sha256': f'{seed}:{alpha}',
                'git': git_info,
                'city': 'CityA',
                'district': 'DistrictA',
                'alpha_flee': alpha,
                'seed': seed,
                'lnO_ratio_of_means': odds,
                'lnO_mean_log_odds': dict(odds),
                'avg_stress_tail': 0.4 + 0.001 * alpha + seed_shift,
                'n_sub_agentsteps': 100,
                'sub_fraction_mean': 0.5,
                'mean_P_sub': {'flee': 0.25},
            })

    iia.aggregate(records, str(tmp_path))

    with (tmp_path / 'iia_slopes.csv').open(
        encoding='utf-8', newline=''
    ) as handle:
        rows = list(csv.DictReader(handle))
    assert rows
    assert {'ci95_lo', 'ci95_hi', 'p_value', 'p_holm'} <= set(rows[0])
    assert all(row['psychology_semantics'] == 'strict' for row in rows)
