# -*- coding: utf-8 -*-
"""Summarize the event5fix public-opinion validation outputs.

This postprocessor reads the 25 event5fix runs from
trace_output/IJDRR_v7_strict_formal/Event5_literature_validation_n5/psychology_<semantics>
and writes manuscript-facing CSV/Markdown
evidence tables. It does not rerun simulations.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from scipy.stats import t as student_t


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TRACE_BASE = (
    ROOT
    / "trace_output"
    / "IJDRR_v7_strict_formal"
    / "Event5_literature_validation_n5"
)
DEFAULT_OUTPUT_DIR = (
    ROOT
    / "analysis_outputs"
    / "IJDRR_v7_strict_formal"
    / "Event5_literature_validation_n5"
)

SEEDS = (42, 43, 44, 45, 46)
PLAN_COMBOS = (
    ("auto", "linear"),
    ("auto", "log"),
    ("auto", "sqrt"),
    ("off", "sqrt"),
    ("on", "sqrt"),
)
EXPECTED_MODEL_CONTRACT_VERSION = "ijdrr_strict_v1"
MIN_METRIC_SCHEMA_VERSION = 4
EXPECTED_COMMON_CONFIG = {
    "model_contract_version": EXPECTED_MODEL_CONTRACT_VERSION,
    "metric_schema_version": MIN_METRIC_SCHEMA_VERSION,
    "city": "厦门市",
    "district": "思明区",
    "n_residents": 800,
    "n_enterprises": 30,
    "total_steps": 120,
    "outage_step": 16,
    "outage_cause": "equipment_failure",
    "home_distribution": "poi",
    "use_mml": True,
    "switch_ablation": "none",
}

PER_RUN_FIELDS = (
    "final_avg_stress",
    "peak_avg_stress",
    "final_avg_panic",
    "peak_avg_panic",
    "final_herd_ratio",
    "peak_herd_ratio",
    "final_flee_ratio",
    "peak_flee_ratio",
    "final_opinion_active_resident_ratio",
    "peak_opinion_active_resident_ratio",
    "final_opinion_threshold_margin",
    "peak_opinion_threshold_margin",
    "final_opinion_effect_nonzero",
    "peak_seir_I",
    "max_seir_infection_reduction",
)

COMPACT_METRICS = (
    "peak_avg_stress",
    "peak_avg_panic",
    "peak_herd_ratio",
    "peak_flee_ratio",
    "peak_opinion_active_resident_ratio",
    "peak_opinion_threshold_margin",
    "final_opinion_effect_nonzero",
    "max_seir_infection_reduction",
)
PAIRED_CONTINUOUS_FIELDS = tuple(
    field for field in PER_RUN_FIELDS if field != "final_opinion_effect_nonzero"
)

@dataclass(frozen=True)
class RunSpec:
    opinion_mode: str
    profile: str
    seed: int

    @property
    def tag(self) -> str:
        return f"event5fix_opinion_{self.opinion_mode}_{self.profile}_seed{self.seed}"


def expected_specs() -> list[RunSpec]:
    return [
        RunSpec(opinion_mode=mode, profile=profile, seed=seed)
        for mode, profile in PLAN_COMBOS
        for seed in SEEDS
    ]


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def semantics_dir(base: Path, semantics: str) -> Path:
    leaf = f"psychology_{semantics}"
    return base if base.name == leaf else base / leaf


def validate_summary_semantics(data: dict, expected: str, path: Path) -> None:
    if data.get("model_contract_version") != EXPECTED_MODEL_CONTRACT_VERSION:
        raise ValueError(f"summary model_contract_version mismatch: {path}")
    try:
        schema_version = int(data.get("metric_schema_version"))
    except (TypeError, ValueError):
        schema_version = -1
    if schema_version < MIN_METRIC_SCHEMA_VERSION:
        raise ValueError(f"summary metric_schema_version is too old: {path}")
    actual = data.get("config", {}).get("psychology_semantics")
    if actual != expected:
        raise ValueError(
            f"summary psychology_semantics mismatch: expected={expected!r}, "
            f"actual={actual!r}, path={path}"
        )
    manifests = data.get("manifest")
    if not isinstance(manifests, dict):
        raise ValueError(f"summary manifest missing: {path}")
    for graph_mode in ("off", "on"):
        manifest = manifests.get(graph_mode)
        actual = manifest.get("psychology_semantics") if isinstance(manifest, dict) else None
        if actual != expected:
            raise ValueError(
                f"{graph_mode} manifest psychology_semantics mismatch: "
                f"expected={expected!r}, actual={actual!r}, path={path}"
            )
        if manifest.get("model_contract_version") != EXPECTED_MODEL_CONTRACT_VERSION:
            raise ValueError(
                f"{graph_mode} manifest model_contract_version mismatch: {path}"
            )
        try:
            manifest_schema = int(manifest.get("metric_schema_version"))
        except (TypeError, ValueError):
            manifest_schema = -1
        if manifest_schema < MIN_METRIC_SCHEMA_VERSION:
            raise ValueError(
                f"{graph_mode} manifest metric_schema_version is too old: {path}"
            )


def canonical_sha256(data: dict) -> str:
    payload = json.dumps(
        data,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _validate_sha256(value: object, label: str, path: Path) -> str:
    text = str(value or "")
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text.lower()):
        raise ValueError(f"{label} missing or invalid: {path}")
    return text.lower()


def _validate_git_info(git_info: object, label: str, path: Path) -> tuple[str, str]:
    if not isinstance(git_info, dict):
        raise ValueError(f"{label} git metadata missing: {path}")
    commit = str(git_info.get("commit") or "")
    if not commit:
        raise ValueError(f"{label} git commit missing: {path}")
    fingerprint = _validate_sha256(
        git_info.get("worktree_fingerprint_sha256"),
        f"{label} worktree fingerprint",
        path,
    )
    _validate_sha256(
        git_info.get("git_diff_sha256"),
        f"{label} git diff fingerprint",
        path,
    )
    untracked = git_info.get("untracked_code_sha256")
    if not isinstance(untracked, dict):
        raise ValueError(f"{label} untracked-code fingerprint map missing: {path}")
    for relative_path, digest in untracked.items():
        _validate_sha256(
            digest,
            f"{label} untracked-code fingerprint for {relative_path}",
            path,
        )
    return commit, fingerprint


def _config_mismatches(actual: dict, expected: dict) -> dict[str, tuple[object, object]]:
    return {
        key: (expected_value, actual.get(key))
        for key, expected_value in expected.items()
        if actual.get(key) != expected_value
    }


def validate_event5_run_contract(
    data: dict,
    spec: RunSpec,
    expected_semantics: str,
    summary_path: Path,
    run_dir: Path | None = None,
) -> tuple[str, str]:
    """Validate one formal run and return its commit/fingerprint pair."""
    validate_summary_semantics(data, expected_semantics, summary_path)
    config = data.get("config")
    if not isinstance(config, dict):
        raise ValueError(f"summary config missing: {summary_path}")
    if config.get("model_contract_version") != EXPECTED_MODEL_CONTRACT_VERSION:
        raise ValueError(f"summary config model_contract_version mismatch: {summary_path}")
    try:
        config_schema = int(config.get("metric_schema_version"))
    except (TypeError, ValueError):
        config_schema = -1
    if config_schema < MIN_METRIC_SCHEMA_VERSION:
        raise ValueError(f"summary config metric_schema_version is too old: {summary_path}")
    expected_config = {
        **EXPECTED_COMMON_CONFIG,
        "seed": spec.seed,
        "tag": spec.tag,
        "opinion_mode": spec.opinion_mode,
        "outage_stress_profile": spec.profile,
        "psychology_semantics": expected_semantics,
    }
    mismatches = _config_mismatches(config, expected_config)
    if mismatches:
        raise ValueError(f"summary config mismatch: {mismatches}, path={summary_path}")
    expected_summary_hash = canonical_sha256(config)
    if data.get("config_sha256") != expected_summary_hash:
        raise ValueError(f"summary config_sha256 mismatch: {summary_path}")

    summary_commit, summary_fingerprint = _validate_git_info(
        data.get("git"), "summary", summary_path
    )
    manifests = data["manifest"]
    for graph_mode in ("off", "on"):
        manifest = manifests[graph_mode]
        expected_manifest = {
            **EXPECTED_COMMON_CONFIG,
            "seed": spec.seed,
            "tag": spec.tag,
            "opinion_mode": spec.opinion_mode,
            "outage_stress_profile": spec.profile,
            "psychology_semantics": expected_semantics,
            "graph_mode": graph_mode,
            "use_road_graph": graph_mode == "on",
        }
        manifest_mismatches = _config_mismatches(manifest, expected_manifest)
        if manifest_mismatches:
            raise ValueError(
                f"{graph_mode} manifest config mismatch: {manifest_mismatches}, "
                f"path={summary_path}"
            )
        manifest_hash_payload = {
            key: value
            for key, value in manifest.items()
            if key not in {"created_at_utc", "output_dir", "git", "config_sha256"}
        }
        if manifest.get("config_sha256") != canonical_sha256(manifest_hash_payload):
            raise ValueError(f"{graph_mode} manifest config_sha256 mismatch: {summary_path}")
        manifest_commit, manifest_fingerprint = _validate_git_info(
            manifest.get("git"), f"{graph_mode} manifest", summary_path
        )
        if (manifest_commit, manifest_fingerprint) != (
            summary_commit,
            summary_fingerprint,
        ):
            raise ValueError(
                f"{graph_mode} manifest/summary worktree fingerprint mismatch: "
                f"{summary_path}"
            )
        if run_dir is not None:
            manifest_path = run_dir / f"graph_{graph_mode}" / "manifest.json"
            if not manifest_path.exists():
                raise ValueError(f"{graph_mode} manifest file missing: {manifest_path}")
            disk_manifest = read_json(manifest_path)
            if disk_manifest != manifest:
                raise ValueError(
                    f"{graph_mode} disk/summary manifest mismatch: {manifest_path}"
                )
    return summary_commit, summary_fingerprint


def find_run_dir(trace_base: Path, spec: RunSpec) -> Path:
    matches = sorted(trace_base.glob(f"t15_*_{spec.tag}"))
    if len(matches) != 1:
        raise FileNotFoundError(
            f"Expected exactly one directory for {spec.tag}, found {len(matches)}"
        )
    return matches[0]


def mean_ci(values: list[float]) -> tuple[int, float, float, float]:
    n = len(values)
    if n == 0:
        return 0, float("nan"), float("nan"), float("nan")
    mean = sum(values) / n
    if n == 1:
        return n, mean, 0.0, 0.0
    variance = sum((value - mean) ** 2 for value in values) / (n - 1)
    sd = math.sqrt(variance)
    tcrit = float(student_t.ppf(0.975, n - 1))
    ci95 = tcrit * sd / math.sqrt(n)
    return n, mean, sd, ci95


def fmt_ci(mean: float, ci95: float) -> str:
    return f"{mean:.6f} [{mean - ci95:.6f}, {mean + ci95:.6f}]"


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def metric(data: dict, block: str, name: str, graph_mode: str, default: float = 0.0) -> float:
    value = data.get(block, {}).get(name, {})
    if isinstance(value, dict):
        return float(value.get(graph_mode, default))
    return float(default)


def mechanism_value(data: dict, name: str, graph_mode: str, default: object = 0.0) -> object:
    value = data.get("mechanism_checks", {}).get(name, {})
    if isinstance(value, dict):
        return value.get(graph_mode, default)
    return default


def manifest_value(data: dict, graph_mode: str) -> dict:
    value = data.get("manifest", {}).get(graph_mode, {})
    return value if isinstance(value, dict) else {}


def build_rows(
    trace_base: Path, psychology_semantics: str = "strict"
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    per_run_rows: list[dict[str, object]] = []
    mechanism_rows: list[dict[str, object]] = []
    batch_fingerprints: set[tuple[str, str]] = set()
    for spec in expected_specs():
        run_dir = find_run_dir(trace_base, spec)
        summary_path = run_dir / "summary.json"
        data = read_json(summary_path)
        commit_fingerprint = validate_event5_run_contract(
            data,
            spec,
            psychology_semantics,
            summary_path,
            run_dir,
        )
        batch_fingerprints.add(commit_fingerprint)
        config = data.get("config", {})
        for graph_mode in ("off", "on"):
            manifest = manifest_value(data, graph_mode)
            row = {
                "tag": spec.tag,
                "run_dir": str(run_dir),
                "seed": spec.seed,
                "opinion_mode": spec.opinion_mode,
                "outage_stress_profile": spec.profile,
                "graph_mode": graph_mode,
                "psychology_semantics": psychology_semantics,
                "config_matches": True,
                "manifest_matches": True,
                "git_dirty": bool(manifest.get("git", {}).get("dirty", False)),
                "git_commit": manifest.get("git", {}).get("commit", ""),
                "worktree_fingerprint_sha256": manifest.get("git", {}).get(
                    "worktree_fingerprint_sha256", ""
                ),
            }
            row.update(
                {
                    "final_avg_stress": metric(data, "final", "avg_stress", graph_mode),
                    "peak_avg_stress": metric(data, "peak", "avg_stress", graph_mode),
                    "final_avg_panic": metric(data, "final", "avg_panic", graph_mode),
                    "peak_avg_panic": metric(data, "peak", "avg_panic", graph_mode),
                    "final_herd_ratio": metric(data, "final", "herd_ratio", graph_mode),
                    "peak_herd_ratio": metric(data, "peak", "herd_ratio", graph_mode),
                    "final_flee_ratio": metric(data, "final", "flee_ratio", graph_mode),
                    "peak_flee_ratio": metric(data, "peak", "flee_ratio", graph_mode),
                    "final_opinion_active_resident_ratio": metric(
                        data, "final", "opinion_active_resident_ratio", graph_mode
                    ),
                    "peak_opinion_active_resident_ratio": metric(
                        data, "peak", "opinion_active_resident_ratio", graph_mode
                    ),
                    "final_opinion_threshold_margin": metric(
                        data, "final", "opinion_threshold_margin", graph_mode
                    ),
                    "peak_opinion_threshold_margin": metric(
                        data, "peak", "opinion_threshold_margin", graph_mode
                    ),
                    "final_opinion_effect_nonzero": metric(
                        data, "final", "opinion_effect_nonzero", graph_mode
                    ),
                    "peak_seir_I": metric(data, "peak", "seir_I", graph_mode),
                    "max_seir_infection_reduction": float(
                        mechanism_value(
                            data, "max_seir_infection_reduction", graph_mode, 0.0
                        )
                    ),
                }
            )
            per_run_rows.append(row)

            active_steps = int(mechanism_value(data, "opinion_active_steps", graph_mode, 0))
            nonzero_effect = bool(
                mechanism_value(data, "nonzero_opinion_effect_any", graph_mode, False)
            )
            mechanism_rows.append(
                {
                    "tag": spec.tag,
                    "seed": spec.seed,
                    "opinion_mode": spec.opinion_mode,
                    "outage_stress_profile": spec.profile,
                    "graph_mode": graph_mode,
                    "psychology_semantics": psychology_semantics,
                    "config_matches": row["config_matches"],
                    "manifest_matches": row["manifest_matches"],
                    "opinion_active_steps": active_steps,
                    "first_opinion_active_step": json.dumps(
                        mechanism_value(data, "first_opinion_active_step", graph_mode, None),
                        ensure_ascii=False,
                    ),
                    "max_opinion_active_district_count": float(
                        mechanism_value(
                            data, "max_opinion_active_district_count", graph_mode, 0.0
                        )
                    ),
                    "max_opinion_active_resident_ratio": float(
                        mechanism_value(
                            data, "max_opinion_active_resident_ratio", graph_mode, 0.0
                        )
                    ),
                    "max_opinion_trigger_pressure": float(
                        mechanism_value(
                            data, "max_opinion_trigger_pressure", graph_mode, 0.0
                        )
                    ),
                    "max_opinion_threshold_margin": float(
                        mechanism_value(
                            data, "max_opinion_threshold_margin", graph_mode, 0.0
                        )
                    ),
                    "nonzero_opinion_effect_any": nonzero_effect,
                    "max_seir_infection_reduction": float(
                        mechanism_value(
                            data, "max_seir_infection_reduction", graph_mode, 0.0
                        )
                    ),
                    "max_rumor_suppress_rate": float(
                        mechanism_value(data, "max_rumor_suppress_rate", graph_mode, 0.0)
                    ),
                    "passes_expected_mode_check": (
                        (spec.opinion_mode == "off" and active_steps == 0 and not nonzero_effect)
                        or (spec.opinion_mode == "on" and active_steps > 0 and nonzero_effect)
                        or (
                            spec.opinion_mode == "auto"
                            and active_steps == 0
                            and not nonzero_effect
                        )
                    ),
                }
            )
    if len(batch_fingerprints) != 1:
        raise ValueError(
            "event5 formal batch was not produced from one frozen commit/worktree: "
            f"{sorted(batch_fingerprints)}"
        )
    return per_run_rows, mechanism_rows


def aggregate(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str, str], list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        key = (
            str(row["opinion_mode"]),
            str(row["outage_stress_profile"]),
            str(row["graph_mode"]),
        )
        grouped[key].append(row)

    out: list[dict[str, object]] = []
    for (opinion_mode, profile, graph_mode), group_rows in sorted(grouped.items()):
        for field in PER_RUN_FIELDS:
            values = [float(row[field]) for row in group_rows]
            n, mean, sd, ci95 = mean_ci(values)
            out.append(
                {
                    "opinion_mode": opinion_mode,
                    "outage_stress_profile": profile,
                    "graph_mode": graph_mode,
                    "metric": field,
                    "n": n,
                    "mean": mean,
                    "sd": sd,
                    "ci95": ci95,
                    "mean_ci95": fmt_ci(mean, ci95),
                }
            )
    return out


def build_on_off_paired_records(
    rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Build seed-matched opinion-on minus opinion-off continuous outcomes."""
    indexed: dict[tuple[str, str, str, int], dict[str, object]] = {}
    for row in rows:
        key = (
            str(row["opinion_mode"]),
            str(row["outage_stress_profile"]),
            str(row["graph_mode"]),
            int(row["seed"]),
        )
        if key in indexed:
            raise ValueError(f"duplicate event5 pairing cell: {key}")
        indexed[key] = row

    paired: list[dict[str, object]] = []
    for graph_mode in ("off", "on"):
        for seed in SEEDS:
            off_key = ("off", "sqrt", graph_mode, seed)
            on_key = ("on", "sqrt", graph_mode, seed)
            if off_key not in indexed or on_key not in indexed:
                raise ValueError(
                    f"incomplete event5 on/off seed pair: graph={graph_mode}, seed={seed}"
                )
            off_row = indexed[off_key]
            on_row = indexed[on_key]
            for field in PAIRED_CONTINUOUS_FIELDS:
                off_value = float(off_row[field])
                on_value = float(on_row[field])
                if not math.isfinite(off_value) or not math.isfinite(on_value):
                    raise ValueError(
                        f"non-finite event5 pair: graph={graph_mode}, seed={seed}, "
                        f"metric={field}"
                    )
                paired.append(
                    {
                        "outage_stress_profile": "sqrt",
                        "graph_mode": graph_mode,
                        "seed": seed,
                        "metric": field,
                        "opinion_off": off_value,
                        "opinion_on": on_value,
                        "paired_delta_on_minus_off": on_value - off_value,
                        "psychology_semantics": off_row["psychology_semantics"],
                        "worktree_fingerprint_sha256": off_row[
                            "worktree_fingerprint_sha256"
                        ],
                    }
                )
    return paired


