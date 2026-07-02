# -*- coding: utf-8 -*-
"""Insert the E2 ablation result block into the manuscript drafts."""
from __future__ import annotations

import re
from pathlib import Path


PAPER_ROOT = Path(r"F:\IJDRR write\论文初稿模块")
EXP_PATH = PAPER_ROOT / "04_Experimental_Design_draft_v1.md"
RESULTS_PATH = PAPER_ROOT / "05_Results_M4_draft_v1.md"


E2_SECTION = r"""## 5.5 E2: Mechanism ablation of the tactical-choice layer

**Question.** The preceding results show that the road graph inserts a shelter-seeking alternative into the choice set and induces a herd-to-flee substitution. E2 asks a narrower mechanism question: which switches in the tactical-choice layer actually drive the population-level end-point indicators, and which switches are outside the active MML pathway or insensitive under the present blackout scenario?

**Setup.** We run a three-city ablation matrix over the same graph-on protocol used in §5.1: Xiamen / Siming, Shenyang / Shenhe and Beijing / Dongcheng; N = 800 residents; seeds 42-51; outage at step 16; 120 steps. The matrix contains 11 presets: the baseline `none`; two legacy switching benchmarks (`hard_switch`, `soft_switch`, both setting `use_mml=False`); four MML-path perturbations (`no_info_network`, `distance_only_store`, `no_inertia`, `no_flee`); three I1 stress/feedback switches (`no_hysteresis`, `no_outcome_feedback`, `no_behavior_demo`); and a combined `i1_minimal` preset. We report graph-on differences relative to the same-city baseline, so the numbers below are mechanism effects after the road graph and shelter alternative are already active.

**Audit status.** The full E2 matrix is complete at 33/33 city-preset cells, with 10 seeds in each cell. After the matrix was generated, we added runtime switch instrumentation and re-ran a representative Xiamen smoke audit (`trace_output/smoke_tests/E2_audit_smoke/`). The audit confirms that each non-baseline preset is applied to all 18 `SwitchParams` holders in that representative run. It also clarifies mechanism scope: `enable_hysteresis` is read only in the legacy `use_mml=False` path, whereas the active MML path reads `use_mml`, `enable_flee_behavior`, `mu`, `gamma` and the outcome-feedback fields. A full 330-run rerun with read-count provenance remains desirable for archival reproducibility, but the current matrix is sufficient for a cautiously worded main-text E2 result.

**Result 1 -- replacing MML with the legacy switching rules is the largest perturbation.** Both `hard_switch` and `soft_switch` increase the herding share in every city (Table 5.4). The effect is strongest in Shenyang and Beijing, where `hard_switch` raises `herd_ratio` by +0.328 and +0.342, respectively; Xiamen still increases by +0.171. The same pattern under `soft_switch` shows that the key perturbation is not only the steepness of the thresholds but the change from a mutually exclusive random-utility choice set to the legacy additive switching logic.

**Result 2 -- disabling flee produces the expected substitution back into herding.** The `no_flee` preset reduces the flee share by exactly the baseline flee level in each city (−0.264, −0.315 and −0.318) and increases herding by +0.133 to +0.169. This is the mirror image of §5.1: when the shelter alternative is removed from the MML choice set, agents that would have selected a path-planned shelter route are reassigned mainly to herding rather than to a new psychological state.

**Result 3 -- outcome feedback is the active I1 add-on under the current scenario.** `no_outcome_feedback` and `i1_minimal` produce identical graph-on deltas in all three cities: herding increases by +0.088, +0.055 and +0.053 in Xiamen, Shenyang and Beijing, respectively. Because `i1_minimal` additionally disables hysteresis, behaviour-demonstration effects and inquiry, this equality indicates that the measurable I1 contribution in the present end-point indicators is carried by outcome feedback. The equality should not be over-interpreted as a universal absence of the other mechanisms; it is a statement about this scenario, these metrics and the current MML pathway.

| Preset | Switch-level intervention | Mean graph-on Δ vs same-city baseline | Mechanistic reading |
|---|---|---|---|
| `hard_switch` | `use_mml=False`, steep thresholds | Δherd = +0.171 / +0.328 / +0.342; Δflee = −0.082 / +0.011 / +0.004 | Legacy switching strongly restores herding relative to MML. |
| `soft_switch` | `use_mml=False`, shallow thresholds | Δherd = +0.169 / +0.320 / +0.335; Δflee = −0.092 / +0.002 / −0.002 | Similar to `hard_switch`; the formulation change dominates threshold steepness. |
| `no_flee` | `enable_flee_behavior=False` | Δherd = +0.133 / +0.169 / +0.163; Δflee = −0.264 / −0.315 / −0.318 | Removes the shelter alternative and reallocates agents mainly into herding. |
| `no_outcome_feedback` | `enable_outcome_feedback=False` | Δherd = +0.088 / +0.055 / +0.053; Δflee = +0.005 / −0.028 / −0.014 | Outcome feedback is a measurable I1 stabiliser in the active MML path. |
| `i1_minimal` | disables outcome feedback, hysteresis, behaviour demo and inquiry | Same as `no_outcome_feedback` | Additional disabled I1 flags add no end-point effect beyond outcome feedback here. |
| `no_info_network`, `distance_only_store`, `no_hysteresis`, `no_behavior_demo` | store-information or path-scope switches | all headline deltas < 0.0005 in every city | Scope diagnostics; not evidence of scientific irrelevance. |

*Table 5.4 (E2). Mechanism-ablation effects on graph-on end-point indicators. Each cell is the mean over n = 10 seeds, expressed as a difference from the same-city `none` baseline. City order inside each triple is Xiamen / Siming, Shenyang / Shenhe and Beijing / Dongcheng. Source: `trace_output/E2_ablation_matrix/figures/e2_ablation_paper_table.csv`.*

**Result 4 -- near-zero switches identify scope boundaries, not failed mechanisms.** Four presets are near-zero across all cities at \(|\Delta|<5\times10^{-4}\): `no_info_network`, `distance_only_store`, `no_hysteresis` and `no_behavior_demo`. The audit explains at least one of these exactly: `enable_hysteresis` belongs to the legacy sigmoid path and is not read by the MML action-choice path, so a near-zero MML result is expected. The store-information presets remain valid diagnostics of the supply-choice sublayer, but the current blackout/shelter scenario is dominated by the flee-herd competition rather than by store redistribution. `no_behavior_demo` should likewise be treated as end-point-insensitive under this scenario; it may matter for transient stress trajectories or a different behavioural observable.

**Reading.** E2 supports the central mechanism claim of §5 without overextending it. The strongest effects come from the mutually exclusive MML formulation itself and from the presence or absence of the flee alternative. Outcome feedback is the only additional I1 switch that materially shifts the reported end-point indicators. The near-zero switches are therefore retained as supplementary scope diagnostics and as targets for a full read-count rerun, not used as negative scientific findings.

![Fig. 5.4](../Crowds_sim/Evacuation-simulation-of-panic-crowds-in-the-city/trace_output/E2_ablation_matrix/figures/e2_ablation_effect_heatmap.png)

*Fig. 5.4 (E2) -- heatmap of graph-on changes relative to the same-city baseline for mean stress, herding ratio and flee ratio. The strongest positive herding deltas occur under legacy hard/soft switching, while `no_flee` removes the shelter-seeking share and reallocates agents mainly into herding. Source: `trace_output/E2_ablation_matrix/figures/e2_ablation_effect_heatmap.png`.*

"""


