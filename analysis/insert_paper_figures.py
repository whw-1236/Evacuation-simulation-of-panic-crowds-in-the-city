from __future__ import annotations

import shutil
from pathlib import Path


PAPER_DIR = Path(r"F:\IJDRR write\论文初稿模块")
TARGETS = [
    PAPER_DIR / "IJDRR_full_paper_v2_refs_resolved.md",
    PAPER_DIR / "IJDRR_main_manuscript_v2_refs_resolved.md",
]
BACKUP_SUFFIX = ".bak_20260704_figures"
REL = "../Crowds_sim/Evacuation-simulation-of-panic-crowds-in-the-city"


FIG1 = f"""![Fig. 1]({REL}/paper_figures/Fig1_model_framework.png)

*Fig. 1. Network-embedded blackout crowd simulation framework. The figure summarises the stress-SFM-MNL-road/shelter feedback loop used in the manuscript: outage-induced stress enters the psychological layer, stress-conditioned MNL utilities select tactical actions, the social-force and road-graph layers realise movement, and shelter visibility feeds back into the feasible choice set. Source: model specification in Sections 3.1-3.7; rendered as `paper_figures/Fig1_model_framework.png`.*
"""

FIG2 = f"""![Fig. 2]({REL}/paper_figures/Fig2_study_area_network_poi.png)

*Fig. 2. Spatial substrates for the three-city validation. Panels show the routed road graph, emergency shelters and supply POIs for Xiamen / Siming, Shenyang / Shenhe and Beijing / Dongcheng after filtering POIs to the graph envelope used by the path planner. Source: `road_graph_cache/*.graphml` and district POI tables; rendered as `paper_figures/Fig2_study_area_network_poi.png`.*
"""

FIG3 = f"""![Fig. 3]({REL}/paper_figures/Fig3_mnl_vis_gate.png)

*Fig. 3. Visibility-conditioned MNL choice-set expansion. In graph-off runs the flee alternative is infeasible because shelter visibility is zero, so the tactical set is restricted to home, hoard and herd. In graph-on runs a routed shelter path activates the flee utility, allowing the road/shelter layer to substitute shelter seeking against herding. Source: model specification in Section 3.3.2; rendered as `paper_figures/Fig3_mnl_vis_gate.png`.*
"""

FIG53 = f"""![Fig. 5.3]({REL}/paper_figures/Fig6_bc_load_three_city.png)

*Fig. 5.3 (E6.4-E6.5) - three-city comparison of node betweenness centrality (BC) against observed incoming road load under the graph-on panic+shelter regime. Each panel overlays all road-graph nodes and the loaded subset; the y-axis uses \\(\\log_{{10}}(\\mathrm{{cumulative\\ load}}+1)\\) so that zero-load and high-load nodes remain visible in the same panel. Loaded-subset Pearson r values are reported in the panel titles. Source: `trace_output/M4_MML_F2_home_dist/*/edge_observations.csv` and `road_graph_cache/*.graphml`; rendered as `paper_figures/Fig6_bc_load_three_city.png`.*
"""


def insert_after(text: str, anchor: str, snippet: str, marker: str) -> tuple[str, bool]:
    if marker in text:
        return text, False
    if anchor not in text:
        raise ValueError(f"Anchor not found: {anchor[:80]!r}")
    return text.replace(anchor, anchor + "\n\n" + snippet.rstrip() + "\n", 1), True


def replace_fig53(text: str) -> tuple[str, bool]:
    if "paper_figures/Fig6_bc_load_three_city.png" in text:
        return text, False

    start_marker = f"![Fig. 5.3]({REL}/trace_output/M4_MML_F2_home_dist/_corr/"
    start = text.find(start_marker)
    if start == -1:
        raise ValueError("Existing Fig. 5.3 image block not found")

    next_section = text.find("\n## 5.4", start)
    if next_section == -1:
        raise ValueError("Section 5.4 marker not found after Fig. 5.3")

    replacement = FIG53.rstrip() + "\n\n"
    return text[:start] + replacement + text[next_section + 1 :], True