def aggregate_on_off_paired_records(
    paired_rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for row in paired_rows:
        grouped[(str(row["graph_mode"]), str(row["metric"]))].append(row)

    out: list[dict[str, object]] = []
    for (graph_mode, field), group_rows in sorted(grouped.items()):
        seeds = [int(row["seed"]) for row in group_rows]
        if sorted(seeds) != list(SEEDS):
            raise ValueError(
                f"event5 paired seed set mismatch for graph={graph_mode}, "
                f"metric={field}: {seeds}"
            )
        deltas = [float(row["paired_delta_on_minus_off"]) for row in group_rows]
        n, mean_delta, sd_delta, half_width = mean_ci(deltas)
        lo = mean_delta - half_width
        hi = mean_delta + half_width
        if n < 2:
            p_value = None
        elif sd_delta == 0.0:
            p_value = 1.0 if mean_delta == 0.0 else 0.0
        else:
            statistic = mean_delta / (sd_delta / math.sqrt(n))
            p_value = float(2.0 * student_t.sf(abs(statistic), n - 1))
        ci_excludes_zero = bool(n >= 2 and (lo > 0.0 or hi < 0.0))
        out.append(
            {
                "contrast": "opinion_on_minus_off",
                "outage_stress_profile": "sqrt",
                "graph_mode": graph_mode,
                "metric": field,
                "n_pairs": n,
                "opinion_off_mean": sum(
                    float(row["opinion_off"]) for row in group_rows
                )
                / n,
                "opinion_on_mean": sum(
                    float(row["opinion_on"]) for row in group_rows
                )
                / n,
                "paired_delta_mean": mean_delta,
                "paired_delta_sd": sd_delta,
                "paired_delta_ci95_lo": lo,
                "paired_delta_ci95_hi": hi,
                "paired_t_p_value_two_sided": p_value,
                "paired_delta_ci_excludes_zero": ci_excludes_zero,
                "evidence_statement": (
                    "paired 95% CI excludes zero"
                    if ci_excludes_zero
                    else "paired 95% CI includes zero; no directional effect claim"
                ),
            }
        )
    return out


def grouped_mechanism_counts(rows: Iterable[dict[str, object]]) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str, str], list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        grouped[
            (
                str(row["opinion_mode"]),
                str(row["outage_stress_profile"]),
                str(row["graph_mode"]),
            )
        ].append(row)

    out: list[dict[str, object]] = []
    for (opinion_mode, profile, graph_mode), group_rows in sorted(grouped.items()):
        margins = [float(row["max_opinion_threshold_margin"]) for row in group_rows]
        ratios = [float(row["max_opinion_active_resident_ratio"]) for row in group_rows]
        n_margin, mean_margin, _sd_margin, ci_margin = mean_ci(margins)
        _n_ratio, mean_ratio, _sd_ratio, ci_ratio = mean_ci(ratios)
        out.append(
            {
                "opinion_mode": opinion_mode,
                "outage_stress_profile": profile,
                "graph_mode": graph_mode,
                "n": len(group_rows),
                "active_runs": sum(
                    1 for row in group_rows if int(row["opinion_active_steps"]) > 0
                ),
                "nonzero_effect_runs": sum(
                    1 for row in group_rows if bool(row["nonzero_opinion_effect_any"])
                ),
                "mean_active_resident_ratio_ci95": fmt_ci(mean_ratio, ci_ratio),
                "mean_threshold_margin_ci95": fmt_ci(mean_margin, ci_margin),
                "all_config_manifest_match": all(
                    bool(row["config_matches"]) and bool(row["manifest_matches"])
                    for row in group_rows
                ),
                "all_expected_mode_checks_pass": all(
                    bool(row["passes_expected_mode_check"]) for row in group_rows
                ),
                "margin_n": n_margin,
            }
        )
    return out


