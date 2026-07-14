from __future__ import annotations

import json
import math
import sys
from argparse import Namespace
from pathlib import Path

import pytest
import numpy as np
from scipy.stats import t as student_t

from analysis import aggregate_f7_nscan_ci
from analysis import compute_e6_6_k200_metrics
from analysis import e2_aggregate
from analysis import f2_compare_r
from analysis import f4_aggregate
from analysis import summarize_event5fix_validation
from scripts import run_e2_ablation_matrix
from scripts import run_f2_home_dist
from scripts import run_f4_multi_seed
from scripts import run_f7_n_scan
from scripts import run_literature_validation_batches
from scripts import run_m4_n5_batches


def valid_summary(semantics: str = "strict") -> dict:
    return {
        "model_contract_version": "ijdrr_strict_v1",
        "metric_schema_version": 4,
        "config": {"psychology_semantics": semantics},
        "manifest": {
            "off": {
                "model_contract_version": "ijdrr_strict_v1",
                "metric_schema_version": 4,
                "psychology_semantics": semantics,
            },
            "on": {
                "model_contract_version": "ijdrr_strict_v1",
                "metric_schema_version": 4,
                "psychology_semantics": semantics,
            },
        },
    }


@pytest.mark.parametrize(
    ("helper", "base"),
    [
        (aggregate_f7_nscan_ci.semantics_dir, Path("runs")),
        (compute_e6_6_k200_metrics.semantics_dir, Path("runs")),
        (summarize_event5fix_validation.semantics_dir, Path("runs")),
    ],
)
def test_path_helper_inserts_semantics_exactly_once(helper, base):
    strict = helper(base, "strict")
    assert strict == base / "psychology_strict"
    assert helper(strict, "strict") == strict
    assert helper(base, "legacy") == base / "psychology_legacy"


@pytest.mark.parametrize(
    "validator",
    [
        aggregate_f7_nscan_ci.validate_summary_semantics,
        compute_e6_6_k200_metrics.validate_summary_semantics,
        summarize_event5fix_validation.validate_summary_semantics,
        e2_aggregate.validate_summary_semantics,
        f2_compare_r.validate_summary_semantics,
        f4_aggregate.validate_summary_semantics,
    ],
)
def test_aggregators_reject_missing_or_mismatched_semantics(validator):
    validator(valid_summary(), "strict", Path("summary.json"))

    missing = valid_summary()
    del missing["config"]["psychology_semantics"]
    with pytest.raises(ValueError, match="psychology_semantics mismatch"):
        validator(missing, "strict", Path("summary.json"))

    mismatched_manifest = valid_summary()
    mismatched_manifest["manifest"]["on"]["psychology_semantics"] = "legacy"
    with pytest.raises(ValueError, match="manifest psychology_semantics mismatch"):
        validator(mismatched_manifest, "strict", Path("summary.json"))

    outdated_schema = valid_summary()
    outdated_schema["metric_schema_version"] = 3
    with pytest.raises(ValueError, match="metric_schema_version"):
        validator(outdated_schema, "strict", Path("summary.json"))


@pytest.mark.parametrize(
    "validator",
    [
        run_m4_n5_batches.validate_summary_semantics,
        run_f2_home_dist.validate_summary_semantics,
        run_f4_multi_seed.validate_summary_semantics,
        run_f7_n_scan.validate_summary_semantics,
        run_e2_ablation_matrix._validate_summary_semantics,
    ],
)
def test_runner_skip_gate_rejects_outdated_contract(tmp_path, validator):
    path = tmp_path / "summary.json"
    path.write_text(json.dumps(valid_summary()), encoding="utf-8")
    validator(path, "strict")

    outdated = valid_summary()
    outdated["manifest"]["off"]["metric_schema_version"] = 3
    path.write_text(json.dumps(outdated), encoding="utf-8")
    with pytest.raises(RuntimeError, match="metric_schema_version"):
        validator(path, "strict")


