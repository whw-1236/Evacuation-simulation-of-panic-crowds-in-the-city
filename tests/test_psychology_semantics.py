# -*- coding: utf-8 -*-
"""Regression contracts for strict/legacy psychology semantics."""
from __future__ import annotations

import math
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


pytest.importorskip('shapely')

from core.agents import GovernmentAgent, ResidentAgent
from core.behavior_switching import (
    SwitchParams,
    calculate_outcome_feedback_delta,
)
from core.event_influence import EventInfluenceCalculator
from core.region_manager import GeoJSONRegionManager
from core.unified_stress_model import unified_stress_model
from simulation.simulation import BlackoutSimulation


def _resident():
    resident = ResidentAgent(seir_type='S')
    resident.psychology_semantics = 'strict'
    resident.zone = 'z0'
    return resident


def test_strict_observables_have_one_derived_formula():
    resident = _resident()
    resident.stress_level = 0.64
    resident._internal_stress = 1.0
    resident._tolerance = 0.0

    resident._derive_psychological_observables(0.25)

    observables = resident._psychology_observables
    assert resident.panic_value == pytest.approx(0.64 ** 0.8)
    assert resident.emotion == pytest.approx(0.64 * observables['emotion_envelope'])
    assert observables['panic'] == pytest.approx(resident.panic_value)
    assert observables['emotion'] == pytest.approx(resident.emotion)


def test_strict_step_projects_observables_after_the_stress_update():
    resident = _resident()
    resident.powered = False

    resident.step(
        dt=0.25,
        social_force=(0.0, 0.0),
        gov_resource=0.0,
        region_panic_level=0.0,
        hazard_positions=[],
        time_factors=None,
        sim_time=0.0,
    )

    assert resident.panic_value == pytest.approx(resident.stress_level ** 0.8)
    assert resident.emotion == pytest.approx(resident._psychology_observables['emotion'])


def test_strict_step_evaluates_observation_map_once_with_full_dt():
    resident = _resident()
    resident.powered = False
    calls = []
    original = resident._derive_psychological_observables

    def record(dt):
        calls.append(dt)
        return original(dt)

    resident._derive_psychological_observables = record
    resident.step(
        dt=0.25,
        social_force=(0.0, 0.0),
        gov_resource=0.0,
        region_panic_level=0.0,
        hazard_positions=[],
        time_factors=None,
        sim_time=0.0,
    )

    assert calls == pytest.approx([0.25])


def test_strict_outage_clocks_reset_only_the_episode():
    resident = _resident()
    resident.powered = False
    resident._advance_strict_service_time_state(1.0)
    assert resident.episode_outage_hours == pytest.approx(1.0)
    assert resident.cumulative_outage_hours == pytest.approx(1.0)
    assert resident.time_since_service_restoration == pytest.approx(0.0)

    resident.powered = True
    resident._advance_strict_service_time_state(1.0)
    assert resident.episode_outage_hours == pytest.approx(1.0)
    assert resident.cumulative_outage_hours == pytest.approx(1.0)
    assert resident.time_since_service_restoration == pytest.approx(0.0)

    resident._advance_strict_service_time_state(1.0)
    assert resident.time_since_service_restoration == pytest.approx(1.0)

    resident.powered = False
    resident._advance_strict_service_time_state(1.0)
    assert resident.episode_outage_hours == pytest.approx(1.0)
    assert resident.cumulative_outage_hours == pytest.approx(2.0)
    assert resident.time_since_service_restoration == pytest.approx(0.0)
    assert resident.t_outage == pytest.approx(resident.episode_outage_hours)
    assert resident.total_outage_hours == pytest.approx(resident.cumulative_outage_hours)


def test_restoration_clock_keeps_advancing_after_recovery_phase_ends():
    resident = _resident()
    resident.powered = False
    resident._advance_strict_service_time_state(1.0)
    resident.powered = True
    resident._advance_strict_service_time_state(1.0)
    resident._advance_strict_service_time_state(1.0)
    resident.recovery_phase = False
    resident._advance_strict_service_time_state(1.0)

    assert resident.time_since_service_restoration == pytest.approx(2.0)