def aggregate_lookup(rows: list[dict[str, object]]) -> dict[tuple[str, str, str, str], str]:
    return {
        (
            str(row["opinion_mode"]),
            str(row["outage_stress_profile"]),
            str(row["graph_mode"]),
            str(row["metric"]),
        ): str(row["mean_ci95"])
        for row in rows
    }


def write_threshold_design(path: Path) -> None:
    content = [
        "# Event 5 Threshold-Sensitivity / Trigger-Boundary Design",
        "",
        "Date: 2026-07-14",
        "",
        "## Purpose",
        "",
        "The event5fix runs show that the baseline automatic public-opinion trigger remains inactive. The next experiment should therefore estimate the trigger boundary, not force a positive conclusion.",
        "",
        "## Design",
        "",
        "- Keep the baseline city/district/population protocol: Xiamen / Siming, N = 800, seeds 42-46, outage step 16, 120 steps, `outage_stress_profile=sqrt`.",
        "- Sweep only the opinion-management trigger threshold, e.g. 0.10, 0.20, 0.30, 0.35, 0.40, plus the current baseline threshold.",
        "- Use `opinion_mode=auto`; keep `off` and `on` as zero-effect and forced positive controls from the event5fix batch.",
        "- Report active district count, active resident ratio, active steps, first active step, threshold margin and nonzero opinion effect before interpreting stress or panic outcomes.",
        "- Stop the sweep once at least one intermediate threshold produces partial activation rather than all-off or all-on behaviour.",
        "",
        "## Acceptance Criteria",
        "",
        "- A threshold value is interpretable only if `auto` produces nonzero active steps and nonzero opinion effect in at least one seed.",
        "- Manuscript language must remain conditional unless activation appears under the baseline threshold.",
        "- If only low thresholds activate the channel, report the result as a calibration boundary: the baseline threshold is conservative for the current blackout scenario.",
        "",
    ]
    path.write_text("\n".join(content), encoding="utf-8")


