# -*- coding: utf-8 -*-
"""Smoke checks for E2 SwitchParams override/audit plumbing."""

from types import SimpleNamespace

from core.behavior_switching import SwitchParams
from scripts.run_ablation import (
    SWITCH_ABLATION_OVERRIDES,
    _apply_switch_overrides,
    _collect_switch_audit,
    _switch_param_targets,
)


def _dummy_sim(n_residents=4):
    fc = SimpleNamespace(sw=SwitchParams())
    residents = [SimpleNamespace(sw=SwitchParams()) for _ in range(n_residents)]
    return SimpleNamespace(force_calculator=fc, residents=residents)


def test_all_e2_presets_apply_to_all_switchparams():
    for preset, overrides in SWITCH_ABLATION_OVERRIDES.items():
        sim = _dummy_sim()
        holders = len(_switch_param_targets(sim))
        audit = _apply_switch_overrides(sim, overrides, f"test:{preset}")

        assert audit["holders"] == (0 if preset == "none" else holders)
        for field, value in overrides.items():
            assert audit["applied_counts"][field] == holders
            assert audit["missing_counts"].get(field, 0) == 0
            for sw in _switch_param_targets(sim):
                assert getattr(sw, field) == value


def test_switch_read_audit_is_aggregated():
    sim = _dummy_sim(n_residents=2)
    targets = _switch_param_targets(sim)
    targets[0]._audit_reads = {"compute_goal_direction.use_mml": 3}
    targets[1]._audit_reads = {"compute_goal_direction.use_mml": 2}

    audit = _collect_switch_audit(sim)

    assert audit["holders"] == 3
    assert audit["read_counts"]["compute_goal_direction.use_mml"] == 5
    assert audit["field_values"]["use_mml"]["True"] == 3
