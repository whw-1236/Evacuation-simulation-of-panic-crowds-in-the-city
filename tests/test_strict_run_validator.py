from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from scripts import validate_strict_run_contract as validator


CSV_FIELDS = [
    "metric_schema_version",
    "metric_phase",
    "psychology_semantics",
    "avg_stress",
    "avg_emotion",
    "avg_panic",
    "pts_ratio",
    "decision_avg_region_psychological_pressure",
    "avg_region_psychological_pressure",
    "occupied_zone_mean_psychological_pressure",
    "avg_episode_outage_hours",
    "avg_cumulative_outage_hours",
    "avg_time_since_service_restoration",
    "service_restoration_ratio",
]


def _row(
    *,
    emotion: float,
    panic: float,
    pts: float,
    cumulative: float,
    restoration: float,
    restored_ratio: float,
) -> dict[str, object]:
    regional_pressure = 0.4 * emotion + 0.4 * panic + 0.2 * pts
    return {
        "metric_schema_version": 4,
        "metric_phase": "end_of_step",
        "psychology_semantics": "strict",
        "avg_stress": 0.3,
        "avg_emotion": emotion,
        "avg_panic": panic,
        "pts_ratio": pts,
        "decision_avg_region_psychological_pressure": regional_pressure,
        "avg_region_psychological_pressure": regional_pressure,
        # A mechanism-specific diagnostic may be unavailable without
        # invalidating the required strict contract fields.
        "occupied_zone_mean_psychological_pressure": "",
        "avg_episode_outage_hours": cumulative,
        "avg_cumulative_outage_hours": cumulative,
        "avg_time_since_service_restoration": restoration,
        "service_restoration_ratio": restored_ratio,
    }


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _manifest(graph_mode: str) -> dict[str, object]:
    return {
        "model_contract_version": validator.MODEL_CONTRACT_VERSION,
        "metric_schema_version": validator.MIN_METRIC_SCHEMA_VERSION,
        "city": "厦门市",
        "district": "思明区",
        "seed": 42,
        "n_residents": 20,
        "n_enterprises": 2,
        "total_steps": 7,
        "dt": 0.25,
        "outage_step": 1,
        "outage_cause": "equipment_failure",
        "tag": "validator_test",
        "use_mml": True,
        "switch_ablation": "none",
        "opinion_mode": "auto",
        "outage_stress_profile": "sqrt",
        "psychology_semantics": "strict",
        "home_distribution": "poi",
        "flee_threshold": None,
        "mml_overrides": {
            "mml_scale": None,
            "mml_asc_flee": None,
            "mml_b_sigma_flee": None,
            "mml_b_vis": None,
        },
        "psychology_contract": {"master_state": "stress_level"},
        "phase_contract": {
            "government_decision": "start_of_step",
            "global_metrics": "end_of_step",
            "decision_pressure_field": (
                "decision_avg_region_psychological_pressure"
            ),
        },
        "graph_mode": graph_mode,
        "use_road_graph": graph_mode == "on",
        "config_sha256": f"config-{graph_mode}",
        "git": {
            "commit": "deadbeef",
            "worktree_fingerprint_sha256": "same-fingerprint",
        },
    }