def write_summary(
    path: Path,
    per_run: list[dict[str, object]],
    aggregate_rows: list[dict[str, object]],
    paired_effect_rows: list[dict[str, object]],
    mechanism_group_rows: list[dict[str, object]],
    missing: list[str],
) -> None:
    lookup = aggregate_lookup(aggregate_rows)
    failed_groups = [
        row
        for row in mechanism_group_rows
        if not (
            row["all_config_manifest_match"] and row["all_expected_mode_checks_pass"]
        )
    ]

    lines = [
        "# Event 5 Public-Opinion Mechanism Audit (event5fix)",
        "",
        "Date: 2026-07-14",
        "",
        "## Run Coverage",
        "",
        f"- Expected event5fix runs: 25",
        f"- Completed event5fix runs: {25 - len(missing)}",
        f"- Per-run graph rows: {len(per_run)} (run x graph-off/on)",
        "- Source tree: `trace_output/IJDRR_v7_strict_formal/Event5_literature_validation_n5/psychology_<semantics>/*event5fix*/summary.json`",
        "- Earlier diagnostic batches are not used as manuscript evidence here.",
        "",
        "## Mechanism Verdict",
        "",
        "- `auto`: no active steps and no nonzero opinion-management effect under the baseline threshold for sqrt/log/linear stress profiles.",
        "- `off`: zero active steps and zero opinion-management effect, as expected for the negative control.",
        "- `on`: active resident ratio reaches 1.0 and nonzero opinion-management effects are recorded in all seeds, so it is a forced positive control rather than evidence that the automatic trigger activated.",
        "- The automatic-trigger threshold margin remains negative in the baseline runs, so the correct manuscript wording is that the implemented channel exists but the baseline automatic trigger remains inactive.",
        "",
        "## Grouped Mechanism Checks",
        "",
        "| opinion mode | profile | graph | n | active runs | nonzero-effect runs | active resident ratio mean [95% CI] | threshold margin mean [95% CI] | checks |",
        "| --- | --- | --- | ---: | ---: | ---: | --- | --- | --- |",
    ]
    for row in mechanism_group_rows:
        checks = "pass" if row["all_expected_mode_checks_pass"] else "review"
        lines.append(
            f"| `{row['opinion_mode']}` | `{row['outage_stress_profile']}` | "
            f"{row['graph_mode']} | {row['n']} | {row['active_runs']} | "
            f"{row['nonzero_effect_runs']} | {row['mean_active_resident_ratio_ci95']} | "
            f"{row['mean_threshold_margin_ci95']} | {checks} |"
        )
    lines.append("")

    lines.extend(
        [
            "## Seed-Paired Opinion-On vs Opinion-Off Continuous Outcomes",
            "",
            "The inferential unit is the seed-matched on-minus-off difference. "
            "A change in the sample mean alone is not treated as evidence of a "
            "directional effect.",
            "",
            "| graph | metric | n pairs | off mean | on mean | paired delta mean [95% CI] | two-sided paired-t p | evidence |",
            "| --- | --- | ---: | ---: | ---: | --- | ---: | --- |",
        ]
    )
    for row in paired_effect_rows:
        p_value = row["paired_t_p_value_two_sided"]
        p_text = "n/a" if p_value is None else f"{float(p_value):.6g}"
        lines.append(
            f"| {row['graph_mode']} | `{row['metric']}` | {row['n_pairs']} | "
            f"{float(row['opinion_off_mean']):.6f} | "
            f"{float(row['opinion_on_mean']):.6f} | "
            f"{float(row['paired_delta_mean']):.6f} "
            f"[{float(row['paired_delta_ci95_lo']):.6f}, "
            f"{float(row['paired_delta_ci95_hi']):.6f}] | {p_text} | "
            f"{row['evidence_statement']} |"
        )
    lines.append("")

    lines.extend(
        [
            "## Manuscript-Facing Metric Table",
            "",
            "| opinion mode | profile | graph | peak stress | peak panic | peak herd | peak flee | active ratio | threshold margin | nonzero effect | SEIR reduction |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    groups = sorted(
        {
            (
                str(row["opinion_mode"]),
                str(row["outage_stress_profile"]),
                str(row["graph_mode"]),
            )
            for row in per_run
        }
    )
    for opinion_mode, profile, graph_mode in groups:
        values = [
            lookup[(opinion_mode, profile, graph_mode, metric)]
            for metric in COMPACT_METRICS
        ]
        lines.append(
            f"| `{opinion_mode}` | `{profile}` | {graph_mode} | "
            + " | ".join(values)
            + " |"
        )
    lines.append("")

    lines.extend(
        [
            "## Threshold-Sensitivity Design",
            "",
            "The next run should be a trigger-boundary sweep, not an expanded claim test. Keep `opinion_mode=auto` and sweep the opinion threshold while reporting active district count, active resident ratio, active steps, first active step, threshold margin and nonzero opinion effect. Only thresholds that generate nonzero active steps and nonzero effects can support an automatic-mechanism statement.",
            "",
            "## IJDRR Wording Guardrail",
            "",
            "Use: \"The forced-on positive control confirms that the implemented public-opinion management channel executes, while the baseline automatic trigger remains inactive under the current threshold. Continuous outcome differences are interpreted only from seed-paired estimates and their 95% confidence intervals.\"",
            "",
            "Do not use: \"The automatic public-opinion management mechanism is validated.\"",
            "",
        ]
    )
    if missing or failed_groups:
        lines.extend(["## Items Requiring Review", ""])
        for tag in missing:
            lines.append(f"- Missing run: `{tag}`")
        for row in failed_groups:
            lines.append(
                f"- Check group review: `{row['opinion_mode']}` / "
                f"`{row['outage_stress_profile']}` / graph={row['graph_mode']}"
            )
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace-base", type=Path, default=DEFAULT_TRACE_BASE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--psychology-semantics",
        choices=("strict", "legacy"),
        default="strict",
        help="Only aggregate runs produced under this psychology contract.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    trace_base = semantics_dir(args.trace_base, args.psychology_semantics)
    output_dir = semantics_dir(args.output_dir, args.psychology_semantics)
    output_dir.mkdir(parents=True, exist_ok=True)

    missing: list[str] = []
    for spec in expected_specs():
        try:
            find_run_dir(trace_base, spec)
        except FileNotFoundError:
            missing.append(spec.tag)
    if missing:
        raise SystemExit(f"Missing event5fix runs: {missing}")

    per_run, mechanism = build_rows(trace_base, args.psychology_semantics)
    agg = aggregate(per_run)
    paired_records = build_on_off_paired_records(per_run)
    paired_effects = aggregate_on_off_paired_records(paired_records)
    mechanism_grouped = grouped_mechanism_counts(mechanism)

    write_csv(output_dir / "event5fix_per_run.csv", per_run)
    write_csv(output_dir / "event5fix_mean_ci.csv", agg)
    write_csv(
        output_dir / "event5fix_on_off_paired_records.csv",
        paired_records,
    )
    write_csv(
        output_dir / "event5fix_on_off_paired_effects.csv",
        paired_effects,
    )
    write_csv(
        output_dir / "event5fix_mechanism_checks.csv", mechanism
    )
    write_csv(
        output_dir / "event5fix_grouped_mechanism_checks.csv",
        mechanism_grouped,
    )
    write_summary(
        output_dir / "event5fix_summary.md",
        per_run,
        agg,
        paired_effects,
        mechanism_grouped,
        missing,
    )
    write_threshold_design(
        output_dir / "event5fix_threshold_sensitivity_design.md"
    )
    print(f"[out] {output_dir}")
    print(f"[coverage] runs=25 graph_rows={len(per_run)}")
    print(
        f"[paired on-off] raw_rows={len(paired_records)} "
        f"effect_rows={len(paired_effects)}"
    )
    print(f"[mechanism] rows={len(mechanism)} groups={len(mechanism_grouped)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
