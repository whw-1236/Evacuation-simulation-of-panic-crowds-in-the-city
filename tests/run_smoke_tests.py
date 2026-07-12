# -*- coding: utf-8 -*-
"""Run core smoke checks without requiring pytest."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    flee = load_module("test_flee_smoke", ROOT / "tests" / "test_flee.py")
    flee.run_checks()

    e2 = load_module("test_e2_switch_audit_smoke", ROOT / "tests" / "test_e2_switch_audit.py")
    e2.test_all_e2_presets_apply_to_all_switchparams()
    e2.test_switch_read_audit_is_aggregated()
    print("[OK] E2 switch audit smoke checks passed")

    lit = load_module(
        "test_literature_validation_controls_smoke",
        ROOT / "tests" / "test_literature_validation_controls.py",
    )
    lit.test_outage_stress_profiles_are_monotonic_and_bounded()
    lit.test_opinion_mode_override_only_touches_event5()
    lit.test_global_metric_fields_include_validation_channels()
    lit.test_collect_step_metrics_exports_validation_channels()
    print("[OK] Literature validation control smoke checks passed")

    interventions = load_module(
        "test_government_intervention_controls_smoke",
        ROOT / "tests" / "test_government_intervention_controls.py",
    )
    interventions.test_manual_on_for_one_event_keeps_other_events_automatic()
    interventions.test_manual_resource_to_enterprise_runs_compensation_route()
    interventions.test_public_opinion_state_decays_and_management_relief_is_exported()
    interventions.test_event_context_ignores_inactive_resource_amounts()
    print("[OK] Government intervention control smoke checks passed")

    outage = load_module(
        "test_outage_state_machine_smoke",
        ROOT / "tests" / "test_outage_state_machine.py",
    )
    outage.run_checks()

    print("[OK] All smoke checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