def test_strict_event_layer_never_applies_fixed_ep_relief_jump():
    resident = SimpleNamespace(
        emotion=0.90,
        panic_value=0.80,
        info_received={'official': 0.0},
        rumor_belief=0.0,
        personal_supply=0.20,
        is_hoarding=False,
        _opinion_management_active=False,
        neighbors=[],
        state='S',
    )
    sim = SimpleNamespace(psychology_semantics='strict', residents=[resident], enterprises=[])
    effects = {'summary': {'total_panic_change': -0.5, 'total_emotion_change': -0.5},
               'government': {}, 'resident': {}}

    EventInfluenceCalculator().apply_effects(sim, effects, 0.25)

    assert resident.emotion == pytest.approx(0.90)
    assert resident.panic_value == pytest.approx(0.80)
    assert effects['summary']['direct_emotion_panic_write'] is False


def test_legacy_keeps_the_historical_direct_event_write_path():
    resident = SimpleNamespace(
        emotion=0.50,
        panic_value=0.50,
        info_received={'official': 0.0},
        rumor_belief=0.0,
        _opinion_management_active=False,
        neighbors=[],
        state='S',
    )
    sim = SimpleNamespace(psychology_semantics='legacy', residents=[resident], enterprises=[])
    effects = {'summary': {'total_panic_change': 0.2, 'total_emotion_change': 0.2},
               'government': {}, 'resident': {}}

    EventInfluenceCalculator().apply_effects(sim, effects, 0.25)

    assert resident.emotion == pytest.approx(0.52)
    assert resident.panic_value == pytest.approx(0.52)


def test_strict_stress_ode_ignores_legacy_direct_event_corrections():
    resident = _resident()
    resident.powered = False
    resident.episode_outage_hours = 2.0
    resident.cumulative_outage_hours = 2.0
    resident.stress_level = 0.4
    resident._pending_stress_reappraisal = 0.0
    resident._gov_events = {
        'outage_notice': True,
        'emergency_response': True,
        'supply_distribution': True,
        'psychological_comfort': True,
    }
    resident._grid_events = {'temp_station': True, 'accelerated_repair': True}
    resident.is_hoarding = True
    resident.hoarding_success = True
    resident.is_self_helping = True
    resident.is_requesting_power = True

    _, strict_components = unified_stress_model.calculate_stress_change(
        resident, gov_resource=0.0, zone_data={}, dt=0.25
    )
    assert strict_components['event_effect'] == pytest.approx(0.0)

    resident.psychology_semantics = 'legacy'
    _, legacy_components = unified_stress_model.calculate_stress_change(
        resident, gov_resource=0.0, zone_data={}, dt=0.25
    )
    assert legacy_components['event_effect'] < 0.0


def test_restoration_term_uses_both_cumulative_and_restoration_time():
    resident = _resident()
    resident.powered = True
    resident.recovery_phase = True
    resident.stress_level = 0.5
    resident.peak_stress = 0.8
    resident.episode_outage_hours = 12.0
    resident.cumulative_outage_hours = 12.0
    resident._pending_stress_reappraisal = 0.0

    resident.time_since_service_restoration = 0.0
    _, early = unified_stress_model.calculate_stress_change(
        resident, gov_resource=0.0, zone_data={}, dt=0.25
    )
    resident.time_since_service_restoration = 6.0
    _, late = unified_stress_model.calculate_stress_change(
        resident, gov_resource=0.0, zone_data={}, dt=0.25
    )

    assert early['restoration'] < 0.0
    assert abs(early['restoration']) > abs(late['restoration'])

    resident.psychology_semantics = 'legacy'
    resident.t_outage = 12.0
    resident.total_outage_hours = 12.0
    resident.time_since_recovery = 0.0
    _, legacy_early = unified_stress_model.calculate_stress_change(
        resident, gov_resource=0.0, zone_data={}, dt=0.25
    )
    resident.time_since_recovery = 6.0
    _, legacy_late = unified_stress_model.calculate_stress_change(
        resident, gov_resource=0.0, zone_data={}, dt=0.25
    )
    assert legacy_early['restoration'] == pytest.approx(
        legacy_late['restoration']
    )


def test_strict_reappraisal_is_consumed_exactly_once():
    resident = _resident()
    resident.powered = False
    resident.episode_outage_hours = 2.0
    resident.cumulative_outage_hours = 2.0
    resident._pending_stress_reappraisal = 0.12

    _, first = unified_stress_model.calculate_stress_change(
        resident, gov_resource=0.0, zone_data={}, dt=0.25
    )
    _, second = unified_stress_model.calculate_stress_change(
        resident, gov_resource=0.0, zone_data={}, dt=0.25
    )

    assert first['reappraisal'] == pytest.approx(0.12)
    assert resident._pending_stress_reappraisal == pytest.approx(0.0)
    assert second['reappraisal'] == pytest.approx(0.0)