def update_experiment_design() -> None:
    text = EXP_PATH.read_text(encoding="utf-8")
    text = text.replace(
        "> **Draft v2 — M4/E6 main-paper scope.** This section now defines the experimental design for the M4 cross-city validation block reported in §5.1-§5.3. The broader E1-E5 programme remains part of the project roadmap, but it is not claimed as completed main-text evidence in this manuscript. This scope choice keeps the submitted paper aligned with the available results: network-mediated shelter seeking, MML herd-to-flee substitution, population-size robustness, and centrality failure.",
        "> **Draft v3 — M4/E6 plus E2 main-paper scope.** This section defines the experimental design for the M4 cross-city validation block reported in §5.1-§5.3 and the E2 mechanism-ablation block reported in §5.5. The broader E1/E3-E5 programme remains part of the project roadmap, but it is not claimed as completed main-text evidence in this manuscript. This scope choice keeps the submitted paper aligned with the available results: network-mediated shelter seeking, MML herd-to-flee substitution, population-size robustness, centrality failure, and SwitchParams-level mechanism ablation.",
    )
    text = text.replace(
        ".\\.venv\\run_in_crowds_env.ps1 analysis\\f2_compare_r.py\n```",
        ".\\.venv\\run_in_crowds_env.ps1 analysis\\f2_compare_r.py\n"
        ".\\.venv\\run_in_crowds_env.ps1 scripts\\run_e2_ablation_matrix.py\n"
        ".\\.venv\\run_in_crowds_env.ps1 analysis\\e2_aggregate.py --input-base E2_ablation_matrix\n"
        ".\\.venv\\run_in_crowds_env.ps1 analysis\\e2_make_figures.py --input-base E2_ablation_matrix\n```",
    )
    text = text.replace(
        "Outputs are written under `trace_output/M4_MML_*/`. The sigmoid fallback used for Supplementary Tables S1-S3 is reproduced by setting `BLACKOUT_USE_MML=0` before the same workflow.",
        "M4/E6 outputs are written under `trace_output/M4_MML_*/`; E2 outputs are written under `trace_output/E2_ablation_matrix/`. The sigmoid fallback used for Supplementary Tables S1-S3 is reproduced by setting `BLACKOUT_USE_MML=0` before the same workflow.",
    )
    text = text.replace(
        "The project matrix also defines mechanism-validation, ablation, emergent-phenomena, policy and sensitivity blocks (E1-E5). These blocks remain useful for the broader research programme, but they are not treated as completed evidence in this manuscript. In particular, the E2 ablation matrix now has runner-level support through `scripts/run_ablation.py --switch-ablation`, but the multi-city, multi-seed batches and aggregation tables are not yet complete; E3 hotspot/Gini outputs and E4 policy panels likewise require additional logging and batch execution. We therefore reserve E1-E5 for future validation or supplementary expansion rather than promising them as §5.4-§5.8 results in the present paper.",
        "The project matrix also defines mechanism-validation, ablation, emergent-phenomena, policy and sensitivity blocks (E1-E5). E2 is now complete at the SwitchParams mechanism level and is reported in §5.5: the batch covers three cities, seeds 42-51 and 11 ablation presets, with aggregation, figure exports and a representative runtime switch audit. OCEAN/no-personality ablation is not included because it requires controlling resident attribute sampling rather than only changing `SwitchParams`. E1 and E3-E5 remain useful for the broader research programme, but they are not treated as completed main-text evidence in this manuscript.",
    )
    text = text.replace(
        "This scope decision is deliberate. The M4/E6 block already forms a complete IJDRR-style modelling argument: a real road-and-shelter graph changes the behavioural choice set, MML exposes the resulting herd-to-flee substitution, the effect is stable over population size, and topology-only centrality fails to predict the resulting road load.",
        "This scope decision is deliberate. The M4/E6 block forms the main IJDRR-style modelling argument: a real road-and-shelter graph changes the behavioural choice set, MML exposes the resulting herd-to-flee substitution, the effect is stable over population size, and topology-only centrality fails to predict the resulting road load. E2 then tests the internal mechanism switches that support this argument without expanding the paper into the unfinished E1/E3-E5 programme.",
    )
    EXP_PATH.write_text(text, encoding="utf-8")