def test_formal_ci_uses_student_t_for_n5_and_n10():
    for values in ([1.0, 2.0, 3.0, 4.0, 5.0], list(map(float, range(1, 11)))):
        n = len(values)
        mean = sum(values) / n
        variance = sum((value - mean) ** 2 for value in values) / (n - 1)
        expected_half = (
            float(student_t.ppf(0.975, n - 1))
            * math.sqrt(variance)
            / math.sqrt(n)
        )

        f7_mean, f7_lo, f7_hi, f7_n = aggregate_f7_nscan_ci.mean_ci(values)
        assert f7_n == n
        assert f7_mean == pytest.approx(mean)
        assert f7_hi - f7_mean == pytest.approx(expected_half)
        assert f7_mean - f7_lo == pytest.approx(expected_half)

        e6_mean, e6_lo, e6_hi, e6_n = compute_e6_6_k200_metrics.mean_ci(values)
        assert e6_n == n
        assert e6_mean == pytest.approx(mean)
        assert e6_hi - e6_mean == pytest.approx(expected_half)
        assert e6_mean - e6_lo == pytest.approx(expected_half)

        event_n, event_mean, _event_sd, event_half = (
            summarize_event5fix_validation.mean_ci(values)
        )
        assert event_n == n
        assert event_mean == pytest.approx(mean)
        assert event_half == pytest.approx(expected_half)

        e2_mean, _e2_sd, e2_lo, e2_hi = e2_aggregate.ci95(values)
        assert e2_hi - e2_mean == pytest.approx(expected_half)
        assert e2_mean - e2_lo == pytest.approx(expected_half)

        f4_mean, _f4_sd, f4_lo, f4_hi = f4_aggregate.ci95(values)
        assert f4_hi - f4_mean == pytest.approx(expected_half)
        assert f4_mean - f4_lo == pytest.approx(expected_half)

        f2_mean, f2_lo, f2_hi, f2_n = f2_compare_r.mean_ci(values)
        assert f2_n == n
        assert f2_mean == pytest.approx(mean)
        assert f2_hi - f2_mean == pytest.approx(expected_half)
        assert f2_mean - f2_lo == pytest.approx(expected_half)


def test_m4_defaults_cover_complete_strict_n5_seed_set(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["run_m4_n5_batches.py"])
    args = run_m4_n5_batches.parse_args()
    assert args.psychology_semantics == "strict"
    assert args.seeds == [42, 43, 44, 45, 46]
    assert "IJDRR_v7_strict_formal" in str(args.output_root)


@pytest.mark.parametrize(
    ("module", "expected_seeds"),
    [
        (run_f4_multi_seed, list(range(42, 52))),
        (run_f7_n_scan, [42, 43, 44, 45, 46]),
        (run_f2_home_dist, [42, 43, 44, 45, 46]),
    ],
)
def test_formal_runner_defaults_use_new_root_and_complete_seeds(
    monkeypatch, module, expected_seeds
):
    monkeypatch.setattr(sys, "argv", [module.__file__])
    args = module.parse_args()
    assert args.seeds == expected_seeds
    assert "IJDRR_v7_strict_formal" in args.output_base


@pytest.mark.parametrize(
    "module",
    [run_f2_home_dist, run_f4_multi_seed, run_f7_n_scan],
)
def test_legacy_semantics_remains_explicitly_selectable(monkeypatch, module):
    monkeypatch.setattr(
        sys,
        "argv",
        [module.__file__, "--psychology-semantics", "legacy"],
    )
    args = module.parse_args()
    assert args.psychology_semantics == "legacy"


def test_e2_command_propagates_semantics_and_checks_strict_path(tmp_path):
    args = Namespace(
        output_base="E2_ablation_matrix",
        output_base_abs=str(tmp_path / "E2_ablation_matrix"),
        run_root_abs=str(
            tmp_path / "E2_ablation_matrix" / "psychology_strict"
        ),
        n_residents=8,
        n_enterprises=2,
        total_steps=2,
        outage_step=1,
        psychology_semantics="strict",
    )
    cmd, run_dir = run_e2_ablation_matrix._build_command(
        args, "city", "district", 42, "none"
    )
    flag_index = cmd.index("--psychology-semantics")
    assert cmd[flag_index + 1] == "strict"
    assert Path(run_dir).parent.name == "psychology_strict"


