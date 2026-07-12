# -*- coding: utf-8 -*-
"""Focused contract tests for the district outage state machine.

These tests deliberately use a tiny in-memory simulation fixture instead of a
city GeoJSON.  The outage API must therefore be usable with the model's live
state only; it must not depend on UI code, a particular city, or an absolute
simulation step.  This is important for headless IJDRR experiment runs.
"""

from __future__ import annotations

import math
import random
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# The project runtime (rather than the workstation's base Python) supplies
# geospatial dependencies used while importing BlackoutSimulation.
pytest.importorskip("shapely")

from config.config import Config
from core.event_recorder import EventDetector, EventRecorder
from core.event_types import GRID_RESTORE
from simulation.simulation import BlackoutSimulation, DistrictOutageState


DISTRICT = "test-district"
ZONE = "zone-0"


def _entity(identifier: str, zone: str = ZONE):
    """Return the minimum resident/enterprise shape used by outage routing."""
    return SimpleNamespace(
        id=identifier,
        zone=zone,
        powered=True,
        _is_load_shed=False,
    )


def _make_simulation(*, dt: float = 1.0) -> BlackoutSimulation:
    """Build a deterministic one-zone fixture without loading map files.

    The lower-priority population is intentionally large enough that a 50%
    partial outage can be realised without shedding the level-1 hospital.
    The elevated repair capacity keeps recovery checks short while retaining
    the production work equation and detection phase.
    """
    sim = BlackoutSimulation.__new__(BlackoutSimulation)
    config = Config()
    # Instance overrides leave global configuration untouched and reduce this
    # test to a few simulated hours.
    config.grid_repair.BASE_REPAIR_CAPACITY = 100.0
    sim.config = config
    sim.dt = float(dt)
    sim.step_count = 0
    sim.t = 0
    sim.random_seed = 42
    sim._outage_rng = random.Random(sim.random_seed)
    sim._outage_event_counter = 0

    sim.district_name = DISTRICT
    sim.district_to_zones = {DISTRICT: [ZONE]}
    sim.zone_to_district = {ZONE: DISTRICT}
    sim.zone_status = {ZONE: True}
    sim.zone_power_fraction = {ZONE: 1.0}
    sim.zone_duration = {ZONE: 0.0}
    sim.zone_outage_cause = {}
    sim.zone_load_levels = {ZONE: 3}
    sim.zone_load_stats = {ZONE: {1: 1, 2: 0, 3: 12}}
    sim.partial_outage_entities = {}
    sim.fault_severity = {}
    sim.fault_detection_time = {}
    sim.fault_ready_for_repair = {}
    sim.recovered_zones = set()
    sim._just_restored_zones = []

    sim.residents = [_entity(f"resident-{idx}") for idx in range(10)]
    sim.enterprises = [_entity(f"enterprise-{idx}") for idx in range(2)]
    sim.csv_nodes = [
        {
            "id": "hospital-0",
            "zone": ZONE,
            "category": "hospital",
            "powered": True,
        },
    ]
    sim.region_manager = SimpleNamespace(
        regions={ZONE: {}},
        region_neighbors={ZONE: []},
    )

    sim.grid = SimpleNamespace(
        current_resource_level=100.0,
        initiative=1.0,
        response=1.0,
        manual_repair=False,
        ongoing_repairs={},
        is_repairing=False,
        calculate_repair_capacity=lambda _config: 100.0,
    )
    sim.gov_agents = {}
    sim.gov = SimpleNamespace()
    sim.recovery_allowed = True
    sim.district_powered = True
    sim.district_recovered = False
    sim.district_outage_mode = None
    sim.district_outage_cause = None
    sim.district_repair_started = False
    sim.district_repair_progress = 0.0
    sim.district_total_work = 0.0
    sim.district_fault_detection_time = 0.0
    sim.district_fault_ready = False
    sim.district_outage_states = {}
    return sim


def _state(sim: BlackoutSimulation, district: str = DISTRICT) -> DistrictOutageState:
    """Read the public, authoritative per-district state store."""
    assert isinstance(getattr(sim, "district_outage_states", None), dict), (
        "the outage state machine must expose sim.district_outage_states"
    )
    state = sim.district_outage_states.get(district)
    assert isinstance(state, DistrictOutageState)
    return state


def _selection_signature(state: DistrictOutageState):
    return [
        (load.kind, load.zone_id, load.level, load.ordinal)
        for load in state.affected_loads
    ]


def _advance_until_restored(sim: BlackoutSimulation, limit: int = 20) -> DistrictOutageState:
    """Advance only the outage state machine, recording its progress path."""
    state = _state(sim)
    progress = [state.progress]
    for _ in range(limit):
        sim.step_count += 1
        sim.zone_recover()
        state = _state(sim)
        progress.append(state.progress)
        if state.status == "restored":
            break

    assert all(
        after + 1e-12 >= before
        for before, after in zip(progress, progress[1:])
    ), f"repair progress must be monotonic, got {progress!r}"
    assert all(0.0 <= value <= 1.0 for value in progress)
    assert state.status == "restored", (
        f"high-capacity equipment failure should recover within {limit} steps; "
        f"last state={state.to_audit_dict()}"
    )
    return state