def update_results() -> None:
    text = RESULTS_PATH.read_text(encoding="utf-8")
    lead = (
        "> **Draft v2 — M4/E6 and E2 results.** This section reports the completed M4/E6 cross-city validation block (§5.1-§5.3) and the E2 SwitchParams-level mechanism-ablation block (§5.5). They address two organising questions for the network-embedded model: *what does grounding the social-force layer on a real road network change about the panic cascade, and which tactical-choice mechanisms materially drive that change?* §5.1 establishes that the cascade simultaneously activates a network-mediated flee channel and suppresses the herd channel through discrete-choice substitution. §5.2 shows this flee channel is a structural property of the model and invariant over the tested population-size range. §5.3 shows that standard node betweenness centrality fails as a predictor of observed road load when the panic+shelter loop is active. §5.5 then ablates the tactical-choice switches behind this evidence chain.\n>\n"
    )
    text = re.sub(
        r"^> \*\*Draft v1[^\n]*\n>\n",
        lead,
        text,
        count=1,
        flags=re.MULTILINE,
    )
    text = text.replace(
        "> Numerical results in this draft are reproduced from `trace_output/M4_MML_*/`; per-figure provenance is given in the captions. Citation placeholders `[REF: ...]` mark items to be resolved against the bibliography before submission.",
        "> Numerical results in §5.1-§5.3 are reproduced from `trace_output/M4_MML_*/`; §5.5 is reproduced from `trace_output/E2_ablation_matrix/`. Per-figure provenance is given in the captions. Citation placeholders `[REF: ...]` mark items to be resolved against the bibliography before submission.",
    )
    marker = "\n---\n\n## Cross-section summary"
    if "## 5.5 E2: Mechanism ablation of the tactical-choice layer" in text:
        start = text.index("## 5.5 E2: Mechanism ablation of the tactical-choice layer")
        end = text.index(marker, start)
        text = text[:start] + E2_SECTION + text[end:]
    else:
        text = text.replace(marker, "\n" + E2_SECTION + marker, 1)

    text = text.replace(
        "Three findings carry the cross-city M4 program:",
        "Four findings carry the results section:",
    )
    e2_summary = (
        "\n4. **The E2 mechanism ablation identifies MML/flee competition and outcome feedback as the active switches in the present evidence chain.** Legacy hard/soft switching increases herding by +0.17 to +0.34 across cities, while disabling flee removes the 0.26-0.32 shelter-seeking share and reallocates agents mainly into herding. `no_outcome_feedback` and `i1_minimal` produce identical non-zero deltas, indicating that outcome feedback is the measurable I1 add-on for the current end-point indicators. Near-zero presets are reported as scope diagnostics, especially `no_hysteresis`, which the audit shows is outside the active MML path.\n"
    )
    text = text.replace(
        "\nTogether, these findings populate the completed M4 / E6 evidence block defined in §4.3:",
        e2_summary
        + "\nTogether, these findings populate the completed M4/E6 and E2 evidence blocks defined in §4.3-§4.4:",
    )
    text = text.replace(
        "E6.6 is treated as a demand-aware centrality extension in §6.1 rather than as completed main-text evidence.",
        "E6.6 is treated as a demand-aware centrality extension in §6.1 rather than as completed main-text evidence; E2 is reported in §5.5 as a completed SwitchParams-level ablation, with OCEAN/no-personality left outside the matrix because it requires resident-attribute sampling control.",
    )
    RESULTS_PATH.write_text(text, encoding="utf-8")


def main() -> None:
    update_experiment_design()
    update_results()
    print(f"updated={EXP_PATH}")
    print(f"updated={RESULTS_PATH}")


if __name__ == "__main__":
    main()
