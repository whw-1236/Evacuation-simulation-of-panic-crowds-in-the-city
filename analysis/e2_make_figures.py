# -*- coding: utf-8 -*-
"""Create publication-ready tables and figures for E2 ablation results."""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
TRACE_ROOT = ROOT / "trace_output"

CITY_LABELS = {
    "厦门市/思明区": "Xiamen/Siming",
    "沈阳市/沈河区": "Shenyang/Shenhe",
    "北京市/东城区": "Beijing/Dongcheng",
}

ABLATION_LABELS = {
    "none": "baseline",
    "hard_switch": "hard\nswitch",
    "soft_switch": "soft\nswitch",
    "no_info_network": "no info\nnetwork",
    "distance_only_store": "distance\nonly store",
    "no_inertia": "no\ninertia",
    "no_hysteresis": "no\nhysteresis",
    "no_outcome_feedback": "no outcome\nfeedback",
    "no_behavior_demo": "no behavior\ndemo",
    "i1_minimal": "I1\nminimal",
    "no_flee": "no\nflee",
}

ABLATION_ORDER = [
    "none",
    "hard_switch",
    "soft_switch",
    "no_info_network",
    "distance_only_store",
    "no_inertia",
    "no_hysteresis",
    "no_outcome_feedback",
    "no_behavior_demo",
    "i1_minimal",
    "no_flee",
]

METRIC_PANELS = [
    ("avg_stress_on_vs_baseline", "A", "Mean stress", ".3f"),
    ("herd_ratio_on_vs_baseline", "B", "Herding ratio", ".3f"),
    ("flee_ratio_on_vs_baseline", "C", "Flee ratio", ".3f"),
]


def load_summary(input_base: str) -> tuple[pd.DataFrame, Path]:
    input_dir = Path(input_base)
    if not input_dir.is_absolute():
        input_dir = TRACE_ROOT / input_base
    csv_path = input_dir / "e2_ablation_summary.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"summary CSV not found: {csv_path}")
    df = pd.read_csv(csv_path)
    df["city_district"] = df["city"].astype(str) + "/" + df["district"].astype(str)
    df["city_label"] = df["city_district"].map(CITY_LABELS).fillna(df["city_district"])
    df["ablation"] = pd.Categorical(df["ablation"], categories=ABLATION_ORDER, ordered=True)
    return df.sort_values(["city_label", "ablation"]), input_dir


def validate(df: pd.DataFrame, zero_tol: float = 5e-4) -> dict:
    expected_cells = len(CITY_LABELS) * len(ABLATION_ORDER)
    cell_count = int(len(df))
    missing = []
    for city in CITY_LABELS.values():
        sub = df[df["city_label"] == city]
        for ablation in ABLATION_ORDER:
            if not ((sub["ablation"].astype(str) == ablation).any()):
                missing.append({"city": city, "ablation": ablation})

    zero_effect = []
    metrics = [m[0] for m in METRIC_PANELS]
    for _, row in df.iterrows():
        if str(row["ablation"]) == "none":
            continue
        vals = [float(row[m]) for m in metrics if pd.notna(row[m])]
        if vals and all(abs(v) < zero_tol for v in vals):
            zero_effect.append({"city": row["city_label"], "ablation": str(row["ablation"])})

    return {
        "expected_cells": expected_cells,
        "observed_cells": cell_count,
        "all_n_runs_are_10": bool((df["n_runs"] == 10).all()),
        "near_zero_threshold_abs_delta": zero_tol,
        "missing_cells": missing,
        "near_zero_effect_cells": zero_effect,
        "near_zero_effect_ablations_all_cities": sorted(
            {
                ablation
                for ablation in ABLATION_ORDER
                if ablation != "none"
                and all(
                    any(z["city"] == city and z["ablation"] == ablation for z in zero_effect)
                    for city in CITY_LABELS.values()
                )
            }
        ),
    }


def write_paper_table(df: pd.DataFrame, out_dir: Path) -> Path:
    cols = [
        "city_label",
        "ablation",
        "n_runs",
        "avg_stress_on_mean",
        "avg_stress_on_vs_baseline",
        "herd_ratio_on_mean",
        "herd_ratio_on_vs_baseline",
        "flee_ratio_on_mean",
        "flee_ratio_on_vs_baseline",
        "avg_edge_congestion_on_mean",
        "avg_edge_congestion_on_vs_baseline",
    ]
    table = df.copy()
    table["ablation"] = table["ablation"].astype(str)
    table = table[cols]
    out_path = out_dir / "e2_ablation_paper_table.csv"
    table.to_csv(out_path, index=False, encoding="utf-8-sig")
    return out_path