def test_trigger_creates_auditable_repair_state():
    sim = _make_simulation()

    state = sim.trigger_outage_scenario(
        DISTRICT,
        mode="full",
        cause="equipment_failure",
        shed_ratio=1.0,
        seed=7,
    )

    assert isinstance(state, DistrictOutageState)
    assert state is _state(sim)
    assert state.status in {"active", "detecting", "mobilizing", "repairing"}
    assert state.event_id
    assert state.total_work > 0.0
    assert state.work_done == 0.0
    assert state.detection_remaining_hours >= 0.0
    assert state.affected_loads
    assert state.affected_zone_ids == [ZONE]

    audit = sim.get_outage_state(DISTRICT)
    assert audit["event_id"] == state.event_id
    assert audit["total_work"] == state.total_work
    assert audit["affected_load_count"] == len(state.affected_loads)
    assert "eta_hours" in audit
    assert not math.isnan(float(audit["eta_hours"]))


def test_zero_shed_is_a_transactional_noop_and_repeat_is_rejected():
    sim = _make_simulation()

    no_op = sim.trigger_outage_scenario(
        DISTRICT,
        mode="partial",
        cause="equipment_failure",
        shed_ratio=0.0,
        seed=3,
    )
    assert no_op is None
    assert sim.district_outage_states == {}
    assert sim.zone_status[ZONE] is True
    assert sim.zone_power_fraction[ZONE] == 1.0

    first = sim.trigger_outage_scenario(
        DISTRICT,
        mode="partial",
        cause="equipment_failure",
        shed_ratio=0.5,
        seed=3,
    )
    before = (
        first.event_id,
        first.total_work,
        sim.zone_power_fraction[ZONE],
        _selection_signature(first),
    )
    with pytest.raises(RuntimeError, match="active outage"):
        sim.trigger_outage_scenario(
            DISTRICT,
            mode="full",
            cause="natural_disaster",
            shed_ratio=1.0,
            seed=99,
        )

    assert _state(sim) is first
    assert (
        first.event_id,
        first.total_work,
        sim.zone_power_fraction[ZONE],
        _selection_signature(first),
    ) == before


def test_one_zone_partial_sheds_weighted_load_without_full_zone_blackout():
    sim = _make_simulation()

    state = sim.trigger_outage_scenario(
        DISTRICT,
        mode="partial",
        cause="equipment_failure",
        shed_ratio=0.5,
        seed=17,
    )

    assert state.mode == "partial"
    assert sim.zone_status[ZONE] is True, "one-zone partial outage must not become full blackout"
    assert 0.0 < sim.zone_power_fraction[ZONE] < 1.0
    assert 0.35 <= state.realized_shed_ratio <= 0.65
    assert state.affected_loads
    assert any(not resident.powered for resident in sim.residents)
    assert sim.csv_nodes[0]["powered"] is True, "level-1 hospital should remain supplied"

    # The simulation-level outage RNG must make the selected load set stable.
    again = _make_simulation()
    state_again = again.trigger_outage_scenario(
        DISTRICT,
        mode="partial",
        cause="equipment_failure",
        shed_ratio=0.5,
        seed=17,
    )
    assert _selection_signature(state_again) == _selection_signature(state)


def test_repair_is_monotonic_then_second_incident_is_allowed():
    sim = _make_simulation()
    first = sim.trigger_outage_scenario(
        DISTRICT,
        mode="full",
        cause="equipment_failure",
        shed_ratio=1.0,
        damage_level=1.0,
        seed=5,
    )
    restored = _advance_until_restored(sim)

    assert restored.event_id == first.event_id
    assert restored.restored_step is not None
    assert sim.zone_status[ZONE] is True
    assert sim.zone_power_fraction[ZONE] == 1.0
    assert not sim.zone_outage_cause
    assert not sim.grid.ongoing_repairs
    assert all(resident.powered for resident in sim.residents)
    assert all(enterprise.powered for enterprise in sim.enterprises)
    assert sim.outage_event_history[-1]['event_id'] == first.event_id
    assert sim.outage_event_history[-1]['completion_reason'] == 'automatic'

    second = sim.trigger_outage_scenario(
        DISTRICT,
        mode="full",
        cause="equipment_failure",
        shed_ratio=1.0,
        damage_level=1.0,
        seed=6,
    )
    assert isinstance(second, DistrictOutageState)
    assert second.event_id != first.event_id
    assert second.status != "restored"


def test_scheduled_outage_uses_duration_without_creating_physical_work():
    sim = _make_simulation(dt=1.0)
    state = sim.trigger_outage_scenario(
        DISTRICT,
        mode="partial",
        cause="planned_outage",
        shed_ratio=0.5,
        scheduled_duration_hours=2.0,
        seed=13,
    )

    assert state.status == "scheduled"
    assert state.total_work == 0.0
    assert state.scheduled_remaining_hours == 2.0

    sim.step_count += 1
    sim.zone_recover()
    assert state.status == "scheduled"
    assert state.scheduled_remaining_hours == 1.0
    assert state.current_capacity == 0.0

    sim.step_count += 1
    sim.zone_recover()
    assert state.status == "restored"
    assert sim.zone_power_fraction[ZONE] == 1.0
    assert not sim.grid.ongoing_repairs