def test_strict_outcome_reappraisal_is_bounded_without_changing_legacy_delta():
    params = SwitchParams(feedback_max_abs=0.15)
    agent = SimpleNamespace(
        is_hoarding=True,
        just_hoarded=False,
        hoarding_success=False,
        hoarding_failures=20,
        _last_hoarding_failed_recorded=-1,
        _herd_active=False,
        current_leader=None,
        _edge_congestion=1.0,
    )

    bounded = calculate_outcome_feedback_delta(agent, params, bounded=True)
    agent._last_hoarding_failed_recorded = -1
    legacy = calculate_outcome_feedback_delta(agent, params, bounded=False)

    assert bounded == pytest.approx(0.15)
    assert legacy > bounded


def test_pts_hysteresis_thresholds_are_personality_only():
    neighbors = [
        SimpleNamespace(
            is_hoarding=True, _herd_active=True, is_emotion_burst=True
        )
    ]
    resident = SimpleNamespace(
        personality='普通型',
        pts_status=False,
        powered=False,
        neighbors=neighbors,
        agreeableness=1.0,
        sw=SwitchParams(enable_behavior_demo=True),
    )

    unified_stress_model._update_behavior_states(resident, 0.79)
    assert resident.pts_status is False
    assert resident._pts_enter_threshold == pytest.approx(0.8)
    assert resident._pts_exit_threshold == pytest.approx(0.5)

    unified_stress_model._update_behavior_states(resident, 0.81)
    assert resident.pts_status is True
    unified_stress_model._update_behavior_states(resident, 0.49)
    assert resident.pts_status is False


@pytest.mark.parametrize(
    ('personality', 'expected_enter', 'expected_exit'),
    [
        ('焦虑型', 0.56, 0.35),
        ('敏感型', 0.68, 0.425),
        ('普通型', 0.80, 0.50),
        ('稳定型', 0.92, 0.575),
        ('理性型', 0.95, 0.65),
    ],
)
def test_pts_thresholds_cover_all_personalities_and_cap(
        personality, expected_enter, expected_exit):
    resident = SimpleNamespace(
        personality=personality,
        pts_status=False,
        powered=False,
        neighbors=[],
        sw=SwitchParams(enable_behavior_demo=False),
    )

    unified_stress_model._update_behavior_states(resident, 0.0)

    assert resident._pts_enter_threshold == pytest.approx(expected_enter)
    assert resident._pts_exit_threshold == pytest.approx(expected_exit)


def test_strict_government_pressure_uses_az_once():
    low_max = GovernmentAgent(w_L=0.0, w_E=1.0, w_Q=0.0, w_C=0.0)
    high_max = GovernmentAgent(w_L=0.0, w_E=1.0, w_Q=0.0, w_C=0.0)

    low_max.decide(
        0.0, 0.4, 0.0, 0.0, {'z0': 0.1},
        psychology_semantics='strict',
    )
    high_max.decide(
        0.0, 0.4, 0.0, 0.0, {'z0': 0.9},
        psychology_semantics='strict',
    )

    assert low_max.pressure_index == pytest.approx(0.4)
    assert high_max.pressure_index == pytest.approx(0.4)


def test_strict_event5_cannot_override_az_with_legacy_opinion_state():
    low_state = GovernmentAgent(w_L=0.0, w_E=1.0, w_Q=0.0, w_C=0.0)
    high_state = GovernmentAgent(w_L=0.0, w_E=1.0, w_Q=0.0, w_C=0.0)
    low_state.set_public_opinion_pressure(0.1)
    high_state.set_public_opinion_pressure(0.9)

    for government in (low_state, high_state):
        government.decide(
            0.0, 0.4, 0.0, 0.0, {'z0': 0.4},
            psychology_semantics='strict',
        )

    assert low_state.last_opinion_pressure == pytest.approx(0.4)
    assert high_state.last_opinion_pressure == pytest.approx(0.4)
    assert low_state.public_opinion_active == high_state.public_opinion_active