def _panel_matrix(df: pd.DataFrame, metric: str) -> tuple[list[str], list[str], np.ndarray]:
    cities = list(CITY_LABELS.values())
    ablations = ABLATION_ORDER
    mat = np.full((len(cities), len(ablations)), np.nan)
    for i, city in enumerate(cities):
        for j, ablation in enumerate(ablations):
            hit = df[(df["city_label"] == city) & (df["ablation"].astype(str) == ablation)]
            if not hit.empty:
                mat[i, j] = float(hit.iloc[0][metric])
    return cities, ablations, mat


def plot_heatmap(df: pd.DataFrame, out_dir: Path) -> dict[str, str]:
    plt.rcParams.update(
        {
            "font.family": "Arial",
            "font.size": 8,
            "axes.titlesize": 9,
            "axes.labelsize": 8,
            "xtick.labelsize": 7,
            "ytick.labelsize": 7,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )

    max_abs = 0.0
    matrices = []
    for metric, _, _, _ in METRIC_PANELS:
        cities, ablations, mat = _panel_matrix(df, metric)
        matrices.append((cities, ablations, mat))
        finite = mat[np.isfinite(mat)]
        if finite.size:
            max_abs = max(max_abs, float(np.nanmax(np.abs(finite))))
    vmax = max(0.05, math.ceil(max_abs * 100) / 100)

    fig, axes = plt.subplots(3, 1, figsize=(7.2, 5.8), constrained_layout=True)
    cmap = plt.get_cmap("RdBu_r")
    im = None
    for ax, (metric, panel, title, fmt), (cities, ablations, mat) in zip(axes, METRIC_PANELS, matrices):
        im = ax.imshow(mat, cmap=cmap, vmin=-vmax, vmax=vmax, aspect="auto")
        ax.set_yticks(np.arange(len(cities)), labels=cities)
        ax.set_xticks(np.arange(len(ablations)), labels=[ABLATION_LABELS[a] for a in ablations])
        ax.tick_params(axis="x", rotation=35)
        for label in ax.get_xticklabels():
            label.set_horizontalalignment("right")
        ax.set_title(f"{panel}. {title}: graph-on change vs baseline", loc="left", fontweight="bold")
        ax.set_xlabel("")
        for i in range(mat.shape[0]):
            for j in range(mat.shape[1]):
                val = mat[i, j]
                if not np.isfinite(val):
                    continue
                text_color = "white" if abs(val) > vmax * 0.55 else "black"
                ax.text(j, i, format(val, fmt), ha="center", va="center", fontsize=6.5, color=text_color)
        ax.spines[:].set_visible(False)
        ax.set_xticks(np.arange(-0.5, len(ablations), 1), minor=True)
        ax.set_yticks(np.arange(-0.5, len(cities), 1), minor=True)
        ax.grid(which="minor", color="white", linewidth=0.8)
        ax.tick_params(which="minor", bottom=False, left=False)

    assert im is not None
    cbar = fig.colorbar(im, ax=axes, shrink=0.88, pad=0.01)
    cbar.set_label("Difference from same-city baseline")

    base = out_dir / "e2_ablation_effect_heatmap"
    outputs = {}
    for ext, kwargs in {
        "png": {"dpi": 400},
        "pdf": {},
        "svg": {},
    }.items():
        path = base.with_suffix(f".{ext}")
        fig.savefig(path, bbox_inches="tight", **kwargs)
        outputs[ext] = str(path)
    plt.close(fig)
    return outputs


def _fmt_delta(df: pd.DataFrame, city_label: str, ablation: str, metric: str) -> str:
    hit = df[(df["city_label"] == city_label) & (df["ablation"].astype(str) == ablation)]
    if hit.empty:
        return "NA"
    return f"{float(hit.iloc[0][metric]):+.3f}"


def write_interpretation(df: pd.DataFrame, validation: dict, out_dir: Path) -> Path:
    cities = list(CITY_LABELS.values())

    def city_values(ablation: str, metric: str) -> str:
        return ", ".join(f"{city}: {_fmt_delta(df, city, ablation, metric)}" for city in cities)

    near_zero = ", ".join(validation["near_zero_effect_ablations_all_cities"]) or "none"
    lines = [
        "# E2 Ablation Matrix Interpretation -- 2026-07-02",
        "",
        "## Data integrity",
        "",
        f"- Matrix completeness: {validation['observed_cells']}/{validation['expected_cells']} city-ablation cells.",
        f"- Each cell contains 10 seeds: {validation['all_n_runs_are_10']}.",
        "- Source aggregate: `trace_output/E2_ablation_matrix/e2_ablation_summary.csv`.",
        "- Derived table: `figures/e2_ablation_paper_table.csv`.",
        "- Figure exports: `figures/e2_ablation_effect_heatmap.svg/.pdf/.png`.",
        "",
        "## Main quantitative signals",
        "",
        "1. `hard_switch` and `soft_switch` are the dominant perturbations. "
        f"Herding ratio changes are {city_values('hard_switch', 'herd_ratio_on_vs_baseline')} for `hard_switch` "
        f"and {city_values('soft_switch', 'herd_ratio_on_vs_baseline')} for `soft_switch`.",
        "",
        "2. Disabling flee behaviour produces the expected substitution away from fleeing. "
        f"`no_flee` changes flee ratio by {city_values('no_flee', 'flee_ratio_on_vs_baseline')}, "
        f"while herding increases by {city_values('no_flee', 'herd_ratio_on_vs_baseline')}.",
        "",
        "3. `no_outcome_feedback` and `i1_minimal` produce identical graph-on deltas in the current matrix. "
        "This suggests that, under the present implementation and parameter regime, the additional flags disabled by "
        "`i1_minimal` do not add measurable effects beyond disabling outcome feedback.",
        "",
        f"4. Near-zero presets across all cities at |delta| < {validation['near_zero_threshold_abs_delta']}: {near_zero}. "
        "These should be treated as mechanism-scope diagnostics, not as evidence that the mechanisms are scientifically irrelevant.",
        "",
        "5. The 2026-07-02 audit smoke (`trace_output/smoke_tests/E2_audit_smoke/`) confirms that every non-baseline preset "
        "was applied to all 18 SwitchParams holders in the representative Xiamen run. Runtime read counters also show that "
        "`enable_hysteresis` is not read by the MML action-choice path; its near-zero result is therefore expected and should "
        "be framed as a legacy-sigmoid-only mechanism. By contrast, `enable_behavior_demo` and `enable_outcome_feedback` are "
        "read in the active stress/feedback path; `no_behavior_demo` is near-zero in the present end-point metrics, whereas "
        "`no_outcome_feedback` and `i1_minimal` produce identical non-zero deltas.",
        "",
        "## IJDRR writing decision",
        "",
        "- Safe to write in main-text §5.5: the E2 matrix is executable and aggregated; `hard_switch`, `soft_switch`, `no_flee`, and `no_outcome_feedback/i1_minimal` show interpretable behavioural substitution or feedback-removal patterns.",
        "- Write with caveats: `no_hysteresis` should be described as outside the active MML mechanism rather than as a failed ablation; `no_behavior_demo` should be described as an endpoint-insensitive perturbation under the current scenario.",
        "- Keep supplementary/provenance: `distance_only_store` and `no_info_network` remain useful diagnostics for the store-information layer, but their near-zero graph-on deltas should be reported as limited-scope evidence unless full-run audit counters are regenerated.",
        "",
        "## Remaining technical checks after manuscript insertion",
        "",
        "1. If E2 becomes a headline result, rerun the full 330-run matrix once with the new audit counters so each formal cell carries read-count provenance.",
        "2. For `distance_only_store`, verify whether store-choice utility terms (`lambda_f`, `lambda_c`) are active in the full graph-on MML path under the tested blackout scenario.",
        "3. Keep `no_hysteresis` in the supplementary audit table or move it to the legacy sigmoid benchmark, because the active MML path does not use that switch.",
        "4. If near-zero effects persist after full-run auditing, report them as robustness/scope findings with explicit caveats.",
        "",
    ]
    out_path = out_dir / "e2_ablation_interpretation.md"
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-base", default="E2_ablation_matrix")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    df, input_dir = load_summary(args.input_base)
    out_dir = input_dir / "figures"
    out_dir.mkdir(parents=True, exist_ok=True)

    validation = validate(df)
    validation_path = out_dir / "e2_ablation_validation.json"
    validation_path.write_text(json.dumps(validation, ensure_ascii=False, indent=2), encoding="utf-8")
    table_path = write_paper_table(df, out_dir)
    fig_paths = plot_heatmap(df, out_dir)
    interpretation_path = write_interpretation(df, validation, out_dir)

    print(
        json.dumps(
            {
                "input": str(input_dir),
                "validation": str(validation_path),
                "paper_table": str(table_path),
                "interpretation": str(interpretation_path),
                "figures": fig_paths,
                "near_zero_effect_ablations_all_cities": validation["near_zero_effect_ablations_all_cities"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