def test_manual_repair_acceleration_changes_only_repair_capacity():
    def capacity_after_detection(manual_repair: bool) -> float:
        sim = _make_simulation(dt=0.25)
        sim.grid.manual_repair = manual_repair
        state = sim.trigger_outage_scenario(
            DISTRICT,
            mode="full",
            cause="equipment_failure",
            shed_ratio=1.0,
            damage_level=50.0,
            seed=23,
        )
        # Two 0.25 h steps complete a 0.5 h detection delay; the third is
        # the first repair step and exposes the current capacity.
        for _ in range(3):
            sim.step_count += 1
            sim.zone_recover()
        assert state.status == "repairing"
        return state.current_capacity

    baseline = capacity_after_detection(False)
    accelerated = capacity_after_detection(True)
    factor = getattr(
        Config().grid_repair, "ACCELERATED_REPAIR_MULTIPLIER", 1.5
    )
    assert accelerated == pytest.approx(baseline * factor)


@pytest.mark.parametrize("dt", [0.125, 0.25, 0.5])
def test_baseline_repair_matches_relative_detection_work_equation(dt):
    """No-intervention recovery follows the stated discrete-time equation.

    The fixture has a fixed 100 work-units/hour capacity and no government
    grid support.  This isolates the state machine from behavioural dynamics:
    N = ceil(t_detect / DT) + ceil(W / (C * DT)).
    """
    sim = _make_simulation(dt=dt)
    sim.grid.manual_repair = False
    state = sim.trigger_outage_scenario(
        DISTRICT,
        mode="full",
        cause="equipment_failure",
        shed_ratio=1.0,
        seed=31,
    )
    capacity = sim.grid.calculate_repair_capacity(sim.config)
    expected_steps = (
        math.ceil(state.detection_remaining_hours / dt)
        + math.ceil(state.total_work / (capacity * dt))
    )
    for _ in range(expected_steps):
        sim.step_count += 1
        sim.zone_recover()
    assert state.status == "restored"
    assert state.restored_step == expected_steps


def test_staged_full_recovery_records_one_restore_event():
    """A red-to-amber transition is not a duplicate final restoration event."""
    sim = _make_simulation(dt=1.0)
    sim.grid.calculate_repair_capacity = lambda _config: 10.0
    recorder = EventRecorder()
    detector = EventDetector(recorder)
    detector.prev_zone_status = sim.zone_status.copy()
    detector.prev_partial_zones = set()
    detector.prev_ongoing_repairs = set()

    state = sim.trigger_outage_scenario(
        DISTRICT,
        mode="full",
        cause="equipment_failure",
        shed_ratio=1.0,
        seed=37,
    )
    for step in range(20):
        recorder.set_step(step)
        detector._detect_grid_events(sim)
        detector.prev_zone_status = sim.zone_status.copy()
        detector.prev_ongoing_repairs = set(sim.grid.ongoing_repairs)
        sim.step_count += 1
        sim.zone_recover()
        if state.status == "restored":
            recorder.set_step(step + 1)
            detector._detect_grid_events(sim)
            break

    restores = [
        event for event in recorder.completed_events
        if event.event_id == GRID_RESTORE and event.zone_id == ZONE
    ]
    assert state.status == "restored"
    assert len(restores) == 1


def test_duplicate_raw_zone_ids_are_visible_preflight_warnings():
    sim = _make_simulation()
    # The loader canonicalises duplicate raw GeoJSON IDs.  They must remain
    # visible to QA, but must not make a real city UI unusable when the
    # canonical zone mapping is still internally consistent.
    # ``all_zone_ids`` is the raw loader sequence.  The regions dictionary
    # cannot preserve duplicate keys, so the preflight must inspect this list.
    sim.region_manager.all_zone_ids = [ZONE, ZONE]

    report = sim.validate_outage_preflight(DISTRICT)
    assert report["ok"] is True
    assert any(
        "duplicate" in str(message).lower() or "重复" in str(message)
        for message in report["warnings"]
    )

    state = sim.trigger_outage_scenario(
        DISTRICT,
        mode="partial",
        cause="equipment_failure",
        shed_ratio=0.5,
        seed=11,
    )
    assert isinstance(state, DistrictOutageState)
    assert state.affected_zone_ids == [ZONE]


def run_checks():
    """Allow the lightweight project smoke runner to invoke this module."""
    test_trigger_creates_auditable_repair_state()
    test_zero_shed_is_a_transactional_noop_and_repeat_is_rejected()
    test_one_zone_partial_sheds_weighted_load_without_full_zone_blackout()
    test_repair_is_monotonic_then_second_incident_is_allowed()
    test_scheduled_outage_uses_duration_without_creating_physical_work()
    test_manual_repair_acceleration_changes_only_repair_capacity()
    test_duplicate_raw_zone_ids_are_visible_preflight_warnings()
    print("[OK] Outage state-machine smoke checks passed")


if __name__ == "__main__":
    run_checks()