def test_literature_validation_paths_are_semantics_isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(run_literature_validation_batches, "TRACE_BASE", tmp_path)
    spec = run_literature_validation_batches.expected_specs()[0]
    assert "psychology_strict" in run_literature_validation_batches.run_dir(
        spec, "strict"
    ).parts
    assert "psychology_legacy" in run_literature_validation_batches.run_dir(
        spec, "legacy"
    ).parts


def test_f4_uses_seed_paired_t_interval_and_exports_raw_pairs():
    deltas = [1.0, 2.0, 3.0, 4.0, 5.0]
    records = []
    for seed, delta in zip(range(42, 47), deltas):
        record = {
            "city": "City",
            "district": "District",
            "seed": seed,
            "home_distribution": "poi",
            "psychology_semantics": "strict",
        }
        for metric, _label in f4_aggregate.METRICS:
            record[f"{metric}_off"] = 10.0 + seed
            record[f"{metric}_on"] = 10.0 + seed + delta
        records.append(record)

    row = f4_aggregate.aggregate(records)[0]
    expected_half = float(student_t.ppf(0.975, 4)) * np.std(deltas, ddof=1) / np.sqrt(5)
    assert row["herd_ratio_paired_delta_mean"] == pytest.approx(3.0)
    assert row["herd_ratio_paired_delta_lo95"] == pytest.approx(3.0 - expected_half)
    assert row["herd_ratio_paired_delta_hi95"] == pytest.approx(3.0 + expected_half)
    paired = f4_aggregate.build_paired_seed_records(records)
    assert len(paired) == 5 * len(f4_aggregate.METRICS)
    assert paired[0]["paired_delta_on_minus_off"] == pytest.approx(1.0)

    with pytest.raises(ValueError, match="duplicate seeds"):
        f4_aggregate.aggregate(records + [dict(records[0])])
    incomplete = [dict(record) for record in records]
    incomplete[0]["herd_ratio_on"] = None
    with pytest.raises(ValueError, match="incomplete/non-finite graph pair"):
        f4_aggregate.aggregate(incomplete)


def test_e6_correlation_summary_uses_fisher_z_student_t_back_transform():
    values = [0.10, 0.35, 0.60, 0.75, 0.85]
    mean_r, lo, hi, n = compute_e6_6_k200_metrics.fisher_r_ci(values)
    z = np.arctanh(values)
    mean_z = float(np.mean(z))
    half_z = float(student_t.ppf(0.975, 4) * np.std(z, ddof=1) / np.sqrt(5))
    assert n == 5
    assert mean_r == pytest.approx(np.tanh(mean_z))
    assert lo == pytest.approx(np.tanh(mean_z - half_z))
    assert hi == pytest.approx(np.tanh(mean_z + half_z))
    assert mean_r != pytest.approx(np.mean(values))
    with pytest.raises(ValueError, match="outside"):
        compute_e6_6_k200_metrics.fisher_r_ci([0.2, 1.01])


def _event5_pair_rows(deltas):
    rows = []
    fingerprint = "a" * 64
    for graph_mode in ("off", "on"):
        for seed, delta in zip(summarize_event5fix_validation.SEEDS, deltas):
            for opinion_mode in ("off", "on"):
                row = {
                    "seed": seed,
                    "opinion_mode": opinion_mode,
                    "outage_stress_profile": "sqrt",
                    "graph_mode": graph_mode,
                    "psychology_semantics": "strict",
                    "worktree_fingerprint_sha256": fingerprint,
                }
                for field in summarize_event5fix_validation.PER_RUN_FIELDS:
                    row[field] = 0.0
                if opinion_mode == "on":
                    for field in summarize_event5fix_validation.PAIRED_CONTINUOUS_FIELDS:
                        row[field] = delta
                    row["final_opinion_effect_nonzero"] = 1.0
                rows.append(row)
    return rows