def test_strict_resident_resource_trigger_uses_az_not_raw_emotion():
    resident = SimpleNamespace(zone='z0', emotion=0.95, powered=True)
    strict_gov = GovernmentAgent()
    legacy_gov = GovernmentAgent()

    strict_gov.allocate_resources(
        [], 10.0, {'z0': 0.0}, [resident],
        psychology_semantics='strict',
    )
    legacy_gov.allocate_resources(
        [], 10.0, {'z0': 0.0}, [resident],
        psychology_semantics='legacy',
    )

    assert strict_gov.resource_to_resident is False
    assert legacy_gov.resource_to_resident is True


def test_adjacent_az_enters_one_bounded_strict_threat_channel_only():
    resident = _resident()
    resident.powered = True
    resident.episode_outage_hours = 0.0
    resident.cumulative_outage_hours = 0.0
    resident.personal_supply = 1.0
    resident.neighbors = []
    resident._event_social_exposure = 0.0
    resident.adjacent_zone_panic = 0.0
    emotion_before = resident.emotion
    panic_before = resident.panic_value

    low = unified_stress_model.calculate_threat_perception(
        resident, zone_data={}, dt=0.25
    )
    resident.adjacent_zone_panic = 1.0
    high = unified_stress_model.calculate_threat_perception(
        resident, zone_data={}, dt=0.25
    )

    assert high > low
    assert 0.0 <= high <= 1.0
    assert resident.emotion == pytest.approx(emotion_before)
    assert resident.panic_value == pytest.approx(panic_before)

    resident.psychology_semantics = 'legacy'
    legacy_high = unified_stress_model.calculate_threat_perception(
        resident, zone_data={}, dt=0.25
    )
    resident.adjacent_zone_panic = 0.0
    legacy_low = unified_stress_model.calculate_threat_perception(
        resident, zone_data={}, dt=0.25
    )
    assert legacy_high == pytest.approx(legacy_low)


def test_region_manager_keeps_legacy_api_separate_from_named_az():
    manager = GeoJSONRegionManager.__new__(GeoJSONRegionManager)
    residents = [
        SimpleNamespace(zone='z0', emotion=0.2, panic_value=0.9, pts_status=True),
        SimpleNamespace(zone='z0', emotion=0.4, panic_value=0.1, pts_status=False),
    ]

    legacy = manager.get_region_panic_level(residents, 'z0')
    canonical = manager.get_region_psychological_pressure(residents, 'z0')

    assert legacy == pytest.approx(0.7 * 0.3)
    assert canonical == pytest.approx(0.4 * 0.3 + 0.4 * 0.5 + 0.2 * 0.5)


def test_named_az_history_is_not_the_legacy_panic_history_object():
    sim = BlackoutSimulation.__new__(BlackoutSimulation)
    sim._init_history()

    assert sim.region_psychological_pressure_hist is not sim.region_panic_hist


def test_region_panic_alias_is_the_canonical_psychological_pressure():
    residents = [
        SimpleNamespace(zone='z0', emotion=0.20, panic_value=0.40, pts_status=False),
        SimpleNamespace(zone='z0', emotion=0.60, panic_value=0.80, pts_status=True),
    ]
    sim = BlackoutSimulation.__new__(BlackoutSimulation)
    sim.residents = residents
    sim.region_manager = SimpleNamespace(regions={'z0': {}})

    levels = sim.calculate_region_panic_levels()

    expected = 0.4 * 0.40 + 0.4 * 0.60 + 0.2 * 0.50
    assert levels['z0'] == pytest.approx(expected)
    assert sim.region_panic_levels['z0'] == pytest.approx(expected)
    assert sim.region_psychological_pressure_levels['z0'] == pytest.approx(expected)


def test_legacy_replay_keeps_historical_region_panic_but_exports_az():
    residents = [
        SimpleNamespace(zone='z0', emotion=0.20, panic_value=0.40, pts_status=False),
        SimpleNamespace(zone='z0', emotion=0.80, panic_value=0.80, pts_status=True),
    ]
    sim = BlackoutSimulation.__new__(BlackoutSimulation)
    sim.psychology_semantics = 'legacy'
    sim.residents = residents
    sim.region_manager = SimpleNamespace(regions={'z0': {}})

    legacy_levels = sim.calculate_region_panic_levels()

    assert legacy_levels['z0'] == pytest.approx(0.7 * 0.50 + 0.3 * 0.50)
    assert sim.region_psychological_pressure_levels['z0'] == pytest.approx(
        0.4 * 0.50 + 0.4 * 0.60 + 0.2 * 0.50
    )