def ensure_main_figure_order(text: str) -> tuple[str, bool]:
    fig1_block = FIG1.rstrip()
    fig2_block = FIG2.rstrip()
    fig3_block = FIG3.rstrip()

    pos1 = text.find(fig1_block)
    pos2 = text.find(fig2_block)
    pos3 = text.find(fig3_block)
    if min(pos1, pos2, pos3) == -1 or pos1 < pos2 < pos3:
        return text, False

    removal = "\n\n" + fig2_block + "\n\n"
    if removal not in text:
        raise ValueError("Fig. 2 block found, but surrounding blank lines do not match expected format")
    text = text.replace(removal, "\n\n", 1)

    pos1 = text.find(fig1_block)
    if pos1 == -1:
        raise ValueError("Fig. 1 block not found after Fig. 2 removal")
    insert_at = pos1 + len(fig1_block)
    text = text[:insert_at] + "\n\n" + fig2_block + text[insert_at:]
    return text, True


def update_file(path: Path) -> list[str]:
    original = path.read_text(encoding="utf-8")
    text = original
    changes: list[str] = []

    fig1_anchor = (
        r"**Unified notation.** Throughout, \(i,j\) index agents; "
        r"\(\mathbf{x}_i,\mathbf{v}_i,m_i\) are position, velocity and mass; "
        r"\(\boldsymbol{\psi}_i=\langle\psi_i^{O},\psi_i^{C},\psi_i^{E},\psi_i^{A},\psi_i^{N}\rangle\) is the OCEAN personality vector. "
        r"The affective core is a single **master stress state** \(\sigma_i(t)\in[0,1]\), from which an expressed emotion \(E_i(t)\) and a panic \(P_i(t)\) are derived (§3.2). "
        r"The behavioural goal switch (§3.3.2) is driven by \(\sigma_i\)."
    )
    text, changed = insert_after(
        text,
        fig1_anchor,
        FIG1,
        "paper_figures/Fig1_model_framework.png",
    )
    if changed:
        changes.append("inserted Fig. 1")

    fig3_anchor = (
        "This visibility gate operationalises the dichotomy of [8], who report that flow-following is conditional on alternative-visibility: "
        "when alternatives are clearly visible, decision-makers actively trade off distance against congestion rather than following crowds. "
        "In our model the road graph is what makes shelters *visible* — and §5.1 shows that this single change shifts the population from herd-dominated to flee-dominated evacuation."
    )
    text, changed = insert_after(
        text,
        fig3_anchor,
        FIG3,
        "paper_figures/Fig3_mnl_vis_gate.png",
    )
    if changed:
        changes.append("inserted Fig. 3")

    fig2_anchor = (
        "**Spatial scale.** The validation uses three Chinese urban districts with different road and POI structures: "
        "Xiamen / Siming, Shenyang / Shenhe and Beijing / Dongcheng. "
        "District-level OpenStreetMap road graphs are loaded from local graph caches (5 160-9 800 nodes, 15 100-25 600 edges) "
        "and reduced to the connected component used by the path planner. Emergency shelters and shops are loaded from district-level POI tables."
    )
    text, changed = insert_after(
        text,
        fig2_anchor,
        FIG2,
        "paper_figures/Fig2_study_area_network_poi.png",
    )
    if changed:
        changes.append("inserted Fig. 2")

    text, changed = replace_fig53(text)
    if changed:
        changes.append("replaced Fig. 5.3")

    text, changed = ensure_main_figure_order(text)
    if changed:
        changes.append("ordered Fig. 1-Fig. 3")

    if text != original:
        backup = path.with_name(path.name + BACKUP_SUFFIX)
        if not backup.exists():
            shutil.copy2(path, backup)
        path.write_text(text, encoding="utf-8", newline="")

    return changes


def main() -> None:
    for target in TARGETS:
        changes = update_file(target)
        if changes:
            print(f"{target.name}: " + "; ".join(changes))
        else:
            print(f"{target.name}: already up to date")


if __name__ == "__main__":
    main()