def test_event5_on_off_inference_is_seed_paired_and_not_direction_only():
    rows = _event5_pair_rows([-2.0, -1.0, 0.0, 1.0, 2.0])
    raw = summarize_event5fix_validation.build_on_off_paired_records(rows)
    effects = summarize_event5fix_validation.aggregate_on_off_paired_records(raw)
    assert len(raw) == 2 * 5 * len(
        summarize_event5fix_validation.PAIRED_CONTINUOUS_FIELDS
    )
    effect = next(
        row
        for row in effects
        if row["graph_mode"] == "off" and row["metric"] == "peak_avg_stress"
    )
    assert effect["paired_delta_mean"] == pytest.approx(0.0)
    assert effect["paired_t_p_value_two_sided"] == pytest.approx(1.0)
    assert effect["paired_delta_ci_excludes_zero"] is False
    assert "no directional effect claim" in effect["evidence_statement"]


def _valid_event5_summary(spec):
    module = summarize_event5fix_validation
    config = {
        **module.EXPECTED_COMMON_CONFIG,
        "seed": spec.seed,
        "tag": spec.tag,
        "opinion_mode": spec.opinion_mode,
        "outage_stress_profile": spec.profile,
        "psychology_semantics": "strict",
    }
    git = {
        "commit": "abc123",
        "dirty": True,
        "status_short": " M example.py",
        "git_diff_sha256": "b" * 64,
        "untracked_code_sha256": {"new.py": "c" * 64},
        "worktree_fingerprint_sha256": "a" * 64,
    }
    manifests = {}
    for graph_mode in ("off", "on"):
        manifest = {
            **module.EXPECTED_COMMON_CONFIG,
            "seed": spec.seed,
            "tag": spec.tag,
            "opinion_mode": spec.opinion_mode,
            "outage_stress_profile": spec.profile,
            "psychology_semantics": "strict",
            "graph_mode": graph_mode,
            "use_road_graph": graph_mode == "on",
            "created_at_utc": "2026-07-14T00:00:00+00:00",
            "output_dir": str(Path("run") / f"graph_{graph_mode}"),
            "git": dict(git),
        }
        payload = {
            key: value
            for key, value in manifest.items()
            if key not in {"created_at_utc", "output_dir", "git", "config_sha256"}
        }
        manifest["config_sha256"] = module.canonical_sha256(payload)
        manifests[graph_mode] = manifest
    return {
        "model_contract_version": module.EXPECTED_MODEL_CONTRACT_VERSION,
        "metric_schema_version": module.MIN_METRIC_SCHEMA_VERSION,
        "config": config,
        "config_sha256": module.canonical_sha256(config),
        "git": git,
        "manifest": manifests,
    }


def test_event5_contract_rejects_config_and_fingerprint_drift(tmp_path):
    module = summarize_event5fix_validation
    spec = module.RunSpec("on", "sqrt", 42)
    summary = _valid_event5_summary(spec)
    run_dir = tmp_path / "run"
    for graph_mode in ("off", "on"):
        manifest_dir = run_dir / f"graph_{graph_mode}"
        manifest_dir.mkdir(parents=True)
        (manifest_dir / "manifest.json").write_text(
            json.dumps(summary["manifest"][graph_mode]), encoding="utf-8"
        )
    assert module.validate_event5_run_contract(
        summary, spec, "strict", run_dir / "summary.json", run_dir
    ) == ("abc123", "a" * 64)

    bad_config = json.loads(json.dumps(summary))
    bad_config["config"]["seed"] = 43
    with pytest.raises(ValueError, match="config mismatch"):
        module.validate_event5_run_contract(
            bad_config, spec, "strict", run_dir / "summary.json"
        )
    bad_fingerprint = json.loads(json.dumps(summary))
    bad_fingerprint["manifest"]["on"]["git"][
        "worktree_fingerprint_sha256"
    ] = "d" * 64
    with pytest.raises(ValueError, match="fingerprint mismatch"):
        module.validate_event5_run_contract(
            bad_fingerprint, spec, "strict", run_dir / "summary.json"
        )


def test_event5_defaults_target_formal_orchestrator_paths():
    module = summarize_event5fix_validation
    assert module.DEFAULT_TRACE_BASE.name == "Event5_literature_validation_n5"
    assert "analysis_outputs" in module.DEFAULT_OUTPUT_DIR.parts
    assert module.DEFAULT_OUTPUT_DIR.name == "Event5_literature_validation_n5"
