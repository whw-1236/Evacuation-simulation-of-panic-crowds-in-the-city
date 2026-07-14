# -*- coding: utf-8 -*-
"""Smoke checks for literature-driven validation controls."""
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.unified_stress_model import unified_stress_model
from scripts.run_ablation import GLOBAL_METRIC_FIELDS, _collect_step_metrics
from simulation.simulation import BlackoutSimulation


REQUIRED_FIELDS = {
    'metric_schema_version',
    'metric_phase',
    'psychology_semantics',
    'pts_ratio',
    'outage_ratio',
    'full_outage_zone_ratio',
    'unpowered_resident_ratio',
    'outage_event_id',
    'outage_state',
    'outage_requested_shed_ratio',
    'outage_realized_shed_ratio',
    'outage_total_work',
    'outage_work_done',
    'outage_progress',
    'opinion_pressure',
    'public_opinion_pressure',
    'opinion_pressure_decay',
    'opinion_pressure_net_change',
    'opinion_management_pressure_relief',
    'system_help_pressure',
    'system_help_emotion_component',
    'system_help_enterprise_component',
    'system_help_critical_component',
    'total_opinion_pressure',
    'public_opinion_active',
    'seir_S',
    'seir_E',
    'seir_I',
    'seir_R',
    'seir_infection_reduction',
    'rumor_suppress_rate',
    'avg_episode_outage_hours',
    'avg_cumulative_outage_hours',
    'avg_time_since_service_restoration',
    'decision_avg_region_psychological_pressure',
    'avg_region_psychological_pressure',
    'occupied_zone_mean_psychological_pressure',
    'service_restoration_ratio',
    'system_help_psychology_component',
}


def test_outage_stress_profiles_are_monotonic_and_bounded():
    times = [0, 2, 6, 12, 24, 48]
    for profile in ('sqrt', 'log', 'linear'):
        values = [
            unified_stress_model._base_outage_internal_stress(t, profile)
            for t in times
        ]
        assert all(0.0 <= value <= 1.0 for value in values)
        assert all(a <= b for a, b in zip(values, values[1:]))


def test_opinion_mode_override_only_touches_event5():
    gov = SimpleNamespace(
        public_opinion_active=True,
        emergency_warning_issued=True,
        resource_to_grid=True,
        resource_to_enterprise=True,
        resource_to_resident=True,
    )
    dummy = SimpleNamespace(
        gov_agents={'d0': gov},
        opinion_mode='off',
        _update_opinion_audit_state=lambda: None,
    )

    BlackoutSimulation._apply_opinion_mode_override(dummy)

    assert gov.public_opinion_active is False
    assert gov.emergency_warning_issued is True
    assert gov.resource_to_grid is True
    assert gov.resource_to_enterprise is True
    assert gov.resource_to_resident is True

    dummy.opinion_mode = 'on'
    BlackoutSimulation._apply_opinion_mode_override(dummy)
    assert gov.public_opinion_active is True


def test_global_metric_fields_include_validation_channels():
    assert REQUIRED_FIELDS.issubset(set(GLOBAL_METRIC_FIELDS))


def test_collect_step_metrics_exports_validation_channels():
    residents = [
        SimpleNamespace(
            stress_level=0.5,
            emotion=0.2,
            panic_value=0.3,
            is_hoarding=False,
            _herd_active=False,
            _edge_congestion=0.0,
            current_edge=None,
            _dom_action='home',
            state='S',
            zone='z0',
        ),
        SimpleNamespace(
            stress_level=0.8,
            emotion=0.4,
            panic_value=0.6,
            is_hoarding=True,
            _herd_active=True,
            _edge_congestion=0.2,
            current_edge=('a', 'b', 0),
            _dom_action='flee',
            state='I',
            zone='z0',
        ),
    ]
    sim = SimpleNamespace(
        residents=residents,
        zone_status={'z0': False, 'z1': True},
        event_influence=SimpleNamespace(opinion_pressure=0.25),
        public_opinion_pressure=0.17,
        P_hist=[0.60],
        opinion_components={'emotion': 0.10, 'enterprise': 0.20, 'critical': 0.30},
        region_psychological_pressure_levels={'z0': 0.30, 'z1': 0.0},
        gov_agents={'d0': SimpleNamespace(public_opinion_active=True)},
        last_event_summary={
            'total_opinion_pressure': 0.12,
            'opinion_pressure_decay': 0.01,
            'opinion_pressure_net_change': -0.02,
            'opinion_management_pressure_relief': 0.03,
        },
        last_event_effects={
            'government': {
                'opinion_manage': {
                    'seir_infection_reduction': 0.03,
                    'rumor_suppress_rate': 0.04,
                }
            }
        },
    )

    metrics = _collect_step_metrics(sim)

    assert REQUIRED_FIELDS.issubset(metrics)
    assert metrics['public_opinion_active'] == 1.0
    assert metrics['metric_schema_version'] == 4.0
    assert metrics['metric_phase'] == 'end_of_step'
    assert metrics['psychology_semantics'] == 'strict'
    assert metrics['outage_ratio'] == 0.5
    assert metrics['full_outage_zone_ratio'] == 0.5
    assert metrics['unpowered_resident_ratio'] == 0.0
    assert metrics['outage_state'] == 'normal'
    assert metrics['opinion_pressure'] == 0.25
    assert metrics['public_opinion_pressure'] == 0.17
    assert metrics['opinion_pressure_decay'] == 0.01
    assert metrics['opinion_pressure_net_change'] == -0.02
    assert metrics['opinion_management_pressure_relief'] == 0.03
    assert metrics['total_opinion_pressure'] == 0.12
    assert metrics['system_help_pressure'] == 0.60
    assert metrics['system_help_psychology_component'] == 0.10
    assert metrics['system_help_emotion_component'] == 0.10
    assert metrics['pts_ratio'] == 0.0
    assert metrics['avg_region_psychological_pressure'] == 0.30
    assert metrics['decision_avg_region_psychological_pressure'] == 0.30
    assert metrics['occupied_zone_mean_psychological_pressure'] == 0.30
    assert metrics['avg_region_psychological_pressure'] == pytest.approx(
        0.4 * metrics['avg_emotion']
        + 0.4 * metrics['avg_panic']
        + 0.2 * metrics['pts_ratio']
    )
    assert metrics['system_help_enterprise_component'] == 0.20
    assert metrics['system_help_critical_component'] == 0.30
    assert metrics['seir_S'] == 0.5
    assert metrics['seir_I'] == 0.5
    assert metrics['seir_infection_reduction'] == 0.03
    assert metrics['rumor_suppress_rate'] == 0.04