def _make_valid_run(tmp_path: Path) -> Path:
    run_dir = tmp_path / "t15_valid"
    rows = [
        # Initial all-powered baseline must not start a recovery episode.
        _row(
            emotion=0.10,
            panic=0.20,
            pts=0.00,
            cumulative=0.00,
            restoration=0.00,
            restored_ratio=1.00,
        ),
        _row(
            emotion=0.20,
            panic=0.30,
            pts=0.00,
            cumulative=0.25,
            restoration=0.00,
            restored_ratio=0.50,
        ),
        _row(
            emotion=0.25,
            panic=0.35,
            pts=0.10,
            cumulative=0.50,
            restoration=0.00,
            restored_ratio=1.00,
        ),
        _row(
            emotion=0.20,
            panic=0.30,
            pts=0.10,
            cumulative=0.50,
            restoration=0.25,
            restored_ratio=1.00,
        ),
        # A re-outage may reset the recovery clock.
        _row(
            emotion=0.30,
            panic=0.40,
            pts=0.20,
            cumulative=0.75,
            restoration=0.00,
            restored_ratio=0.50,
        ),
        _row(
            emotion=0.25,
            panic=0.35,
            pts=0.10,
            cumulative=1.00,
            restoration=0.00,
            restored_ratio=1.00,
        ),
        _row(
            emotion=0.20,
            panic=0.30,
            pts=0.00,
            cumulative=1.00,
            restoration=0.25,
            restored_ratio=1.00,
        ),
    ]
    for graph_mode in validator.GRAPH_MODES:
        graph_dir = run_dir / f"graph_{graph_mode}"
        graph_dir.mkdir(parents=True)
        (graph_dir / "manifest.json").write_text(
            json.dumps(_manifest(graph_mode), ensure_ascii=False),
            encoding="utf-8",
        )
        _write_csv(graph_dir / "global_metrics.csv", rows)

    contract = _manifest("off")
    summary = {
        "model_contract_version": validator.MODEL_CONTRACT_VERSION,
        "metric_schema_version": validator.MIN_METRIC_SCHEMA_VERSION,
        "config": {
            key: contract[key]
            for key in validator.PAIR_KEYS
        },
    }
    (run_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False), encoding="utf-8"
    )
    return run_dir


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_minimal_strict_run_passes_with_optional_numeric_blanks(tmp_path: Path):
    report = validator.validate_run_dir(_make_valid_run(tmp_path))

    assert report["ok"] is True
    assert report["issues"] == []


def test_missing_semantics_fails(tmp_path: Path):
    run_dir = _make_valid_run(tmp_path)
    summary_path = run_dir / "summary.json"
    summary = _read_json(summary_path)
    del summary["config"]["psychology_semantics"]
    summary_path.write_text(json.dumps(summary), encoding="utf-8")

    report = validator.validate_run_dir(run_dir)

    assert report["ok"] is False
    assert "summary psychology_semantics mismatch" in report["issues"]


@pytest.mark.parametrize("location", ["summary", "csv"])
def test_old_schema_fails(tmp_path: Path, location: str):
    run_dir = _make_valid_run(tmp_path)
    if location == "summary":
        summary_path = run_dir / "summary.json"
        summary = _read_json(summary_path)
        summary["metric_schema_version"] = 3
        summary_path.write_text(json.dumps(summary), encoding="utf-8")
    else:
        csv_path = run_dir / "graph_off" / "global_metrics.csv"
        with csv_path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        rows[0]["metric_schema_version"] = "3"
        _write_csv(csv_path, rows)

    report = validator.validate_run_dir(run_dir)

    assert report["ok"] is False
    assert any("metric_schema_version" in issue for issue in report["issues"])


def test_az_identity_error_fails(tmp_path: Path):
    run_dir = _make_valid_run(tmp_path)
    csv_path = run_dir / "graph_on" / "global_metrics.csv"
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    rows[2]["avg_region_psychological_pressure"] = "0.999"
    _write_csv(csv_path, rows)

    report = validator.validate_run_dir(run_dir)

    assert report["ok"] is False
    assert any("A_z identity mismatch" in issue for issue in report["issues"])


def test_paired_manifest_configuration_mismatch_fails(tmp_path: Path):
    run_dir = _make_valid_run(tmp_path)
    manifest_path = run_dir / "graph_on" / "manifest.json"
    manifest = _read_json(manifest_path)
    manifest["n_residents"] = 21
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    report = validator.validate_run_dir(run_dir)

    assert report["ok"] is False
    assert "paired manifest mismatch: n_residents" in report["issues"]


def test_required_numeric_blank_still_fails(tmp_path: Path):
    run_dir = _make_valid_run(tmp_path)
    csv_path = run_dir / "graph_off" / "global_metrics.csv"
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    rows[0]["avg_stress"] = ""
    _write_csv(csv_path, rows)

    report = validator.validate_run_dir(run_dir)

    assert report["ok"] is False
    assert any("invalid numeric field 'avg_stress'" in issue for issue in report["issues"])


def test_recovery_clock_decrease_during_full_service_fails(tmp_path: Path):
    run_dir = _make_valid_run(tmp_path)
    csv_path = run_dir / "graph_off" / "global_metrics.csv"
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    rows[2]["avg_time_since_service_restoration"] = "0.25"
    rows[3]["avg_time_since_service_restoration"] = "0.10"
    _write_csv(csv_path, rows)

    report = validator.validate_run_dir(run_dir)

    assert report["ok"] is False
    assert any(
        "restoration clock decreases during continuous full service" in issue
        for issue in report["issues"]
    )
